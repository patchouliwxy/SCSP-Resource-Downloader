import json
import tempfile
import unittest
import struct
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import build_wardrobe as builder
from scsp_wardrobe import Wardrobe, Thumbnails
import scsp_update as updater


class WardrobeTests(unittest.TestCase):
    def test_cached_thumbnail_bypasses_busy_workers_and_reuses_lookup(self):
        from test_scsp_web import resource
        import threading
        entry=resource('product_icon_24_0001001.png');entry['file']='abc'
        catalog=SimpleNamespace(entries=[entry],by_id={entry['id']:entry})
        with tempfile.TemporaryDirectory() as temp:
            thumbs=Thumbnails(catalog,Path(temp)/'thumbs',Path(temp)/'cache')
            (thumbs.root/'abc.png').write_bytes(b'cached')
            for _ in range(4):thumbs.limit.acquire()
            ready=threading.Event()
            worker=threading.Thread(target=lambda:(thumbs.get(entry['id']),ready.set()))
            try:
                worker.start()
                self.assertTrue(ready.wait(1), 'Cached images should not wait for decode workers')
            finally:
                for _ in range(4):thumbs.limit.release()
                worker.join(2)
            with patch.object(builder.core,'dependency_lookup',side_effect=AssertionError('should reuse lookup')):
                self.assertEqual(builder.core.resolve_dependencies([entry],[entry],thumbs.lookup)[1],[])

    def test_variable_arrays_and_exact_id_coverage(self):
        # Header6 hair records: 4 ints, an int array and boolean.
        rows = (b'\6'+struct.pack('<iiiii',1001,1,1,1,1)+struct.pack('<iB',12800,0)+
                b'\6'+struct.pack('<iiiiiB',1002,1,1,22,0,0))
        data=b'prefix'+struct.pack('<i',2)+rows
        parsed=builder.table(data, {'1001':'a','1002':'b'}, 6, builder.hair)
        self.assertEqual(parsed[1001]['linked_resources'],[12800])
        self.assertEqual(parsed[1002]['resource'],22)
        with self.assertRaises(ValueError):
            builder.table(data, {'1001':'a','1003':'b'}, 6, builder.hair)

    def test_wardrobe_version_isolation_character_categories_and_sets(self):
        data=dict(game_version='v', resource_version='r',records=[dict(group='accessory',id=12027,character='12',subtype='earring',category=1,models=[],icon='image')],
                  sets=[dict(id=12001,character='12',parts=[dict(group='accessory',id=12027)])],counts={})
        catalog=SimpleNamespace(data=dict(game_version='v',resource_version='r'),character_names={'12':'杜野 凛世','10':'園田 智代子'})
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'data.json';path.write_text(json.dumps(data))
            wardrobe=Wardrobe(catalog,path)
            self.assertEqual(wardrobe.search('12','accessory','earring')['total'],1)
            self.assertEqual(wardrobe.search('10','accessory')['total'],0)
            self.assertEqual(wardrobe.search('12','set')['items'][0]['missing'],1)
            catalog.data['resource_version']='other'
            self.assertFalse(Wardrobe(catalog,path).metadata()['available'])

    def test_update_builds_and_publishes_wardrobe(self):
        self.assertIn('wardrobe-data.json', updater.PUBLISHED)
        import inspect
        # Runtime callback test below ensures a failed wardrobe layout aborts publication.
        fake_index=dict(game_version='1',resource_version='2',entries=[dict(id='root/raw/'+name,name=name,file=name,size=1) for name in ('localizetext.bytes','masterdata.bytes')])
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(updater.core,'root_manifest'), patch.object(updater.core,'build_index',return_value=fake_index), patch.object(updater.core,'get_file',return_value=b'data'), patch.object(updater.core,'decode_asset',return_value=b'data'), patch.object(updater.build_song_names,'read_text_tables',return_value={}), patch.object(updater.build_song_names,'build',return_value={}), patch.object(updater.build_character_data,'build',return_value={}), patch.object(updater.build_wardrobe,'build',side_effect=ValueError('layout changed')), patch.object(updater,'publish') as publish:
                with self.assertRaisesRegex(ValueError,'layout changed'):
                    updater.update('1','2',Path(temp))
                publish.assert_not_called()


if __name__=='__main__':
    unittest.main()
