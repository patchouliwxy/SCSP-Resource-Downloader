import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import scsp_web as web
import scsp_download as core
from scsp_scene_names import scene_names
from scsp_scene_fbx import export_scene_fbx
from test_scsp_web import catalog, resource
import test_scsp_web as fixtures


class SceneFormatTests(unittest.TestCase):
    def test_format_default_and_validation(self):
        stage=resource('001_test.unity')
        c=catalog([stage])
        self.assertEqual('unity',c.plan({'ids':[stage['id']]})['scene_export_format'])
        self.assertTrue(c.plan({'ids':[stage['id']],'scene_export_format':'fbx'})['scene_fbx_only'])
        for bad in ('obj',None,1,[]):
            with self.assertRaises(core.DownloadError):
                c.plan({'ids':[stage['id']],'scene_export_format':bad})

    def test_dependency_scene_does_not_trigger_fbx(self):
        stage=resource('001_test.unity');clip=resource('clip.anim',[stage['name']])
        c=catalog([stage,clip]);p=c.plan({'ids':[clip['id']],'scene_export_format':'fbx'})
        self.assertFalse(p['scene_fbx_only']);self.assertFalse(p['scene_export_requested'])

    def test_official_names_and_version_guard(self):
        stage=resource('001_test.unity')
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);data=dict(game_version='test',resource_version='test',songs={'001_test':{'title':'公式曲名'}})
            (root/'song-names.json').write_text(json.dumps(data),encoding='utf-8')
            with patch.object(web,'ROOT',root):
                c=catalog([stage]);self.assertEqual('公式曲名',c.search(query='公式曲名',scope='scene')['items'][0]['display_name'])
                self.assertEqual('001_test.unity',c.search(scope='scene')['items'][0]['name'])
                data['resource_version']='old';(root/'song-names.json').write_text(json.dumps(data),encoding='utf-8')
                self.assertEqual(0,catalog([stage]).search(query='公式曲名')['total'])

    def test_no_title_guessed_from_number(self):
        stage=resource('s10_30100900_01.unity');c=catalog([stage])
        self.assertNotIn('display_name',c.search()['items'][0])

    def test_unsupported_scene_fails_instead_of_partial_success(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);b=p/'scene';b.write_bytes(b'UnityFS\0')
            import hashlib
            entry=resource('001_test.unity')
            m=dict(selected_ids=[entry['id']],entries=[entry],dependency_complete=False,
                   unresolved_dependencies=['missing.shader'],outputs=[dict(file=entry['file'],output='scene',sha256=hashlib.sha256(b.read_bytes()).hexdigest())])
            (p/'manifest.json').write_text(json.dumps(m))
            with patch('scsp_scene_fbx.STUDIO',p/'missing.exe'):
                with self.assertRaisesRegex(RuntimeError,'内置场景'):
                    export_scene_fbx(p)


class SceneFbxJobTests(unittest.TestCase):
    setUp=fixtures.DownloadTests.setUp
    tearDown=fixtures.DownloadTests.tearDown
    wait=fixtures.DownloadTests.wait

    def test_fbx_dispatch_archive_and_original_inputs_kept(self):
        stage=resource('stage.unity');self.manager.catalog=catalog([stage])
        def restore(output,progress):
            f=output/'scene-fbx/stage/stage.fbx';f.parent.mkdir(parents=True);f.write_bytes(b'fbx fixture')
            return dict(scenes=['scene-fbx/stage/stage.fbx'],files=[dict(file='scene-fbx/stage/stage.fbx')])
        with patch.object(core,'get_file',return_value=b'1234UnityFS\0'),patch.object(web,'export_scene_fbx',side_effect=restore),patch.object(web,'export_scenes') as unity,patch.object(web,'export_animations') as anim:
            job=self.manager.submit(dict(ids=[stage['id']],scene_export_format='fbx'));done=self.wait(job['id'])
            self.assertEqual('completed',done['status']);self.assertEqual('fbx',done['scene_export_format'])
            self.assertIn('scene-fbx/stage/stage.fbx',done['model_files']);unity.assert_not_called();anim.assert_not_called()
        with zipfile.ZipFile(self.manager.output/(job['id']+'.zip')) as z:
            self.assertIn('scene-fbx/stage/stage.fbx',z.namelist())
            self.assertFalse(any(n.startswith('bundles/') or n.endswith('.anim') for n in z.namelist()))
        self.assertTrue(any((self.manager.output/job['id']/'bundles').iterdir()))
