import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from scsp_scene_export import has_scene, verified_bundles, finalize_project
from test_scsp_web import catalog, resource
import test_scsp_web as fixtures
import scsp_download as core
import scsp_web as web


class SceneExportTests(unittest.TestCase):
    def test_scene_detection_uses_selection_not_dependency(self):
        m={'selected_ids':['clip'], 'entries':[{'id':'clip','type':'anim'},{'id':'stage','type':'unity'}]}
        self.assertFalse(has_scene(m))
        m['selected_ids'].append('stage');self.assertTrue(has_scene(m))

    def test_inputs_verify_hash_and_cannot_escape_task(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();p=root/'a';p.write_bytes(b'UnityFS\0')
            m={'outputs':[{'output':'a','sha256':hashlib.sha256(p.read_bytes()).hexdigest()}]}
            self.assertEqual(verified_bundles(root,m),[p])
            m['outputs'][0]['sha256']='bad'
            with self.assertRaisesRegex(ValueError,'hash mismatch'):verified_bundles(root,m)
            m['outputs'][0]['output']='../outside'
            with self.assertRaisesRegex(ValueError,'escapes'):verified_bundles(root,m)

    def test_complete_scene_keeps_meta_and_script_evidence_outside_assets(self):
        with tempfile.TemporaryDirectory() as temp:
            sample=Path(temp);exported=sample/'export';a=exported/'ExportedProject/Assets';a.mkdir(parents=True)
            for name in ('stage.unity','stage.unity.meta','mesh.asset','mesh.asset.meta','script.cs','script.cs.meta','folder.asmdef','map.png'):
                (a/name).write_text('fixture')
            (sample/'manifest.json').write_text(json.dumps({'dependency_complete':False,'unresolved_dependencies':['missing.shader']}))
            report=finalize_project(sample,exported)
            self.assertEqual(report['scenes'],['scene-project/Assets/stage.unity'])
            self.assertTrue((sample/'scene-project/Assets/mesh.asset.meta').is_file())
            self.assertFalse((sample/'scene-project/Assets/script.cs').exists())
            self.assertTrue((sample/'scene-project/RecoveryEvidence/script.cs.meta').is_file())
            self.assertEqual(report['unresolved_dependencies'],['missing.shader'])
            self.assertFalse(report['game_playback_verified'])
            with self.assertRaises(ValueError):finalize_project(sample,exported)

    def test_no_scene_is_explicit_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(RuntimeError,'.unity'):finalize_project(Path(temp),Path(temp))


class SceneDownloadTests(unittest.TestCase):
    setUp = fixtures.DownloadTests.setUp
    tearDown = fixtures.DownloadTests.tearDown
    wait = fixtures.DownloadTests.wait

    def test_scene_archive_contains_assets_instead_of_anim_only(self):
        stage=resource('stage.unity');self.manager.catalog=catalog([stage])
        def restore(output,progress):
            files=[]
            for relative in ('scene-project/Assets/stage.unity','scene-project/Assets/stage.unity.meta','scene-project/Assets/mesh.asset'):
                path=output/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('fixture');files.append({'file':relative})
            return {'scenes':['scene-project/Assets/stage.unity'],'files':files}
        with patch.object(core,'get_file',return_value=b'1234UnityFS\0'),patch.object(web,'export_scenes',side_effect=restore),patch.object(web,'export_animations') as anim:
            job=self.manager.submit({'ids':[stage['id']]});result=self.wait(job['id'])
            self.assertEqual(result['status'],'completed');self.assertEqual(result['scene_count'],1);anim.assert_not_called()
        with zipfile.ZipFile(self.manager.output/(job['id']+'.zip')) as z:
            self.assertIn('scene-project/Assets/stage.unity',z.namelist());self.assertIn('manifest.json',z.namelist())
            self.assertTrue(any(n.startswith('bundles/') for n in z.namelist()))
        with patch.object(core,'get_file',return_value=b'1234UnityFS\0'),patch.object(web,'export_scenes',side_effect=RuntimeError('scene failed')):
            job=self.manager.submit({'ids':[stage['id']]});self.assertEqual(self.wait(job['id'])['status'],'failed')
