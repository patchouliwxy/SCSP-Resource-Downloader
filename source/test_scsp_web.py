import hashlib
import http.client
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import zipfile

from http.server import ThreadingHTTPServer
import scsp_web as web
import scsp_download as core
from test_scsp_download import entry


def resource(name, deps=(), kind=None):
    result = entry(name, deps)
    result["type"] = kind or name.rsplit(".", 1)[-1]
    result["sha256"] = hashlib.sha256(b"1234UnityFS\0").hexdigest()
    return result


def catalog(entries):
    return web.Catalog({"schema": 1, "game_version": "test", "resource_version": "test", "entries": entries})


class CatalogTests(unittest.TestCase):
    def test_character_names_and_default_lineup_are_version_scoped(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = dict(game_version='test', resource_version='test', characters={'09': '小宮 果穂'},
                formations={'002_yumeas': {'members': [{'position': 1, 'character_id': 9, 'name': '小宮 果穂'}],
                    'source': 'root/raw/002_yumeas_unit.json', 'position_basis': 'unitIdolData array order'}})
            (root / 'character-data.json').write_text(json.dumps(data), encoding='utf-8')
            with patch.object(web, 'ROOT', root):
                c = catalog([resource('m_head_09.prefab'), resource('002_yumeas_01.anim')])
                self.assertEqual(c.search(query='小宮果穂')['total'], 1)
                self.assertEqual(c.songs[0]['default_lineup'][0]['character_id'], 9)
                data['resource_version'] = 'old'
                (root / 'character-data.json').write_text(json.dumps(data), encoding='utf-8')
                c = catalog([resource('m_head_09.prefab')])
                self.assertFalse(c.character_names)

    def test_classification_character_and_search_pagination(self):
        c = catalog([resource(f"m_hair_10_{i:03}_00000.prefab") for i in range(35)] +
                    [resource("m_dress_2196_10ocdl_00.prefab"), resource("mot_002yumeas_ucs_01_09_01.anim"),
                     resource("faceeyecloselcvd.anim")])
        page = c.search(category="hair", character="10", page=2)
        self.assertEqual(page["total"], 35)
        self.assertEqual(len(page["items"]), 5)
        self.assertEqual(c.search(query="2196", character="10")["total"], 1)
        self.assertEqual(web.classify(c.entries[-2]), "performance")
        self.assertEqual(web.classify(c.entries[-1]), "expression")

    def test_song_plan_preserves_missing_and_excludes_cutscenes(self):
        c = catalog([resource("002_yumeas_01.anim", ["missing.shader"]), resource("002_yumeas_01_exp.json"),
                     resource("002_yumeas_02.anim"), resource("mot_002yumeas_ucs_01_09_01.anim")])
        self.assertEqual([(s["code"], s["slots"]) for s in c.songs], [("002_yumeas", [1, 2])])
        plan = c.plan({"song_code": "002_yumeas", "slots": [1]})
        self.assertEqual(len(plan["selected_ids"]), 2)
        self.assertFalse(plan["dependency_complete"])
        self.assertEqual(len(plan["unresolved_dependencies"]), 2)
        self.assertFalse(plan["song_selection"]["includes_cutscene_variants"])

    def test_single_shared_and_custom_body_song_selection(self):
        c = catalog([resource("019_fuysos.anim"), resource("019_fuysos_root.asset"), resource("019_fuysos_exp.json"),
                     resource("001_ambeve.anim"), resource("001_ambeve_01_exp.json"), resource("001_ambeve_02_exp.json"),
                     resource("036_shineg_01_body.asset"), resource("036_shineg_01_root.asset"), resource("036_shineg_01_exp.json"),
                     resource("036_shineg_02_body.asset"), resource("036_shineg_02_root.asset"), resource("036_shineg_02_exp.json"),
                     resource("023_watasi_body.asset"), resource("023_watasi_root.asset"), resource("023_watasi_exp.json"),
                     resource("036_shineg_dancelesson_01.anim"), resource("182_attachbonetarget.anim")])
        single = c.plan({"song_code": "019_fuysos"})
        self.assertTrue(single["dependency_complete"])
        self.assertEqual(single["song_selection"]["body_mode"], "single")
        with self.assertRaises(core.DownloadError):
            c.plan({"song_code": "019_fuysos", "slots": [1]})
        shared = c.plan({"song_code": "001_ambeve", "slots": [2]})
        self.assertEqual({e["name"] for e in shared["entries"]}, {"001_ambeve.anim", "001_ambeve_02_exp.json"})
        self.assertFalse(shared["dependency_complete"])
        custom = c.plan({"song_code": "036_shineg", "slots": [2]})
        self.assertEqual({e["name"] for e in custom["entries"]}, {"036_shineg_02_body.asset", "036_shineg_02_root.asset", "036_shineg_02_exp.json"})
        self.assertEqual(custom["song_selection"]["body_formats"], ["body_asset"])
        self.assertEqual(c.plan({"song_code": "023_watasi"})["song_selection"]["body_mode"], "single")
        self.assertEqual(len(c.songs), 4)

    def test_unmapped_snapshot_metadata_preserved(self):
        c = web.Catalog({"schema": 1, "game_version": "test", "resource_version": "20006100",
                         "source_kind": "public_snapshot", "mapped_files": 1, "snapshot_files": 3,
                         "unmapped_files": 2, "official_live_latest_verified": False,
                         "entries": [resource("m_head_10.prefab")]})
        self.assertEqual(c.metadata()["unmapped_files"], 2)
        self.assertFalse(c.plan({"ids": [c.entries[0]["id"]]})["snapshot_provenance"]["official_live_latest_verified"])

    def test_reject_unknown_ids_bad_slots_and_empty_selection(self):
        c = catalog([resource("x.asset")])
        for body in ({}, {"ids": ["../../secret"]}, {"ids": "x"}, {"slots": [True]}, {"slots": [1]}):
            with self.subTest(body=body), self.assertRaises(core.DownloadError):
                c.plan(body)


class DownloadTests(unittest.TestCase):
    def fixture_finished_job(self, identity='abcdef123456'):
        folder = self.manager.output / identity
        folder.mkdir()
        (folder / 'animation-export-work').mkdir()
        (folder / 'animation-export-work/temporary.anim').write_bytes(b'temp')
        (self.manager.output / (identity + '.zip')).write_bytes(b'zip')
        job = dict(id=identity, status='completed', output_path=str(folder))
        self.manager.jobs[identity] = job
        self.manager.update(job)
        return identity, folder

    def test_remove_files_frees_task_directory_archive_but_keeps_cache(self):
        identity, folder = self.fixture_finished_job()
        self.manager.cache.mkdir()
        cached = self.manager.cache / 'keep'
        cached.write_bytes(b'cached')
        result = self.manager.remove(identity, True)
        self.assertGreaterEqual(result['freed_bytes'], 7)
        self.assertFalse(folder.exists())
        self.assertFalse((self.manager.output / (identity + '.zip')).exists())
        self.assertTrue(cached.exists())
        self.assertNotIn(identity, self.manager.jobs)

    def test_record_only_cleanup_is_persistent_and_keeps_files(self):
        identity, folder = self.fixture_finished_job()
        result = self.manager.remove(identity, False)
        self.assertEqual(result['freed_bytes'], 0)
        self.assertTrue((folder / 'animation-export-work/temporary.anim').exists())
        reopened = web.Downloads(self.manager.catalog, self.manager.output, self.manager.cache)
        try:
            self.assertNotIn(identity, reopened.jobs)
        finally:
            reopened.pool.shutdown(wait=True)

    def test_bulk_clear_skips_active_jobs_and_rejects_escaping_identity(self):
        identity, folder = self.fixture_finished_job()
        busy = '123456abcdef'
        self.manager.jobs[busy] = dict(id=busy, status='exporting')
        report = self.manager.clear([identity, busy, '../cache'], True)
        self.assertEqual([r['id'] for r in report['removed']], [identity])
        self.assertEqual(len(report['errors']), 2)
        self.assertIn(busy, self.manager.jobs)
        with self.assertRaises(core.DownloadError):
            self.manager.task_paths('../cache')
        self.assertFalse(folder.exists())

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.a = resource("a.prefab", ["mesh.asset", "missing.shader"])
        self.b = resource("mesh.asset")
        self.manager = web.Downloads(catalog([self.a, self.b]), self.root / "out", self.root / "cache")
        self.anim_patch = patch.object(web, "export_animations", return_value={"sources": [], "clips": []})
        self.anim_patch.start()

    def tearDown(self):
        self.manager.pool.shutdown(wait=True)
        self.anim_patch.stop()
        self.temp.cleanup()

    def wait(self, identity):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            job = self.manager.jobs[identity]
            if job["status"] in ("completed", "failed", "canceled"):
                return job
            time.sleep(.01)
        self.fail("Task did not finish")

    def test_missing_and_size_block_before_network(self):
        with patch.object(core, "get_file") as get:
            with self.assertRaises(core.DownloadError):
                self.manager.submit({"ids": [self.a["id"]]})
            self.a["size"] = 2 * 1048576
            with self.assertRaises(core.DownloadError):
                self.manager.submit({"ids": [self.a["id"]], "allow_unresolved": True, "max_total_mb": 1})
            get.assert_not_called()

    def test_download_manifest_archive_and_cancel_queued(self):
        with patch.object(core, "get_file", return_value=b"1234UnityFS\0") as get:
            job = self.manager.submit({"ids": [self.a["id"]], "allow_unresolved": True})
            result = self.wait(job["id"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(get.call_count, 2)
        manifest = json.loads((self.root / "out" / job["id"] / "manifest.json").read_text())
        self.assertTrue(manifest["download_complete"])
        self.assertFalse(manifest["dependency_complete"])
        self.assertEqual(manifest["outputs"][0]["sha256"], hashlib.sha256(b"UnityFS\0").hexdigest())
        with zipfile.ZipFile(self.root / "out" / (job["id"] + ".zip")) as archive:
            self.assertIn("manifest.json", archive.namelist())
            self.assertEqual(len(archive.namelist()), 3)
        plan = self.manager.catalog.plan({"ids": [self.a["id"]]})
        queued = dict(id="a"*12, status="canceling")
        self.manager.run(queued, plan)
        self.assertEqual(queued["status"], "canceled")

    def test_independent_anim_is_in_zip_and_export_failure_is_not_complete(self):
        def restore(output, progress):
            folder = output / "animations"
            folder.mkdir()
            (folder / "test.anim").write_text("standalone animation fixture")
            report = {"clips": [{"file": "animations/test.anim"}], "sources": []}
            (folder / "export-report.json").write_text(json.dumps(report))
            return report
        with patch.object(core, "get_file", return_value=b"1234UnityFS\0"), patch.object(web, "export_animations", side_effect=restore):
            job = self.manager.submit({"ids": [self.a["id"]], "allow_unresolved": True})
            self.assertEqual(self.wait(job["id"])["animation_count"], 1)
        with zipfile.ZipFile(self.root / "out" / (job["id"] + ".zip")) as archive:
            self.assertIn("animations/test.anim", archive.namelist())
            self.assertIn("animations/export-report.json", archive.namelist())
        with patch.object(core, "get_file", return_value=b"1234UnityFS\0"), patch.object(web, "export_animations", side_effect=ValueError("Animation export failed")):
            job = self.manager.submit({"ids": [self.a["id"]], "allow_unresolved": True})
            self.assertEqual(self.wait(job["id"])["status"], "failed")
        manifest = json.loads((self.root / "out" / job["id"] / "manifest.json").read_text())
        self.assertFalse(manifest["download_complete"])
        self.assertEqual(len(manifest["outputs"]), 2)

    def test_failed_download_retains_partial_manifest(self):
        with patch.object(core, "get_file", side_effect=[b"1234UnityFS\0", core.DownloadError("SHA-256 mismatch")]):
            job = self.manager.submit({"ids": [self.a["id"]], "allow_unresolved": True})
            result = self.wait(job["id"])
        self.assertEqual(result["status"], "failed")
        manifest = json.loads((self.root / "out" / job["id"] / "manifest.json").read_text())
        self.assertFalse(manifest["download_complete"])
        self.assertEqual(len(manifest["outputs"]), 1)
        self.assertIn("SHA-256", manifest["download_error"])

    def test_model_fbx_and_textures_packaged_and_failure_retains_original(self):
        def restore(output, progress):
            folder = output / 'models';folder.mkdir()
            files = ['models/head.fbx', 'models/face.png']
            for relative in files:
                (output / relative).write_bytes(b'model fixture')
            report = dict(models=[dict(fbxs=[files[0]])], files=[dict(file=f) for f in files])
            (folder / 'export-report.json').write_text(json.dumps(report))
            return report
        with patch.object(core, 'get_file', return_value=b'1234UnityFS\0'), patch.object(web, 'export_models', side_effect=restore):
            job = self.manager.submit({'ids': [self.a['id']], 'allow_unresolved': True})
            result = self.wait(job['id'])
            self.assertEqual(result['status'], 'completed')
            self.assertEqual(result['model_count'], 1)
            self.assertEqual(result['model_files'], ['models/head.fbx'])
        with zipfile.ZipFile(self.root / 'out' / (job['id'] + '.zip')) as archive:
            for name in ('models/head.fbx', 'models/face.png', 'models/export-report.json'):
                self.assertIn(name, archive.namelist())
        with patch.object(core, 'get_file', return_value=b'1234UnityFS\0'), patch.object(web, 'export_models', side_effect=RuntimeError('FBX export failed')):
            job = self.manager.submit({'ids': [self.a['id']], 'allow_unresolved': True})
            self.assertEqual(self.wait(job['id'])['status'], 'failed')
        manifest = json.loads((self.root / 'out' / job['id'] / 'manifest.json').read_text())
        self.assertFalse(manifest['download_complete'])
        self.assertEqual(len(manifest['outputs']), 2)

    def test_model_only_delivery_skips_animation_and_removes_inputs(self):
        model = resource('m_dress_0015_12pl01_00.prefab')
        manager = web.Downloads(catalog([model]), self.root / 'models-out', self.root / 'cache')
        def restore(output, progress):
            folder = output / 'models/0015_12pl01_00';folder.mkdir(parents=True)
            files = ['models/0015_12pl01_00/dress.fbx', 'models/0015_12pl01_00/face.png']
            for name in files:
                (output / name).write_bytes(b'fixture')
            work = output / 'model-export-work';work.mkdir()
            (work / 'temporary').write_bytes(b'fixture')
            report = dict(models=[dict(fbxs=[files[0]])], files=[dict(file=f) for f in files])
            (output / 'models/export-report.json').write_text(json.dumps(report))
            return report
        try:
            with patch.object(core, 'get_file', return_value=b'1234UnityFS\0'), patch.object(web, 'export_models', side_effect=restore), patch.object(web, 'export_animations') as anim:
                job = manager.submit({'ids': [model['id']]})
                deadline = time.monotonic() + 5
                while manager.jobs[job['id']]['status'] not in ('completed', 'failed') and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertEqual(manager.jobs[job['id']]['status'], 'completed')
                anim.assert_not_called()
            folder = manager.output / job['id']
            self.assertFalse((folder / 'bundles').exists())
            self.assertFalse((folder / 'model-export-work').exists())
            self.assertTrue((folder / 'manifest.json').exists())
            with zipfile.ZipFile(manager.output / (job['id'] + '.zip')) as archive:
                self.assertEqual(set(archive.namelist()), {'0015_12pl01_00/dress.fbx', '0015_12pl01_00/face.png'})
        finally:
            manager.pool.shutdown(wait=True)


class HTTPTests(unittest.TestCase):
    def test_audio_audition_supports_byte_ranges(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp);key = 'a' * 24
            folder = root / key / 'audio';folder.mkdir(parents=True)
            (folder / 'track.wav').write_bytes(bytes(range(100)))
            fake = SimpleNamespace(root=root, get=lambda k: dict(status='completed', tracks=[dict(track=1, file='audio/track.wav')]))
            manager = web.Downloads(catalog([]), root / 'out', root / 'cache')
            server = ThreadingHTTPServer(('127.0.0.1', 0), web.make_handler(manager.catalog, manager, listens=fake))
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                conn = http.client.HTTPConnection('127.0.0.1', server.server_port)
                conn.request('GET', '/api/listens/' + key + '/track/1', headers={'Range': 'bytes=10-19'})
                response = conn.getresponse()
                self.assertEqual(response.status, 206)
                self.assertEqual(response.getheader('Content-Range'), 'bytes 10-19/100')
                self.assertEqual(response.read(), bytes(range(10, 20)))
                conn.request('GET', '/api/listens/' + key + '/track/1', headers={'Range': 'bytes=999-'})
                response = conn.getresponse();response.read()
                self.assertEqual(response.status, 416)
                conn.close()
            finally:
                server.shutdown();server.server_close();manager.pool.shutdown(wait=True)

    def test_reload_refuses_active_jobs_then_updates_catalog(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            index = root / 'index.json'
            index.write_text(json.dumps(dict(schema=1, game_version='test', resource_version='test',
                entries=[resource('m_head_09.prefab')])), encoding='utf-8')
            c = catalog([resource('m_head_10.prefab')])
            manager = web.Downloads(c, root / 'out', root / 'cache')
            server = ThreadingHTTPServer(('127.0.0.1', 0), web.make_handler(c, manager, index))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                conn = http.client.HTTPConnection('127.0.0.1', server.server_port)
                headers = {'Content-Type': 'application/json', 'X-SCSP-Client': '1'}
                manager.jobs['busy'] = {'status': 'exporting'}
                conn.request('POST', '/api/reload', '{}', headers)
                response = conn.getresponse(); response.read()
                self.assertEqual(response.status, 409)
                self.assertIs(manager.catalog, c)
                manager.jobs.clear()
                conn.request('POST', '/api/reload', '{}', headers)
                response = conn.getresponse()
                self.assertTrue(json.loads(response.read())['reloaded'])
                conn.request('GET', '/api/resources?q=m_head_09')
                response = conn.getresponse()
                self.assertEqual(json.loads(response.read())['total'], 1)
                self.assertEqual(manager.catalog.entries[0]['name'], 'm_head_09.prefab')
                conn.close()
            finally:
                server.shutdown(); server.server_close(); manager.pool.shutdown(wait=True)

    def test_local_api_post_guard_unknown_resource_and_path(self):
        with tempfile.TemporaryDirectory() as temp:
            c = catalog([resource("m_head_10.prefab")])
            manager = web.Downloads(c, Path(temp) / "out", Path(temp) / "cache")
            server = ThreadingHTTPServer(("127.0.0.1", 0), web.make_handler(c, manager))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                conn = http.client.HTTPConnection("127.0.0.1", server.server_port)
                conn.request("GET", "/api/resources?q=m_head")
                response = conn.getresponse()
                self.assertEqual(json.loads(response.read())["total"], 1)
                conn.request("POST", "/api/plan", json.dumps({"ids": [c.entries[0]["id"]]}), {"Content-Type": "application/json"})
                response = conn.getresponse();response.read()
                self.assertEqual(response.status, 403)
                headers = {"Content-Type": "application/json", "X-SCSP-Client": "1"}
                conn.request("POST", "/api/plan", json.dumps({"ids": [c.entries[0]["id"]]}), headers)
                response = conn.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(json.loads(response.read())["unique_files"], 1)
                conn.request("POST", "/api/download", "{}", {**headers, "Origin": "https://example.com"})
                response = conn.getresponse();response.read()
                self.assertEqual(response.status, 403)
                conn.request("GET", "/../latest-index.json")
                response = conn.getresponse();response.read()
                self.assertEqual(response.status, 404)
                conn.close()
            finally:
                server.shutdown();server.server_close();manager.pool.shutdown(wait=True)


if __name__ == "__main__":
    unittest.main()
