import sys,json,shutil,unittest,tempfile,hashlib
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
from PIL import Image
import scsp_texture_export as tex
class TextureExportTest(unittest.TestCase):
 def run_case(self, groups, expected_error=False):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td); entries=[]; outputs=[]; envs=[]
   for i,objects in enumerate(groups):
    raw=('bundle'+str(i)).encode();(root/str(i)).write_bytes(raw)
    entries.append(dict(id=str(i),file=str(i),type='png',name='chr_test.png'))
    outputs.append(dict(file=str(i),output=str(i),sha256=hashlib.sha256(raw).hexdigest()))
    envs.append(NS(objects=[NS(type=NS(name=k),read=lambda n=n:NS(m_Name=n,image=Image.new('RGBA',(8,9),'red'))) for k,n in objects]))
   (root/'manifest.json').write_text(json.dumps(dict(selected_ids=[e['id'] for e in entries],entries=entries,outputs=outputs)),encoding='utf-8')
   with patch.object(tex.UnityPy,'load',side_effect=envs):
    if expected_error:
     with self.assertRaisesRegex(ValueError,'名称不唯一'):tex.export_textures(root)
    else:
     tex.export_textures(root)
     with Image.open(root/'models/textures/chr_test.png') as im:self.assertEqual(im.size,(8,9))
 def test_sprite_texture_same_name(self):self.run_case([[('Texture2D','chr_test'),('Sprite','chr_test')]])
 def test_sprite_only(self):self.run_case([[('Sprite','chr_test')]])
 def test_two_real_textures_rejected(self):self.run_case([[('Texture2D','chr_test'),('Texture2D','chr_test')]],True)
 def test_names_scoped_to_source_bundle(self):self.run_case([[('Texture2D','chr_test')],[('Texture2D','chr_test')]])
if __name__=='__main__':unittest.main()
