import io
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace as NS
import zipfile
import wave
from PIL import Image

import scsp_download as core
import scsp_web as web
from scsp_image_preview import ImagePreviews, texture_image
from song_delivery import select_companions
from generic_motion import lip_data, generic_input, path_hash
from audio_companions import with_audio_pairs
from test_scsp_web import resource, catalog
import test_scsp_web as fixtures


class SongDeliveryTests(unittest.TestCase):
    def fixture(self):
        names=['110_mellow_01.anim','110_mellow_02.anim','110_mellow_01_root.asset',
               '110_mellow_01_exp.json','110_mellow_camera.json','110_mellow_unit.json',
               '110_mellow_sequence.json','mellow.playable','mellow_all.asset','mellow_amana.asset','mellow_lmv.asset']
        es=[resource(n) for n in names]
        selected,song=core.select_song(es,'110_mellow',[1])
        return selected,song

    def test_full_companions_exclude_other_slot_and_postprocess(self):
        es,song=self.fixture()
        chosen,report=select_companions(es,song,dict(expression=True,camera=True,timeline=True,mouth_ids=None))
        names={e['name'] for e in chosen}
        self.assertIn('110_mellow_01.anim',names)
        self.assertNotIn('110_mellow_02.anim',names)
        for suffix in ('_root.asset','_exp.json'):
            self.assertIn('110_mellow_01'+suffix,names)
        for name in ('110_mellow_camera.json','110_mellow_unit.json','110_mellow_sequence.json','mellow.playable','mellow_all.asset','mellow_amana.asset'):
            self.assertIn(name,names)
        self.assertNotIn('mellow_lmv.asset',names)
        self.assertEqual(2,report['mouth_resource_count']);self.assertEqual([],report['mouth_required_ids'])

    def test_explicit_mouth_selection_and_invalid_options(self):
        es,song=self.fixture()
        mouth=next(e for e in es if e['name']=='mellow_all.asset')
        chosen,_=select_companions(es,song,dict(mouth_ids=[mouth['id']]))
        self.assertIn(mouth,chosen)
        self.assertNotIn('mellow_amana.asset',{e['name'] for e in chosen})
        for opts in ({'expression':1},{'mouth_ids':['other']},{'unknown':True}):
            with self.assertRaises(ValueError):select_companions(es,song,opts)


class ImagePreviewTests(unittest.TestCase):
    def payload(self):
        b=io.BytesIO();Image.new('RGBA',(17,23),(255,0,0,80)).save(b,'PNG');return b.getvalue()

    def test_raw_png_dimensions_and_alpha(self):
        im=texture_image(self.payload(),'test.png')
        self.assertEqual((17,23),im.size);self.assertEqual((80,80),im.getchannel('A').getextrema())

    def test_same_name_sprite_is_not_a_second_texture(self):
        def obj(kind):return NS(type=NS(name=kind),read=lambda:NS(m_Name='test',image=Image.new('RGBA',(2,3))))
        with patch('UnityPy.load',return_value=NS(objects=[obj('Texture2D'),obj('Sprite')])):
            self.assertEqual((2,3),texture_image(b'UnityFS','test.png').size)
        with patch('UnityPy.load',return_value=NS(objects=[obj('Texture2D'),obj('Texture2D')])):
            with self.assertRaises(ValueError):texture_image(b'UnityFS','test.png')

    def test_reject_unknown_and_oversize_without_fetch(self):
        with tempfile.TemporaryDirectory() as td:
            e=resource('large.png');e['size']=65*1048576
            manager=ImagePreviews(catalog([e]),Path(td)/'images',Path(td)/'cache')
            try:
                with patch.object(core,'get_file') as fetch:
                    for identity in ('../secret',e['id']):
                        with self.assertRaises(core.DownloadError):manager.start(identity)
                    fetch.assert_not_called()
            finally:manager.pool.shutdown()

    def test_close_during_decode_removes_preview_but_keeps_cache(self):
        with tempfile.TemporaryDirectory() as td:
            e=resource('test.png');manager=ImagePreviews(catalog([e]),Path(td)/'images',Path(td)/'cache')
            manager.cache.mkdir();(manager.cache/'keep').write_bytes(b'original')
            started,proceed=threading.Event(),threading.Event()
            def decode(*args):started.set();proceed.wait(3);return Image.new('RGBA',(17,23))
            with patch.object(core,'get_file',return_value=b'1234UnityFS\0'),patch('scsp_image_preview.texture_image',side_effect=decode):
                job=manager.start(e['id']);self.assertTrue(started.wait(3));manager.release(job['key']);proceed.set();manager.pool.shutdown()
            self.assertFalse((manager.root/job['key']).exists());self.assertTrue((manager.cache/'keep').exists())


