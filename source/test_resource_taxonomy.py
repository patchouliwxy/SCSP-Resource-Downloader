import json
import tempfile
from pathlib import Path
import http.client
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch

import scsp_web as web
from resource_taxonomy import classify_resource, character_hint
from test_scsp_web import resource, catalog


class TaxonomyTests(unittest.TestCase):
    def test_audio_families_and_type_guards(self):
        examples = {
            '001_ambeve.acb':'audio_song', '240_brev2d.acb':'audio_song',
            '001_ambeve_10chiyoko.acb':'audio_character',
            '178_border_83iori.acb':'audio_character',
            '178_border_bgm.acb':'audio_instrumental', '001_ambeve_inst.acb':'audio_instrumental',
            '180_karmad_runway.acb':'audio_runway', '900_dresso.acb':'audio_runway',
            'mv_002_yumeas.acb':'audio_mv', 's03_0101xxxx.acb':'audio_story',
            's01_01010000_99.acb':'audio_story', 'cs_s01_01010000.acb':'audio_cutscene',
            'cs_011wcango_ucs_00.acb':'audio_cutscene', '182_superd_addcs.acb':'audio_cutscene',
            'bgm_home.acb':'audio_bgm', 'bgm_home.awb':'audio_bgm',
            'ambi.acb':'audio_ambience', 'amb_s43_03010000.acb':'audio_ambience',
            'se_adv.acb':'audio_sfx_story', 'adv_foot2.acb':'audio_sfx_story',
            'se_pgasha_card_301002.acb':'audio_sfx_gasha', 'se_gasha2.acb':'audio_sfx_gasha',
            'se_home.acb':'audio_sfx', 'inst_event_10002.acb':'audio_event',
            'future_unknown.acb':'audio',
        }
        for name, category in examples.items():
            with self.subTest(name=name):
                row=classify_resource(resource(name))
                self.assertEqual(row['category'],category);self.assertEqual(row['scope'],'audio')
                self.assertTrue(row['category_basis'])
        self.assertEqual(classify_resource(resource('se_home.png'))['category'],'texture')
        self.assertEqual(classify_resource(resource('001_ambeve_10chiyoko.anim'))['scope'],'motion')

    def test_audio_character_suffix_is_not_song_scene_or_story_number(self):
        for name, expected in [('001_ambeve_10chiyoko.acb','10'),('178_border_83iori.acb','83'),
            ('s10_30100900_01.acb',''),('cs_s10_30100900.acb',''),
            ('001_ambeve.acb',''),('inst_event_10.acb',''),('se_pgasha_card_301002.acb','')]:
            self.assertEqual(character_hint(resource(name)),expected)

    def test_audio_scope_category_search_pagination_and_plan_preserve_inputs(self):
        items=[resource(f's01_01010000_{i:02}.acb') for i in range(35)]
        singer=resource('001_ambeve_10chiyoko.acb',['missing.awb'])
        c=catalog(items+[singer,resource('se_home.acb'),resource('bgm_home.awb'),resource('eye.png')])
        self.assertEqual(c.search(scope='audio')['total'],38)
        self.assertEqual(len(c.search(scope='audio',category='audio_story',page=2)['items']),5)
        self.assertEqual(c.search(scope='audio',character='10')['total'],1)
        self.assertEqual(c.search(scope='audio',query='背景音乐')['total'],1)
        self.assertEqual(c.metadata()['scope_counts']['audio'],38)
        plan=c.plan({'ids':[singer['id']]})
        self.assertFalse(plan['dependency_complete']);self.assertIn('missing.awb',plan['unresolved_dependencies'][0])
        self.assertEqual(plan['selected_ids'],[singer['id']]);self.assertFalse(plan['model_only'])

    def test_audio_reload_fallback_and_acb_awb_same_family(self):
        c=catalog([resource('future_unknown.acb'),resource('bgm_adv.awb')])
        self.assertEqual(c.search(category='audio')['total'],1)
        after=catalog([resource('future_unknown.acb'),resource('bgm_adv.awb'),resource('bgm_adv.acb')])
        self.assertEqual(after.search(scope='audio',category='audio_bgm')['total'],2)

    def test_motion_purposes_and_typed_negative_controls(self):
        examples = {
            'mot_002yumeas_ucs_01_09_01.anim': 'performance',
            'mota_007_itubok_01.anim': 'performance',
            'folder/s44_01010100_00_0320_01mano.anim': 'story_motion',
            'motion10_angry_loop.anim': 'character_motion',
            'chara_initial_01_wait01_lp.anim': 'character_motion',
            '000_speciallesson_05_01.anim': 'lesson_motion',
            'motsd_dance_shorta.anim': 'sd_motion',
            'admot_dress_sitwait01_0707_90pl01.anim': 'outfit_motion',
            '900_dresso_01_cool_00_walk_exp.anim': 'expression',
            '14_amana_facial_eye_default.anim': 'expression',
            'faceeyecloselcvd.anim': 'expression',
            '035_chocod_root.asset': 'root_motion',
            '035_chocod_camera.json': 'camera_motion',
            's43_02030000_08_cut_01_camera_01.anim': 'camera_motion',
            'an_lv_062_petal_camera_follow_off.anim': 'stage_animation',
            'an_gashaeffect_scene1_d_tapeffect_white.anim': 'ui_animation',
            'opaque_motion.anim': 'animation',
            'motr_live01a_in.anim': 'animation',
            'immygri/cut_002yumeas_ucs_00.playable': 'timeline',
            'm_head_10.prefab': 'head',
            'eye_close.png': 'texture',
            '14_amana_facial_eye_default.mat': 'other',
        }
        for name, expected in examples.items():
            with self.subTest(name=name):
                self.assertEqual(classify_resource(resource(name))['category'], expected)

    def test_scenes_require_same_index_song_evidence(self):
        examples = {
            '035_chocod.unity': 'scene_mv',
            '002_yumeas_dancelesson.unity': 'scene_lesson',
            's10_30100900_01.unity': 'scene_story',
            'dioramabackground_0001_0101.unity': 'scene_diorama',
            '900_dresso.unity': 'scene_outfit',
            'costumechange.unity': 'scene_outfit',
            'fittingroom.unity': 'scene_outfit',
            'gashaeffect.unity': 'scene_system',
            '000_lightweight.unity': 'scene_other',
            '106_hnouyn.unity': 'scene_other',
            '900_unknown.unity': 'scene_other',
            'folder/stage_000500.fbx': 'stage_model',
            'bgmodel_0010.prefab': 'background_model',
        }
        for name, expected in examples.items():
            with self.subTest(name=name):
                result=classify_resource(resource(name), {'035_chocod'})
                self.assertEqual(result['category'], expected)
                self.assertEqual(result['scope'], 'scene')
        self.assertEqual(classify_resource(resource('035_chocod.unity'),set())['category'],'scene_other')

    def test_auxiliary_clip_is_not_a_main_dance(self):
        c=catalog([resource('182_attachbonetarget.anim'), resource('019_fuysos.anim'),
                   resource('019_fuysos_root.asset'), resource('019_fuysos.unity')])
        self.assertEqual(c.search(category='dance')['total'],1)
        self.assertEqual(c.search(category='scene_mv')['total'],1)
        self.assertEqual(c.search(query='用途未确认')['total'],1)

    def test_motion_character_is_not_a_slot_or_scene_number(self):
        for name, expected in [('motion10_angry_loop.anim','10'),
            ('s44_01010100_00_0320_01mano.anim','01'),
            ('mot_002yumeas_ucs_01_09_01.anim','09'),
            ('mota_007_itubok_01.anim',''),('035_chocod_02.anim',''),
            ('stage_000500.fbx',''),('00_common_facial_base_000.anim','00')]:
            self.assertEqual(character_hint(resource(name)),expected)

    def test_scope_filters_counts_pagination_and_missing_plan_are_preserved(self):
        c=catalog([resource(f'motion10_wait_{i}.anim') for i in range(35)]+
                  [resource('s44_01010100_00.unity',['missing.shader']),resource('bgmodel_0010.prefab'),
                   resource('eye_close.png')])
        self.assertEqual(c.search(scope='motion',page=2)['total'],35)
        self.assertEqual(len(c.search(scope='motion',page=2)['items']),5)
        self.assertEqual(c.search(scope='scene')['total'],2)
        self.assertEqual(c.search(scope='scene',category='character_motion')['total'],0)
        self.assertEqual(c.metadata()['scope_counts']['motion'],35)
        scene=c.search(scope='scene',kind='unity')['items'][0]
        plan=c.plan({'ids':[scene['id']]})
        self.assertFalse(plan['model_only'])
        self.assertFalse(plan['dependency_complete'])
        self.assertEqual(len(plan['unresolved_dependencies']),1)
        self.assertIn('missing.shader',plan['unresolved_dependencies'][0])
        self.assertTrue(scene['category_basis'])
        with self.assertRaises(web.core.DownloadError):c.search(scope='typo')

    def test_reload_recomputes_rules_for_a_new_index(self):
        before=catalog([resource('035_chocod.unity')])
        after=catalog([resource('035_chocod.unity'),resource('035_chocod.anim'),resource('035_chocod_exp.json')])
        self.assertEqual(before.search(scope='scene')['items'][0]['category'],'scene_other')
        self.assertEqual(after.search(scope='scene')['items'][0]['category'],'scene_mv')

    def test_http_scopes_and_detail_basis(self):
        with tempfile.TemporaryDirectory() as temp:
            c=catalog([resource('motion10_angry_loop.anim'),resource('fittingroom.unity')])
            manager=web.Downloads(c,Path(temp)/'out',Path(temp)/'cache')
            server=ThreadingHTTPServer(('127.0.0.1',0),web.make_handler(c,manager))
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            conn=http.client.HTTPConnection('127.0.0.1',server.server_port)
            try:
                conn.request('GET','/api/resources?scope=scene')
                response=conn.getresponse();self.assertEqual(response.status,200)
                payload=json.loads(response.read());self.assertEqual(payload['total'],1)
                from urllib.parse import quote
                conn.request('GET','/api/resource?id='+quote(payload['items'][0]['id']))
                response=conn.getresponse();detail=json.loads(response.read())
                self.assertEqual(detail['category'],'scene_outfit');self.assertTrue(detail['category_basis'])
                conn.request('GET','/api/resources?scope=typo')
                response=conn.getresponse();response.read();self.assertEqual(response.status,400)
            finally:
                conn.close();server.shutdown();server.server_close();thread.join();manager.pool.shutdown()


if __name__=='__main__': unittest.main()
