import tempfile
import time
from pathlib import Path
from unittest.mock import patch
import unittest

import scsp_preview as preview
import scsp_download as core
from test_scsp_web import catalog, resource


class PreviewTests(unittest.TestCase):
    def test_release_deletes_preview_but_keeps_original_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            entry = resource('m_head_14.prefab', ['missing.shader'])
            manager = preview.Previews(catalog([entry]), root / 'previews', root / 'cache')
            manager.cache.mkdir();(manager.cache / 'original').write_bytes(b'keep')
            def build(paths, target):
                target.write_bytes(b'glTF preview fixture')
                return dict(meshes=1, vertices=3, textures=0, bytes=20, warnings=[])
            with patch.object(core, 'get_file', return_value=b'1234UnityFS\0'), patch.object(preview, 'build_glb', side_effect=build):
                job = manager.start(entry['id'])
                manager.pool.shutdown(wait=True)
                result = manager.get(job['key'])
                self.assertEqual(result['status'], 'completed')
                self.assertEqual(len(result['missing']), 1)
                manager.release(job['key'])
                self.assertFalse((manager.root / job['key']).exists())
                self.assertTrue((manager.cache / 'original').exists())
                self.assertNotIn(job['key'], manager.jobs)
                manager.release(job['key'])

    def test_release_during_generation_is_cleaned_when_worker_finishes(self):
        import threading
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp);entry = resource('m_head_14.prefab')
            manager = preview.Previews(catalog([entry]), root / 'previews', root / 'cache')
            started, proceed = threading.Event(), threading.Event()
            def build(paths, target):
                started.set();proceed.wait(3);target.write_bytes(b'glTF')
                return dict(meshes=1, vertices=3, textures=0, bytes=4, warnings=[])
            with patch.object(core, 'get_file', return_value=b'1234UnityFS\0'), patch.object(preview, 'build_glb', side_effect=build):
                job = manager.start(entry['id']);self.assertTrue(started.wait(3))
                manager.release(job['key']);proceed.set();manager.pool.shutdown(wait=True)
                self.assertFalse((manager.root / job['key']).exists())
                self.assertNotIn(job['key'], manager.jobs)

    def test_unsupported_resource_and_oversize_preview_do_not_download(self):
        with tempfile.TemporaryDirectory() as temp:
            small, large = resource('song.acb'), resource('m_head_14.prefab')
            large['size'] = 65 * 1048576
            manager = preview.Previews(catalog([small, large]), Path(temp) / 'previews', Path(temp) / 'cache')
            try:
                with patch.object(core, 'get_file') as fetch:
                    for identity in (small['id'], large['id'], '../../secret'):
                        with self.assertRaises(core.DownloadError):
                            manager.start(identity)
                    fetch.assert_not_called()
            finally:
                manager.pool.shutdown(wait=True)


if __name__ == '__main__':
    unittest.main()