class LightPackageTests(unittest.TestCase):
    setUp=fixtures.DownloadTests.setUp
    tearDown=fixtures.DownloadTests.tearDown
    wait=fixtures.DownloadTests.wait

    def test_unconverted_manual_asset_is_delivered_not_silently_omitted(self):
        with patch.object(core,'get_file',return_value=b'1234UnityFS\0'):
            job=self.manager.submit(dict(ids=[self.a['id']],allow_unresolved=True,include_raw=False))
            done=self.wait(job['id']);self.assertEqual('completed',done['status'])
        with zipfile.ZipFile(self.manager.output/(job['id']+'.zip')) as z:
            self.assertEqual(b'UnityFS\0',z.read('resources/'+self.a['id']))
            self.assertFalse(any(p.startswith('bundles/') for p in z.namelist()))
        self.assertFalse((self.manager.output/job['id']/'bundles').exists())

    def test_stage_cleanup_only_new_work_after_checkpoint(self):
        with patch.object(core,'get_file',return_value=b'1234UnityFS\0'),patch.object(self.manager,'package',side_effect=OSError('keep task for QA')):
            job=self.manager.submit(dict(ids=[self.a['id']],allow_unresolved=True));self.wait(job['id'])
        folder=self.manager.output/job['id'];(folder/'animation-export-work').mkdir();(folder/'animation-export-work/old').write_text('preserve')
        plan=dict(cleanup_work=True,export_checkpoints={})
        def action():
            (folder/'animation-export-work').mkdir();(folder/'animation-export-work/new').write_text('temporary')
            (folder/'animations').mkdir();(folder/'animations/new.anim').write_text('anim')
            return dict(clips=[dict(file='animations/new.anim')])
        self.manager.stage(self.manager.jobs[job['id']],plan,'animation','test',action,1)
        self.assertFalse((folder/'animation-export-work').exists())
        self.assertTrue(any(p.read_text()=='preserve' for p in (folder/'history').rglob('old')))
        self.assertTrue(self.manager.checkpoint_valid(folder,plan['export_checkpoints']['animation']))

    def test_song_json_root_and_timeline_survive_light_package(self):
        folder=self.manager.output/'aaaaaaaaaaaa';folder.mkdir()
        es=[resource(n) for n in ('110_mellow_camera.json','110_mellow_01_root.asset','mellow.playable')]
        outputs=[]
        for i,e in enumerate(es):
            (folder/str(i)).write_bytes(b'data');outputs.append(dict(file=e['file'],output=str(i)))
        (folder/'manifest.json').write_text('{}')
        plan=dict(model_only=False,include_raw=False,entries=es,selected_ids=[e['id'] for e in es],outputs=outputs,
                  song_selection=dict(roles={es[1]['id']:'root',es[2]['id']:'timeline'}))
        self.manager.jobs['aaaaaaaaaaaa']=dict(id='aaaaaaaaaaaa',status='packaging')
        self.manager.package(self.manager.jobs['aaaaaaaaaaaa'],plan,dict(files=[],scenes=[]),dict(clips=[]),dict(files=[],models=[]),dict(files=[]),dict(files=[]))
        with zipfile.ZipFile(self.manager.output/'aaaaaaaaaaaa.zip') as z:
            for name in ('data/110_mellow_camera.json','root-data/110_mellow_01_root.unity3d','timeline/mellow.unity3d'):
                self.assertEqual(b'data',z.read(name))


