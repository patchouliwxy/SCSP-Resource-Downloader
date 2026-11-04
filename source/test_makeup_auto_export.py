import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import scsp_model_export as exporter
import test_scsp_model_export


class MakeupAutoExportTests(unittest.TestCase):
    def fixture(self,root,carrier=True):
        test_scsp_model_export.ModelExportTests().fixture(root)
        p=root/'manifest.json';m=json.loads(p.read_text())
        if carrier:
            m['entries'][0].update(name='m_acce_91000_test_make_12.prefab',dependencies=['12_face_00_make_col.png'])
            m['entries'].append(dict(id='png',name='12_face_00_make_col.png',type='png',file='test',size=1,dependencies=[]))
        else:m['entries'][0]['dependencies']=[]
        for e in m['entries']:e.setdefault('contents',[]);e.setdefault('size',1);e.setdefault('catalog','root')
        p.write_text(json.dumps(m))

    def response(self,geometry):
        def run(args,**kwargs):
            req=json.loads(Path(args[1]).read_text());folder=Path(req['output']);folder.mkdir()
            (folder/'geometry-report.json').write_text(json.dumps(dict(selection='source_prefab_root',animations=0,meshes=0,**geometry)))
            return SimpleNamespace(returncode=0)
        return run

    def test_verified_meshless_appearance_automatically_exports_png(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.fixture(root)
            with patch.object(exporter.subprocess,'run',side_effect=self.response(dict(geometry_checked=True,source_mesh_renderers=0,unresolved_mesh_references=[]))),patch('scsp_texture_export.export_textures') as tex:
                report=exporter.export_models(root)
            tex.assert_called_once_with(root,['png'])
            self.assertEqual(report['models'][0]['asset_kind'],'texture')
            self.assertEqual(report['models'][0]['fbxs'],[])

    def test_unresolved_mesh_is_not_silently_treated_as_texture(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.fixture(root)
            with patch.object(exporter.subprocess,'run',side_effect=self.response(dict(geometry_checked=True,source_mesh_renderers=1,unresolved_mesh_references=['face']))),patch('scsp_texture_export.export_textures') as tex:
                with self.assertRaises(RuntimeError):exporter.export_models(root)
            tex.assert_not_called()

    def test_ordinary_model_with_no_mesh_still_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.fixture(root,False)
            with patch.object(exporter.subprocess,'run',side_effect=self.response(dict(geometry_checked=True,source_mesh_renderers=0,unresolved_mesh_references=[]))):
                with self.assertRaises(RuntimeError):exporter.export_models(root)
