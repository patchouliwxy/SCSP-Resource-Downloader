import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import Mock,patch
import scsp_audio_index as ai
from test_scsp_web import resource,catalog


def table(name,columns,rows):
    strings=bytearray();data=bytearray();offsets={}
    def text(s):
        if s not in offsets:offsets[s]=len(strings);strings.extend(s.encode()+b'\0')
        return offsets[s]
    text(name);schema=b'';values=b'';width=sum(struct.calcsize('>'+ai.FORMATS[t]) for _,t in columns)
    for key,kind in columns:schema+=struct.pack('>BI',0x50|kind,text(key))
    for row in rows:
        for key,kind in columns:
            value=row[key]
            if kind==10:values+=struct.pack('>I',text(value))
            elif kind==11:values+=struct.pack('>II',len(data),len(value));data.extend(value)
            else:values+=struct.pack('>'+ai.FORMATS[kind],value)
    row_at=32+len(schema);string_at=row_at+len(values);data_at=string_at+len(strings);size=data_at+len(data)
    return struct.pack('>4sIHHIIIHHI',b'@UTF',size-8,1,row_at-8,string_at-8,data_at-8,0,len(columns),width,len(rows))+schema+values+strings+data


def bank(cues):
    sub=table('CueNameTable',[('CueName',10),('CueIndex',2)],cues)
    return table('Header',[('CueNameTable',11)],[{'CueNameTable':sub}])


class AudioCueTests(unittest.TestCase):
    def test_reads_actual_table_keeps_cue_indices_and_aliases(self):
        expected=[{'CueName':'s01_001_0030_01mano','CueIndex':9},{'CueName':'s01_001_0040_02hiori','CueIndex':2},
                  {'CueName':'alias_01mano','CueIndex':9}]
        b=bank(expected);cues=ai.parse_cues(lambda at,n:b[at:at+n],len(b))
        self.assertEqual([c['cue_index'] for c in cues],[9,2,9])
        self.assertEqual([c['cue_name'] for c in cues],[c['CueName'] for c in expected])

    def test_bounds_missing_layout_and_empty_table(self):
        for b in (b'@UTF',bank([{'CueName':'test_01mano','CueIndex':1}])[:-4]):
            with self.assertRaises((ValueError,struct.error)):ai.parse_cues(lambda at,n:b[at:at+n],len(b))
        b=table('Header',[('Other',4)],[{'Other':0}])
        with self.assertRaisesRegex(ValueError,'CueNameTable'):ai.parse_cues(lambda at,n:b[at:at+n],len(b))
        b=bank([]);self.assertEqual(ai.parse_cues(lambda at,n:b[at:at+n],len(b)),[])

    def test_roles_only_from_explicit_known_suffix_and_preserve_unknown(self):
        known={'01':'櫻木 真乃','02':'風野 灯織','03':'八宮 めぐる'}
        self.assertEqual(ai.cue_characters('s01_001_0030_01mano; s01_001_0040_02hiori [pre]',known),['01','02'])
        for name in ('s01_01010000_00','inst_event_01','voice_99unknown','01mano','s02_01010000'):
            self.assertEqual(ai.cue_characters(name,known),[])

    def test_server_ignoring_range_never_downloads_full_audio(self):
        e=resource('s01_test.acb');e.update(size=1000000,resource_type=64)
        response=Mock(status=200);connection=Mock();connection.getresponse.return_value=response
        with tempfile.TemporaryDirectory() as temp,patch.object(ai._connections,'conn',connection,create=True):
            reader=ai.RangeReader(e,temp)
            with self.assertRaisesRegex(ValueError,'honor bounded Range'):reader(0,32)
            response.read.assert_not_called();response.close.assert_called();connection.close.assert_called()

    def test_range_header_validates_total_and_bounded_read(self):
        e=resource('s01_test.acb');e.update(size=1000000,resource_type=64)
        response=Mock(status=206);response.getheader.side_effect=lambda key: 'bytes 0-4095/1000000' if key=='Content-Range' else 'etag'
        response.read.return_value=b'a'*4096;connection=Mock();connection.getresponse.return_value=response
        with tempfile.TemporaryDirectory() as temp,patch.object(ai._connections,'conn',connection,create=True):
            reader=ai.RangeReader(e,temp);self.assertEqual(reader(0,32),b'a'*32);self.assertEqual(reader(12,5),b'a'*5)
            self.assertEqual(reader.fetched,4096);self.assertEqual(connection.request.call_count,1)
            self.assertEqual(connection.request.call_args.kwargs['headers']['Range'],'bytes=0-4095')

    def test_version_reuses_unchanged_content_and_changed_content_is_pending(self):
        with tempfile.TemporaryDirectory() as temp:
            e=resource('s01_01010000_00.acb');c=catalog([e]);c.character_names={'01':'真乃','02':'灯織'}
            index=ai.AudioIndex(c,Path(temp)/'index',Path(temp)/'cache')
            record=dict(identity=ai.fingerprint(e),cues=[{'cue_index':9,'cue_name':'s01_001_0030_01mano'},
                {'cue_index':2,'cue_name':'s01_001_0040_02hiori'}, {'cue_index':5,'cue_name':'unknown'}],cue_count=3,metadata_bytes_fetched=4096)
            ai.save_json(index.bank_path(e),record);index.attach(e,record)
            self.assertEqual(c.search(scope='audio',character='02')['total'],1)
            self.assertEqual(c.search(scope='audio',query='灯織')['total'],1)
            self.assertEqual(index.bank(e['id'])['unknown_cues'],1)
            self.assertEqual([r['id'] for r in c.search()['items'][0]['audio_characters']],['01','02'])
            newer=catalog([e]);newer.data['resource_version']='next';newer.character_names={'01':'櫻木 真乃','02':'風野 灯織'}
            reused=ai.AudioIndex(newer,index.root,index.cache)
            self.assertTrue(reused.status()['complete']);self.assertNotEqual(reused.version_file,index.version_file)
            self.assertEqual(reused.bank(e['id'])['characters'][0]['name'],'櫻木 真乃')
            e2=dict(e,checksum=2);changed=catalog([e2]);changed.character_names=newer.character_names
            pending=ai.AudioIndex(changed,index.root,index.cache);self.assertEqual(pending.status()['indexed'],0)

    def test_failures_are_reported_and_retry_is_explicit(self):
        with tempfile.TemporaryDirectory() as temp:
            e=resource('s01_01010000_00.acb');c=catalog([e]);index=ai.AudioIndex(c,Path(temp)/'index',Path(temp)/'cache')
            with patch.object(ai,'read_bank',side_effect=ValueError('unsupported layout')):
                index.start();index.worker.join(timeout=5)
            self.assertEqual(index.status()['failed'],1);self.assertFalse(index.status()['complete'])
            self.assertNotIn('audio_indexed',c.rows[0][0])