class AudioPairTests(unittest.TestCase):
    def test_pair_uses_full_path_and_does_not_guess_other_folder(self):
        es=[resource('a/voice.acb'),resource('a/voice.awb'),resource('b/voice.awb')]
        self.assertEqual([es[0],es[1]],with_audio_pairs(es,[es[0]]))

    def test_hash_named_inputs_restore_sidecars_and_decode_tracks_lazily(self):
        import scsp_audio_export as audio
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);es=[resource('bank.acb'),resource('bank.awb')];outs=[]
            for i,e in enumerate(es):
                p=root/(str(i)+'.unity3d');p.write_bytes(bytes([i]))
                outs.append(dict(file=e['file'],output=p.name,sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
            (root/'manifest.json').write_text(json.dumps(dict(entries=es,outputs=outs)))
            decoder=root/'decoder.exe';decoder.touch()
            def run(args,**kwargs):
                source=Path(args[-1]);self.assertIn(source.suffix,('.awb','.acb'))
                self.assertTrue(source.with_suffix('.awb').is_file());self.assertTrue(source.with_suffix('.acb').is_file())
                if '-o' in args:
                    with wave.open(args[args.index('-o')+1],'wb') as w:w.setparams((1,2,8000,0,'NONE',''));w.writeframes(b'\x01\x00'*8)
                    return NS(returncode=0,stdout=b'',stderr=b'')
                return NS(returncode=0,stderr=b'',stdout=json.dumps(dict(streamInfo=dict(total=1,name=source.suffix),sampleRate=8000,channels=1,numberOfSamples=8)).encode())
            with patch.object(audio,'DECODER',decoder),patch.object(audio.subprocess,'run',side_effect=run):
                a=audio.export_audio(root,preview=True)
                self.assertEqual(2,len(a['tracks']));self.assertEqual(1,len(a['files']))
                b=audio.export_audio(root,preview=True,track_numbers=[2])
                self.assertEqual(2,b['files'][0]['track'])
                self.assertEqual(2,len(list((root/'audio').glob('*.wav'))))


class GenericCurveTests(unittest.TestCase):
    def clip(self, path='LipA', kind='Position', value=0.6):
        text='  m_Name: test\n  m_'+kind+'Curves:\n  - curve:\n      m_Curve:\n'
        for t,v in ((0,0),(1,value)):
            text+=f'        time: {t}\n        value: {{x: {v}, y: 0, z: 0}}\n        inSlope: {{x: 0, y: 0, z: 0}}\n        outSlope: {{x: 0, y: 0, z: 0}}\n        weightedMode: 0\n'
        return text+'    path: '+path+'\n  m_FloatCurves: []\n'

    def test_exact_hashed_lip_paths_become_vowels(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'lip.anim'
            path.write_text(self.clip(f'path_0x{path_hash("LipA"):08X}_x'))
            data=lip_data(path,fps=2)
            self.assertEqual(3,len(data['datas']))
            self.assertAlmostEqual(.3,data['datas'][1]['a'])
            self.assertEqual(0,data['datas'][1]['o'])

    def test_unknown_transform_is_not_mislabeled_as_mouth_or_guessed(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'unknown.anim';path.write_text(self.clip('UnknownBone'))
            self.assertIsNone(lip_data(path))
            with self.assertRaisesRegex(ValueError,'不能猜配'):
                generic_input(path,dict(nodes=[dict(name='Actor',parent=-1)]))

    def test_exact_bone_transform_can_be_sampled(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'spine.anim';path.write_text(self.clip('Spine'))
            data=generic_input(path,dict(nodes=[dict(name='Actor',parent=-1),dict(name='Spine',parent=0)]),fps=2)
            self.assertTrue(data['generic']);self.assertEqual(['Spine']*3,data['paths'])
            self.assertAlmostEqual(.3,data['samples'][3])


if __name__=='__main__':unittest.main()
