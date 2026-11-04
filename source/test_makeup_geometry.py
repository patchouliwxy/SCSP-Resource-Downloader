import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from appearance_resources import attach_makeup_models
from scsp_wardrobe import Wardrobe
import build_wardrobe as builder


class MakeupGeometryTests(unittest.TestCase):
    def fixture(self):
        e=dict(id='prefab',name='m_acce_92592_12nofa_00_12.prefab',type='prefab',size=10)
        r=dict(id=1,group='accessory',kind=3,subtype='makeup',character='12',models=[],
               appearance_prefabs=[dict(id=e['id'],name=e['name'])],textures=[dict(id='png')],asset_kind='texture')
        return e,r

    def test_saved_catalog_regains_prefab_without_losing_textures_or_mutating_input(self):
        e,r=self.fixture();data=dict(records=[r])
        result=attach_makeup_models(data,[e])
        row=result['records'][0]
        self.assertEqual([m['id'] for m in row['models']],['prefab'])
        self.assertEqual(row['textures'],r['textures'])
        self.assertEqual(row['geometry_status'],'checked_at_export')
        self.assertEqual(r['models'],[])
        self.assertEqual(attach_makeup_models(result,[e]),result)

    def test_other_character_and_texture_only_records_do_not_get_false_mesh(self):
        e,r=self.fixture();e['name']='m_acce_92592_12nofa_00_11.prefab'
        self.assertFalse(attach_makeup_models(dict(records=[r]),[e])['records'][0]['models'])
        r['appearance_prefabs']=[]
        result=attach_makeup_models(dict(records=[r]),[e])['records'][0]
        self.assertEqual(result['asset_kind'],'texture')
        self.assertTrue(result['textures'])

    def test_eye_texture_policy_is_preserved(self):
        e,r=self.fixture();r.update(kind=4,subtype='eye_l')
        self.assertFalse(attach_makeup_models(dict(records=[r]),[e])['records'][0]['models'])

    def test_wardrobe_load_migrates_old_index_and_sets(self):
        e,r=self.fixture()
        data=dict(game_version='v',resource_version='r',records=[r],sets=[dict(id=1,character='12',parts=[dict(group='accessory',id=1)])])
        catalog=SimpleNamespace(data=dict(game_version='v',resource_version='r'),entries=[e],character_names={'12':'name'})
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'data.json';p.write_text(json.dumps(data))
            w=Wardrobe(catalog,p)
            self.assertTrue(w.search('12','accessory','makeup')['items'][0]['models'])
            self.assertEqual(w.search('12','set')['items'][0]['missing'],0)

    def test_update_builder_keeps_makeup_prefab(self):
        def entry(name,kind='prefab',deps=()):return dict(id=name,name=name,type=kind,size=1,file=name,dependencies=list(deps))
        rows=[{1:dict(id=1,character=12,kind=1,resource=15)},
              {1:dict(id=1,character=12,kind=1,resource=1)},
              {2:dict(id=2,character=12,category=3,kind=3,resource=9100302)},
              {1:dict(id=1,dress_id=1,hair_id=1,accessory_ids=[2])}]
        entries=[entry('m_dress_0015_12pl01_00.prefab'),entry('m_hair_12_001_00000.prefab'),
                 entry('m_acce_91003_nonedr_make_12.prefab',deps=['12_face_03_make_col.png']),entry('12_face_03_make_col.png','png')]
        texts={'mlCharacterText_Name':{12:'name'},'mlCostumeSet_Name':{1:'set'},'mlCostumeSet_Description':{},'mlCostume_UnlockPremise':{},'mlHairstyle_UnlockPremise':{},'mlAccessory_UnlockPremise':{}}
        with patch.object(builder,'table',side_effect=rows):result=builder.build(dict(game_version='v',resource_version='r',entries=entries),texts,b'')
        makeup=next(r for r in result['records'] if r['id']==2)
        self.assertEqual(makeup['models'][0]['name'],'m_acce_91003_nonedr_make_12.prefab')
        self.assertEqual(makeup['textures'][0]['name'],'12_face_03_make_col.png')
