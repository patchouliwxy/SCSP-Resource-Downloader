import unittest
from unittest.mock import patch
import build_wardrobe as builder


class AppearanceTests(unittest.TestCase):
    def test_prefab_dependencies_override_filename_guess_and_share_right_eye(self):
        def entry(name,kind='prefab',deps=()):
            return dict(id=name,name=name,type=kind,size=1,file=name,dependencies=list(deps))
        rows=[{1001:dict(id=1001,character=12,kind=1,resource=15)},
              {1001:dict(id=1001,character=12,kind=1,resource=1)},
              {2001:dict(id=2001,character=12,category=3,kind=5,resource=8101302),2002:dict(id=2002,character=12,category=3,kind=3,resource=9100302)},
              {1001:dict(id=1001,dress_id=1001,hair_id=1001,accessory_ids=[2001,2002])}]
        entries=[entry('m_dress_0015_12pl01_00.prefab'),entry('m_hair_12_001_00000.prefab'),
                 entry('m_acce_81013_nonedr_r1_12.prefab',deps=['12_eye_l_06_col.png']),entry('12_eye_l_06_col.png','png'),
                 entry('m_acce_91003_nonedr_make_12.prefab',deps=['12_face_03_make_col.png']),entry('12_face_03_make_col.png','png')]
        texts={'mlCharacterText_Name':{12:'name'},'mlCostumeSet_Name':{1001:'set'},'mlCostumeSet_Description':{},'mlCostume_UnlockPremise':{},'mlHairstyle_UnlockPremise':{},'mlAccessory_UnlockPremise':{}}
        with patch.object(builder,'table',side_effect=rows):
            result=builder.build(dict(game_version='v',resource_version='r',entries=entries),texts,b'')
        eye=next(r for r in result['records'] if r['id']==2001)
        makeup=next(r for r in result['records'] if r['id']==2002)
        self.assertEqual(eye['textures'][0]['name'],'12_eye_l_06_col.png')
        self.assertEqual(eye['evidence'],'appearance prefab dependency list')
        self.assertEqual(makeup['textures'][0]['name'],'12_face_03_make_col.png')
        self.assertFalse(eye['models'])

    def test_colored_hair_matches_suffix_and_eyes_are_downloadable_textures(self):
        rows={'dress':{1001:dict(id=1001,character=12,kind=1,resource=15)},
              'hair':{1001:dict(id=1001,character=12,kind=3,resource=49001)},
              'accessory':{2001:dict(id=2001,character=12,category=3,kind=4,resource=8100701)},
              'sets':{1001:dict(id=1001,dress_id=1001,hair_id=1001,accessory_ids=[2001])}}
        def entry(name,kind='prefab'):
            return dict(id=name,name=name,type=kind,size=1,file=name)
        index=dict(game_version='v',resource_version='r',entries=[entry('m_dress_0015_12pl01_00.prefab'),entry('m_hair_12_021_49001.prefab'),entry('12_eye_07_col.png','png')])
        texts={'mlCharacterText_Name':{12:'杜野 凛世'},'mlCostumeSet_Name':{1001:'set'},'mlCostumeSet_Description':{},'mlCostume_UnlockPremise':{},'mlHairstyle_UnlockPremise':{},'mlAccessory_UnlockPremise':{}}
        with patch.object(builder,'table',side_effect=[rows['dress'],rows['hair'],rows['accessory'],rows['sets']]):
            result=builder.build(index,texts,b'')
        hair=next(r for r in result['records'] if r['group']=='hair')
        eye=next(r for r in result['records'] if r['group']=='accessory')
        self.assertEqual(hair['models'][0]['name'],'m_hair_12_021_49001.prefab')
        self.assertEqual(eye['subtype'],'eye_l')
        self.assertEqual(eye['asset_kind'],'texture')
        self.assertEqual(eye['textures'][0]['name'],'12_eye_07_col.png')


if __name__=='__main__':unittest.main()
