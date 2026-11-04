from copy import deepcopy
import unittest
from appearance_resources import attach_makeup_models


class MakeupCorrectionTests(unittest.TestCase):
    def fixture(self):
        entries=[];records=[];sets=[]
        for owner,number,other in [(1,11,22),(2,22,11)]:
            prefab=f'm_acce_{90000+number}_test_00_{owner:02d}.prefab'
            tex=f'{owner:02d}_face_{number}_col.png';mat=f'm_face_{number}_{owner:02d}.mat'
            entries.extend([dict(id=prefab,name=prefab,type='prefab',size=1,dependencies=[tex,mat]),
                            dict(id=tex,name=tex,type='png',size=1),dict(id=mat,name=mat,type='mat',size=1)])
            records.extend([dict(group='dress',id=owner,character=str(owner),resource=number,
                                 models=[dict(name=f'm_dress_{number}_test_00.prefab')]),
                            dict(group='accessory',id=200+owner,character=str(owner),kind=1,resource=(20000+number)*100,
                                 models=[dict(id=f'support{owner}')]),
                            dict(group='accessory',id=100+owner,character=str(owner),kind=3,resource=(90000+other)*100,
                                 models=[],textures=[dict(id='old')],materials=[],binding_warning='cross',
                                 appearance_prefabs=[dict(id=f'm_acce_{90000+other}_test_00_{3-owner:02d}.prefab')])])
            sets.append(dict(id=owner,character=str(owner),parts=[dict(group='dress',id=owner),dict(group='accessory',id=200+owner),dict(group='accessory',id=100+owner)]))
        return dict(records=records,sets=sets,resource_version='test'),entries

    def test_reciprocal_swap_uses_sets_updates_mesh_texture_material_and_preserves_source(self):
        data,entries=self.fixture();before=deepcopy(data)
        fixed=attach_makeup_models(data,entries)
        for row in [r for r in fixed['records'] if r.get('kind')==3]:
            owner=int(row['character']);number=11*owner
            self.assertEqual(row['resource'],(90000+11*(3-owner))*100)
            self.assertEqual(row['resolved_resource'],(90000+number)*100)
            self.assertTrue(row['models'][0]['name'].endswith(f'_{owner:02d}.prefab'))
            self.assertEqual(row['textures'][0]['id'],f'{owner:02d}_face_{number}_col.png')
            self.assertEqual(row['materials'][0]['id'],f'm_face_{number}_{owner:02d}.mat')
            self.assertFalse(row['binding_warning'])
            self.assertEqual(row['appearance_correction']['original_textures'],[dict(id='old')])
        self.assertEqual(data,before)
        self.assertEqual(attach_makeup_models(fixed,entries),fixed)

    def test_ambiguous_prefab_candidates_are_not_guessed(self):
        data,entries=self.fixture()
        entries.append(dict(id='ambiguous',name='m_acce_90011_alt_00_01.prefab',size=1,type='prefab',dependencies=[]))
        self.assertFalse(any('appearance_correction' in r for r in attach_makeup_models(data,entries)['records']))

    def test_missing_reciprocal_record_or_support_is_not_guessed(self):
        for mode in ['reciprocal','support']:
            data,entries=self.fixture()
            if mode=='reciprocal':data['records']=[r for r in data['records'] if r['id']!=102]
            else:data['sets'][0]['parts']=[p for p in data['sets'][0]['parts'] if p['id']!=201]
            self.assertFalse(any('appearance_correction' in r for r in attach_makeup_models(data,entries)['records']))

    def test_future_official_fix_is_used_without_override(self):
        data,entries=self.fixture()
        for r in data['records']:
            if r.get('kind')==3:
                owner=int(r['character']);r['resource']=(90000+11*owner)*100
                r['appearance_prefabs']=[dict(id=f'm_acce_{90000+11*owner}_test_00_{owner:02d}.prefab')]
        rows=attach_makeup_models(data,entries)['records']
        self.assertFalse(any('appearance_correction' in r for r in rows))
        self.assertTrue(all(r['models'] for r in rows if r.get('kind')==3))

    def test_conflicting_sets_do_not_override(self):
        data,entries=self.fixture();outfit=deepcopy(data['sets'][1]);outfit['parts'].append(dict(group='accessory',id=101));data['sets'].append(outfit)
        self.assertFalse(any('appearance_correction' in r for r in attach_makeup_models(data,entries)['records']))
