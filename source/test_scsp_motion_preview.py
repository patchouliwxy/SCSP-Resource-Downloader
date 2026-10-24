import json
from pathlib import Path
import tempfile
import threading
from unittest.mock import patch
import unittest

import scsp_motion_preview as m
from test_scsp_web import catalog,resource


def yaml_clip(keys,weighted=0,kind=95,name='Spine Front-Back',stop=1):
    text='  m_Name: test\n  m_FloatCurves:\n  - serializedVersion: 2\n'
    for t,v,inside,outside in keys:
        text+=f'        time: {t}\n        value: {v}\n        inSlope: {inside}\n        outSlope: {outside}\n        weightedMode: {weighted}\n'
    return text+f'    attribute: {name}\n    classID: {kind}\n  m_PPtrCurves: []\n    m_StartTime: 0\n    m_StopTime: {stop}\n'


class MotionPreviewTests(unittest.TestCase):
    def sample(self,text):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'x.anim';p.write_text(text)
            return m.sample_humanoid(p,{'muscles':['Spine Front-Back']},fps=2)

    def test_hermite_and_step_curves(self):
        result=self.sample(yaml_clip([(0,0,1,1),(1,1,1,1)]))
        self.assertEqual(result['samples'],[0,.5,1])
        step=self.sample(yaml_clip([(0,0,'.inf','.inf'),(1,1,'.inf','.inf')]))
        self.assertEqual(step['samples'],[0,0,1])
        curve=self.sample(yaml_clip([(0,0,0,2),(1,1,0,0)]))
        self.assertAlmostEqual(curve['samples'][1],.75)

    def test_reject_nonhumanoid_weighted_nonfinite_and_long_clips(self):
        texts=[yaml_clip([(0,0,1,1),(1,1,1,1)],kind=4),
               yaml_clip([(0,0,1,1),(1,1,1,1)],weighted=1),
               yaml_clip([(0,'nan',1,1),(1,1,1,1)]),
               yaml_clip([(0,0,1,1),(1,1,1,1)],stop=601)]
        for text in texts:
            with self.subTest(text=text[-80:]),self.assertRaises(ValueError):self.sample(text)

    def test_whitelist_excludes_nonbody_assets(self):
        for name in ('035_chocod_camera.json','035_chocod_root.asset','faceeyecloselcvd.anim','an_lv_005_stage_wingdef.anim','motsd_dance_shorta.anim','s10_30100900_01.playable'):
            self.assertFalse(m.supports_motion(resource(name)))
        for name in ('motion10_wait_a_lp.anim','036_shineg_01_body.asset','s44_01010100_00_0320_01mano.anim'):
            self.assertTrue(m.supports_motion(resource(name)))

    def test_close_while_sampling_cleans_temporary_data_and_keeps_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);entry=resource('motion10_wait_a_lp.anim')
            manager=m.MotionPreviews(catalog([entry]),root/'previews',root/'cache')
            manager.cache.mkdir();(manager.cache/'keep').write_bytes(b'original')
            worker=root/'worker.exe';worker.write_bytes(b'fixture')
            model=root/'model.json';model.write_text('{}')
            started,proceed=threading.Event(),threading.Event()
            def exported(folder,progress):
                target=folder/'animations';target.mkdir();(target/'motion10_wait_a_lp.anim').write_text('fixture')
                return {'clips':[{'file':'animations/motion10_wait_a_lp.anim'}]}
            def retarget(anim,folder):
                started.set();proceed.wait(3);(folder/'motion.bin').write_bytes(b'frames')
                return {'fps':30,'boneCount':54}
            with patch.object(m,'WORKER',worker),patch.object(m,'MODEL',model),patch.object(m.core,'get_file',return_value=b'1234UnityFS\0'),patch.object(m,'export_animations',side_effect=exported),patch.object(m,'retarget',side_effect=retarget):
                job=manager.start(entry['id']);self.assertTrue(started.wait(3));manager.release(job['key']);proceed.set();manager.pool.shutdown()
                self.assertNotIn(job['key'],manager.jobs)
                self.assertFalse((manager.root/job['key']).exists())
                self.assertEqual((manager.cache/'keep').read_bytes(),b'original')

    def test_reject_unknown_and_oversize_before_network(self):
        with tempfile.TemporaryDirectory() as temp:
            large=resource('motion10_wait_a_lp.anim');large['size']=65*1048576
            manager=m.MotionPreviews(catalog([large,resource('song.acb')]),Path(temp)/'previews',Path(temp)/'cache')
            try:
                with patch.object(m.core,'get_file') as fetch:
                    for identity in ('../../secret',manager.catalog.entries[1]['id'],large['id']):
                        with self.assertRaises(m.core.DownloadError):manager.start(identity)
                    fetch.assert_not_called()
            finally:manager.pool.shutdown()


if __name__=='__main__':unittest.main()
