import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from wardrobe_headwear import attach_headwear
from scsp_wardrobe import Wardrobe


def fixture():
    data=dict(game_version='v',resource_version='r',counts={},records=[
        dict(id=10001,group='hair',character='10',models=[{'name':'hair'}],linked_resources=[13700,25900,13700],icon='hair-icon'),
        dict(id=10002,group='hair',character='10',models=[],linked_resources=[13700],icon='other-icon'),
        dict(id=12001,group='hair',character='12',models=[],linked_resources=[13700],icon='')],
        sets=[dict(id=1,character='10',parts=[dict(group='hair',id=10001)])])
    entries=[dict(id=str(i),name=n,size=1,type='prefab') for i,n in enumerate([
        'm_acce_00137_10clct_00_10.prefab','m_acce_00259_00bowg_00_10.prefab',
        'm_acce_00137_10clct_00_12.prefab'])]
    return data,entries


class HeadwearTests(unittest.TestCase):
    def test_multiple_attachments_are_separate_from_hair_variants(self):
        data,entries=fixture();result=attach_headwear(data,entries)
        hair=result['records'][0]
        self.assertEqual(len(hair['models']),1)
        self.assertEqual([a['resource'] for a in hair['attachments']],[13700,25900])
        self.assertEqual([a['models'][0]['id'] for a in hair['attachments']],['0','1'])
        self.assertEqual(len(result['sets'][0]['parts']),3)
        self.assertNotIn('attachments',data['records'][0])

    def test_character_isolation_and_shared_headwear_dedup(self):
        data,entries=fixture();result=attach_headwear(data,entries)
        heads=[r for r in result['records'] if r.get('subtype')=='headwear']
        self.assertEqual(len(heads),3)
        self.assertEqual(heads[0]['source_hair_ids'],[10001,10002])
        self.assertEqual(heads[2]['models'][0]['id'],'2')

    def test_missing_model_preserves_declared_attachment(self):
        data,entries=fixture();result=attach_headwear(data,entries[:1])
        head=result['records'][0]['attachments'][1]
        self.assertEqual(head['models'],[])
        self.assertEqual(head['asset_kind'],'unresolved')
        self.assertTrue(head['binding_warning'])
        self.assertEqual(len(result['sets'][0]['parts']),3)

    def test_idempotent_and_new_index_drops_old_links(self):
        data,entries=fixture();result=attach_headwear(data,entries)
        self.assertEqual(attach_headwear(result,entries),result)
        result['records'][0]['linked_resources']=[]
        updated=attach_headwear(result,entries)
        self.assertEqual(updated['records'][0]['attachments'],[])
        self.assertEqual(len(updated['sets'][0]['parts']),1)

    def test_old_metadata_gets_headwear_filter_and_set_components(self):
        data,entries=fixture()
        with TemporaryDirectory() as temp:
            path=Path(temp)/'data.json';path.write_text(json.dumps(data))
            catalog=SimpleNamespace(data=dict(game_version='v',resource_version='r'),entries=entries,character_names={'10':'園田 智代子'})
            wardrobe=Wardrobe(catalog,path)
            self.assertEqual(wardrobe.search('10','accessory','headwear')['total'],2)
            self.assertIn('headwear',[r['id'] for r in wardrobe.metadata()['accessory_categories']])
            self.assertEqual(len(wardrobe.search('10','set')['items'][0]['components']),3)
