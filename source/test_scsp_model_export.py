import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

import scsp_download as core
import scsp_model_export as exporter


class ModelExportTests(unittest.TestCase):
    def fixture(self, root):
        folder = root / 'bundles';folder.mkdir()
        (folder / 'test.unity3d').write_bytes(b'UnityFS\0test')
        entry = dict(id='root/m_head_14.prefab', name='m_head_14.prefab', type='prefab', file='test')
        core.write_json(root / 'manifest.json', dict(selected_ids=[entry['id']], entries=[entry],
                        outputs=[dict(output='bundles/test.unity3d', file='test', sha256=hashlib.sha256(b'UnityFS\0test').hexdigest())]))

    def test_selected_name_filter_texture_report_and_no_animation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp);self.fixture(root)
            def run(args, **kwargs):
                self.assertIn('(?i)^m_head_14$', args)
                self.assertEqual(args[args.index('--fbx-animation') + 1], 'skip')
                folder = Path(args[args.index('-o') + 1]);folder.mkdir()
                (folder / 'head.fbx').write_bytes(b'Kaydara FBX Binary  \x00\x1a\x00fixture')
                (folder / 'face.png').write_bytes(b'texture')
                return SimpleNamespace(returncode=0)
            with patch.object(exporter.subprocess, 'run', side_effect=run):
                report = exporter.export_models(root)
            self.assertEqual(len(report['files']), 2)
            self.assertEqual(len(report['models']), 1)
            self.assertFalse(report['unity_import_verified'])

    def test_hash_mismatch_and_empty_export_fail(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp);self.fixture(root)
            (root / 'bundles/test.unity3d').write_bytes(b'changed')
            with patch.object(exporter.subprocess, 'run') as run:
                with self.assertRaises(ValueError):
                    exporter.export_models(root)
                run.assert_not_called()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp);self.fixture(root)
            with patch.object(exporter.subprocess, 'run', return_value=SimpleNamespace(returncode=0)):
                with self.assertRaises(RuntimeError):
                    exporter.export_models(root)
