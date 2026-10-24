import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import scsp_download as d


def entry(name, deps=(), contents=()):
    info = {"name": name, "id": "root/assetbundles/" + name,
            "catalog": "root/assetbundles", "type": "asset", "size": 12,
            "resource_type": 1, "seed": 0, "checksum": 1,
            "label_crc": d.crc64(name.encode()), "contents": list(contents),
            "dependencies": list(deps)}
    info["file"] = d.real_name(info)
    return info


class SelectionTests(unittest.TestCase):
    def test_song_selection_pairs_independent_data_and_excludes_nearby_variants(self):
        expected = ["002_yumeas_01.anim", "002_yumeas_01_root.asset", "002_yumeas_01_exp.json",
                    "002_yumeas_02.anim", "002_yumeas_02_root.asset", "002_yumeas_02_exp.json",
                    "002_yumeas_camera.json", "immygri/yumeas.playable"]
        unrelated = ["002_yumeas_dancelesson_01.anim", "002_yumeas_ucs1_01.anim",
                     "mot_002yumeas_ucs_01_09_01.anim", "002_yumeas.acb", "003_hikari_01.anim"]
        selected, info = d.select_song([entry(n) for n in expected + unrelated], "002_YumeAS")
        self.assertEqual({e["name"] for e in selected}, set(expected))
        self.assertEqual(info["slots"], [1, 2])
        self.assertEqual(info["missing_companions"], [])
        self.assertFalse(info["includes_cutscene_variants"])

    def test_song_slot_limits_fetch_and_records_selection(self):
        names = [f"002_yumeas_{slot:02d}{suffix}" for slot in (1, 2)
                 for suffix in (".anim", "_root.asset", "_exp.json")]
        names += ["002_yumeas_unit.json", "mot_002yumeas_ucs_01_09_01.anim"]
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            index = root / "index.json"
            d.write_json(index, {"schema": 1, "game_version": "test", "resource_version": "test",
                                 "entries": [entry(n) for n in names]})
            with patch.object(d, "get_file", return_value=b"1234UnityFS\0") as get:
                with redirect_stdout(io.StringIO()):
                    result = d.main(["fetch", "--index", str(index), "--song-code", "002_yumeas",
                                     "--slot", "2", "--out", str(root / "out")])
            self.assertEqual(result, 0)
            self.assertEqual({c.args[0]["name"] for c in get.call_args_list},
                             {"002_yumeas_02.anim", "002_yumeas_02_root.asset",
                              "002_yumeas_02_exp.json", "002_yumeas_unit.json"})
            manifest = json.loads((root / "out/manifest.json").read_text())
            self.assertEqual(manifest["song_selection"]["slots"], [2])

    def test_song_missing_companions_stop_fetch_before_network(self):
        entries = [entry("002_yumeas_01.anim")]
        selected, info = d.select_song(entries, "002_yumeas")
        self.assertEqual(len(info["missing_companions"]), 2)
        with self.assertRaises(d.DownloadError):
            d.select_song(entries, "002_yumeas", [9])
        with self.assertRaises(d.DownloadError):
            d.select_song(entries, "../002_yumeas")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            d.write_json(root / "index.json", {"schema": 1, "game_version": "test",
                                               "resource_version": "test", "entries": entries})
            with patch.object(d, "get_file") as get, redirect_stdout(io.StringIO()):
                with self.assertRaises(d.DownloadError):
                    d.main(["fetch", "--index", str(root / "index.json"), "--song-code",
                            "002_yumeas", "--out", str(root / "out")])
                get.assert_not_called()

    def test_exact_selection_transitive_dependency_cycle_excludes_unrelated(self):
        root = entry("hair.prefab", ["mesh.asset"])
        mesh = entry("mesh.asset", ["material.mat"])
        material = entry("material.mat", ["mesh.asset"])
        other = entry("other.prefab")
        entries = [root, mesh, material, other]
        plan, missing = d.resolve_dependencies(entries, d.select(entries, ["hair.prefab"], []))
        self.assertEqual({x["name"] for x in plan}, {"hair.prefab", "mesh.asset", "material.mat"})
        self.assertEqual(missing, [])

    def test_missing_and_ambiguous_names_are_reported(self):
        a = entry("a.asset", ["missing.shader"], ["motion.anim"])
        b = entry("b.asset", contents=["motion.anim"])
        with self.assertRaises(d.DownloadError):
            d.select([a, b], ["motion.anim"], [])
        plan, missing = d.resolve_dependencies([a, b], [a])
        self.assertEqual(len(plan), 1)
        self.assertIn("missing.shader", missing[0])

    def test_fetch_only_requests_selected_bundle_and_dependencies(self):
        a, b, other = entry("a.prefab", ["b.asset"]), entry("b.asset"), entry("unrelated.prefab")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            index = root / "index.json"
            d.write_json(index, {"schema": 1, "game_version": "test", "resource_version": "test",
                                 "entries": [a, b, other]})
            with patch.object(d, "get_file", return_value=b"1234UnityFS\0") as get:
                with redirect_stdout(io.StringIO()):
                    result = d.main(["fetch", "--index", str(index), "--name", "a.prefab",
                                     "--out", str(root / "out")])
            self.assertEqual(result, 0)
            self.assertEqual([c.args[0]["name"] for c in get.call_args_list], ["a.prefab", "b.asset"])
            manifest = json.loads((root / "out/manifest.json").read_text())
            self.assertEqual(len(manifest["outputs"]), 2)

    def test_missing_dependencies_stop_fetch_before_network(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            index = root / "index.json"
            d.write_json(index, {"schema": 1, "game_version": "test", "resource_version": "test",
                                 "entries": [entry("dress.prefab", ["absent.shader"])]})
            with patch.object(d, "get_file") as get, redirect_stdout(io.StringIO()):
                with self.assertRaises(d.DownloadError):
                    d.main(["fetch", "--index", str(index), "--name", "dress.prefab",
                            "--out", str(root / "out")])
                get.assert_not_called()

    def test_protocol_vectors_and_bounds(self):
        self.assertEqual(d.crc64(b"123456789"), 0x6C40DF5F0B497347)
        manifest = d.root_manifest("1.0.4", "10000300@jqWxJ9wcJQVnmMwPYKbgEDA=")
        self.assertEqual(d.real_name(manifest), "W6WP26FAI4S365WCT76BWIZGTM")
        with self.assertRaises(d.DownloadError):
            d.Reader(b"\x80").varuint()
        with self.assertRaises(d.DownloadError):
            d.parse_catalog(b"wrong format")
        with self.assertRaises(d.DownloadError):
            d.safe_output(Path("out"), "../../escape")

    def test_current_snapshot_excludes_changed_or_absent_files_and_reports_gaps(self):
        keep, gone, wrong_size = entry("keep.prefab"), entry("gone.prefab"), entry("changed.prefab")
        named = {"game_version": "older", "resource_version": "older-resource",
                 "entries": [keep, gone, wrong_size]}
        current = {"application": "newer", "resource": "current-resource"}
        files = {keep["file"]: {"size": keep["size"], "sha256": "a" * 64},
                 wrong_size["file"]: {"size": 13, "sha256": "b" * 64},
                 "new-file": {"size": 1, "sha256": "c" * 64}}
        result = d.reconcile_snapshot(named, current, files)
        self.assertEqual([e["name"] for e in result["entries"]], ["keep.prefab"])
        self.assertEqual(result["entries"][0]["sha256"], "a" * 64)
        self.assertEqual(result["unmapped_files"], 2)
        self.assertFalse(result["name_index_complete"])
        self.assertFalse(result["official_live_latest_verified"])

    def test_download_verifies_snapshot_hash(self):
        info = entry("sample.prefab")
        info["sha256"] = "0" * 64
        with tempfile.TemporaryDirectory() as td, patch.object(d.urllib.request, "urlopen") as open_url:
            open_url.return_value.__enter__.return_value.read.return_value = b"1234UnityFS\0"
            with self.assertRaisesRegex(d.DownloadError, "SHA-256"):
                d.get_file(info, Path(td))


if __name__ == "__main__":
    unittest.main()
