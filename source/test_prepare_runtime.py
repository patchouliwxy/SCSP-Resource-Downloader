import tempfile
import unittest
import zipfile
from pathlib import Path

from prepare_runtime import METADATA, prepare


class RuntimePreparationTests(unittest.TestCase):
    def files(self):
        return METADATA | {'tools/AssetStudioMod/cli/AssetStudioModCLI_net472_win32_64/AssetStudioModCLI.exe',
                           'tools/AssetRipper/2.0.0/AssetRipper.GUI.Free.exe', 'tools/vgmstream/r2117/vgmstream-cli.exe'}

    def test_directory_copies_runtime_not_downloads(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);release=root/'release';source=root/'source'
            for name in self.files() | {'web-downloads/private.txt','.scsp-cache/private.txt'}:
                path=release/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'test')
            prepare(release,source)
            self.assertTrue(all((source/p).is_file() for p in self.files()))
            self.assertFalse((source/'web-downloads').exists())
            self.assertFalse((source/'.scsp-cache').exists())

    def test_zip_copies_runtime_with_relative_layout(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);archive=root/'release.zip'
            with zipfile.ZipFile(archive,'w') as z:
                for name in self.files() | {'web-downloads/private.txt'}:z.writestr('SCSPDownloader/'+name,b'test')
            prepare(archive,root/'source')
            self.assertTrue(all((root/'source'/p).is_file() for p in self.files()))
            self.assertFalse((root/'source/web-downloads').exists())

    def test_zip_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);archive=root/'bad.zip'
            with zipfile.ZipFile(archive,'w') as z:z.writestr('SCSPDownloader/tools/../../escaped.txt',b'bad')
            with self.assertRaises(ValueError):prepare(archive,root/'source')
            self.assertFalse((root/'escaped.txt').exists())

    def test_incomplete_release_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);release=root/'release';release.mkdir()
            with self.assertRaisesRegex(ValueError,'Incomplete'):prepare(release,root/'source')
