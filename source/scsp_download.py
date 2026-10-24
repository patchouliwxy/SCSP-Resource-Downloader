#!/usr/bin/env python3
"""SCSP catalog-only indexing and selected CDN bundle downloads.

Protocol reference: LukeFZ/PrismCatalogDownloader (2023-12-12).
This implementation retains content addresses and dependency names.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import base64
from collections import defaultdict, deque
import gzip
import hashlib
import http.client
import io
import json
from pathlib import Path, PurePosixPath
import re
import struct
import sys
import time
import threading
import urllib.error
import urllib.request

CDN = "https://asset.imassc.song4.prism.bn765.com/r"
CURRENT_URL = "https://raw.githubusercontent.com/1498zl-coder/SCSPGameData/main/versions/current.json"
NAMED_SOURCE_GAME = "2.16.0"
NAMED_SOURCE_RESOURCE = "20005500@biAa6sChu11oqPxOqwP913c="
MASK64 = (1 << 64) - 1
MAX_FILE = 128 * 1024 * 1024
MAX_DECODED = 256 * 1024 * 1024


class DownloadError(ValueError):
    pass


class Reader:
    def __init__(self, data):
        self.data, self.pos = data, 0

    def take(self, size):
        if size < 0 or self.pos + size > len(self.data):
            raise DownloadError("Truncated catalog")
        result = self.data[self.pos:self.pos + size]
        self.pos += size
        return result

    def uint64(self):
        return int.from_bytes(self.take(8), "big")

    def varuint(self):
        result = 0
        for shift in range(0, 70, 7):
            byte = self.take(1)[0]
            result |= (byte & 127) << shift
            if byte < 128:
                if result > MASK64:
                    raise DownloadError("Invalid catalog integer")
                return result
        raise DownloadError("Invalid catalog integer")

    def string(self):
        end = self.data.find(b"\0", self.pos)
        if end < 0:
            raise DownloadError("Unterminated catalog string")
        return self.take(end - self.pos + 1)[:-1].decode("utf-8")


def varuint(value):
    result = bytearray()
    while value >= 128:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


def crc64(data):
    crc = 0
    for byte in data:
        crc ^= byte << 56
        for _ in range(8):
            crc = ((crc << 1) ^ (0x42F0E1EBA9EA3693 if crc >> 63 else 0)) & MASK64
    return crc


def real_name(info):
    material = (int(info["checksum"]).to_bytes(8, "big") + varuint(info["size"])
                + int(info["label_crc"]).to_bytes(8, "big"))
    return base64.b32encode(hashlib.md5(material).digest()).decode().rstrip("=")


def root_manifest(game_version, resource_version):
    try:
        simple, encoded = resource_version.split("@", 1)
        r = Reader(base64.b64decode(encoded, validate=True))
        info = {"checksum": r.uint64(), "size": r.varuint(), "seed": r.uint64(),
                "label_crc": crc64(f"{game_version}:{simple}".encode("ascii"))}
        if r.pos != len(r.data):
            raise DownloadError("Unexpected resource-version data")
        return info
    except (ValueError, UnicodeError) as exc:
        raise DownloadError(f"Invalid GameVersion / ResourceVersion: {exc}") from exc


def crypt(data, material):
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    digest = hashlib.sha1(material).digest()
    operation = Cipher(algorithms.AES(digest[:16]), modes.CTR(digest[4:20])).decryptor()
    return operation.update(data) + operation.finalize()


def decompress(data):
    import lz4.frame
    decoder = lz4.frame.LZ4FrameDecompressor()
    result = decoder.decompress(data, max_length=MAX_DECODED + 1)
    if len(result) > MAX_DECODED or not decoder.eof or decoder.unused_data:
        raise DownloadError("Invalid or oversized LZ4 frame")
    return result


def decode_catalog(info, data):
    material = (bytes.fromhex("E040926FB42EBD50886A8849E5545924")
                + info["seed"].to_bytes(8, "big")
                + info["label_crc"].to_bytes(8, "big") + varuint(info["size"]))
    return parse_catalog(decompress(crypt(data, material)))


def parse_catalog(data):
    r = Reader(data)
    if r.take(2) != b"\xbc\x10":
        raise DownloadError("Unsupported catalog format (expected BC10)")
    count, type_count, group_count = r.varuint(), r.varuint(), r.varuint()
    if max(count, type_count, group_count) > 1_000_000:
        raise DownloadError("Unreasonable catalog table size")
    types = [r.string() for _ in range(type_count)]
    groups = [r.string() for _ in range(group_count)]
    columns = [[r.varuint() for _ in range(count)] for _ in range(7)]
    priority, resource_type, dep_count, content_count, group_counts, size, type_idx = columns
    if any(x >= type_count for x in type_idx):
        raise DownloadError("Invalid catalog type index")
    if sum(dep_count) + sum(content_count) + sum(group_counts) > len(data):
        raise DownloadError("Invalid catalog list counts")
    content_types = [[types[r.varuint()] for _ in range(n)] for n in content_count]
    entry_groups = [[groups[r.varuint()] for _ in range(n)] for n in group_counts]
    labels = [r.string() for _ in range(count)]
    contents = [[r.string() for _ in range(n)] for n in content_count]
    deps = [[r.string() for _ in range(n)] for n in dep_count]
    checksums = [r.uint64() for _ in range(count)]
    seeds = [r.uint64() if r.data[r.pos] & 128 else r.take(1)[0] for _ in range(count)]
    if r.pos != len(data):
        raise DownloadError("Unsupported catalog layout: trailing bytes")
    entries = []
    for i, label in enumerate(labels):
        name = f"{label}.{types[type_idx[i]]}"
        entry = {"label": label, "name": name, "type": types[type_idx[i]],
                 "resource_type": resource_type[i], "size": size[i],
                 "checksum": checksums[i], "seed": seeds[i],
                 "label_crc": crc64(name.encode("ascii", errors="replace")),
                 "contents": [f"{s}.{t}" for s, t in zip(contents[i], content_types[i])],
                 "content_addresses": contents[i], "dependencies": deps[i],
                 "groups": entry_groups[i]}
        entry["file"] = real_name(entry)
        entries.append(entry)
    return entries


_transfer_local = threading.local()


@contextmanager
def transfer_observer(callback):
    previous = getattr(_transfer_local, 'callback', None)
    _transfer_local.callback = callback
    try:
        yield
    finally:
        _transfer_local.callback = previous


def transfer_event(kind, **details):
    callback = getattr(_transfer_local, 'callback', None)
    if callback:
        callback(kind, details)


def get_file(info, cache):
    filename = real_name(info)
    path = cache / filename
    if path.exists() and path.stat().st_size == info["size"]:
        data = path.read_bytes()
        if not info.get("sha256") or hashlib.sha256(data).hexdigest() == info["sha256"]:
            transfer_event('cache', bytes=len(data))
            return data
    if not 0 < info["size"] <= MAX_FILE:
        raise DownloadError(f"Unsupported file size: {info['size']}")
    url = f"{CDN}/{filename[:2]}/{filename}"
    attempts = 5
    for attempt in range(attempts):
        retry_after = 0
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                data = response.read(info["size"] + 1)
            transfer_event('received', bytes=len(data))
            if len(data) != info["size"]:
                raise OSError(f"Wrong response size for {filename}: {len(data)} / {info['size']}")
            break
        except urllib.error.HTTPError as error:
            if error.code not in (408, 429, 500, 502, 503, 504):
                raise DownloadError(f"下载 {info.get('name', filename)} 失败：HTTP {error.code}") from error
            value = error.headers.get('Retry-After', '') if error.headers else ''
            retry_after = min(30, int(value)) if value.isdigit() else 0
            error.close()
            cause = error
        except (OSError, http.client.HTTPException) as error:
            cause = error
        if attempt == attempts - 1:
            raise DownloadError(f"下载 {info.get('name', filename)} 失败（已尝试 {attempts} 次）：{cause}") from cause
        delay = max(retry_after, min(8, .5 * 2 ** attempt))
        transfer_event('retry', attempt=attempt+1, max_attempts=attempts, delay=delay, error=str(cause))
        time.sleep(delay)
    if info.get("sha256") and hashlib.sha256(data).hexdigest() != info["sha256"]:
        raise DownloadError(f"SHA-256 mismatch for {filename}")
    cache.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".part")
    temporary.write_bytes(data)
    temporary.replace(path)
    transfer_event('downloaded', bytes=len(data))
    return data


def build_index(game_version, resource_version, cache):
    queue = deque([("root", root_manifest(game_version, resource_version))])
    seen, entries, catalog_bytes = set(), [], 0
    while queue:
        scope, manifest = queue.popleft()
        filename = real_name(manifest)
        if filename in seen:
            continue
        seen.add(filename)
        if len(seen) > 1000:
            raise DownloadError("Too many nested catalogs")
        print(f"Catalog {scope}: {manifest['size']:,} bytes", file=sys.stderr, flush=True)
        data = get_file(manifest, cache)
        catalog_bytes += len(data)
        for entry in decode_catalog(manifest, data):
            if entry["type"] == "catalog":
                queue.append((f"{scope}/{entry['label']}", entry))
            else:
                entry["catalog"] = scope
                entry["id"] = f"{scope}/{entry['name']}"
                entries.append(entry)
    if len({e["id"] for e in entries}) != len(entries):
        raise DownloadError("Duplicate qualified resource names")
    return {"schema": 1, "game_version": game_version, "resource_version": resource_version,
            "catalog_count": len(seen), "catalog_bytes": catalog_bytes, "entries": entries}


def fetch_metadata(url, expected_sha=None, max_size=32 * 1024 * 1024):
    with urllib.request.urlopen(url, timeout=30) as response:
        data = response.read(max_size + 1)
    if len(data) > max_size:
        raise DownloadError("Metadata exceeds size limit")
    if expected_sha and hashlib.sha256(data).hexdigest() != expected_sha:
        raise DownloadError("Published metadata SHA-256 mismatch")
    return data


def read_hash_catalog(compressed):
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as source:
        raw = source.read(64 * 1024 * 1024 + 1)
    if len(raw) > 64 * 1024 * 1024:
        raise DownloadError("Decoded hash catalog exceeds size limit")
    files = {}
    for line in raw.decode("ascii").splitlines():
        name, size, sha = line.split("\t")
        if len(name) != 26 or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567" for c in name):
            raise DownloadError("Invalid published file key")
        if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            raise DownloadError("Invalid published file SHA-256")
        if name in files:
            raise DownloadError("Duplicate published file key")
        files[name] = {"size": int(size), "sha256": sha}
    return files


def reconcile_snapshot(named, current, files):
    entries = []
    for entry in named["entries"]:
        record = files.get(entry["file"])
        if record and record["size"] == entry["size"]:
            entries.append({**entry, "sha256": record["sha256"]})
    mapped = {e["file"] for e in entries}
    unmapped = sorted(set(files) - mapped)
    return {"schema": 1, "game_version": current["application"],
            "resource_version": current["resource"], "source_kind": "public_snapshot",
            "snapshot_url": CURRENT_URL, "official_live_latest_verified": False,
            "source_game_version": named["game_version"],
            "source_resource_version": named["resource_version"],
            "snapshot_files": len(files), "mapped_files": len(mapped),
            "unmapped_files": len(unmapped), "unmapped_hashes": unmapped,
            "name_index_complete": not unmapped, "entries": entries}


def build_latest_snapshot(cache):
    current = json.loads(fetch_metadata(CURRENT_URL, max_size=1024 * 1024))
    if current.get("schema_version") != 2:
        raise DownloadError("Unsupported published version format")
    manifest_bytes = fetch_metadata(current["manifest_url"], current["manifest_sha256"])
    manifest = json.loads(manifest_bytes)
    if (manifest.get("schema_version") != 2 or manifest["resource"] != current["resource"]
            or manifest["application"] != current["application"]):
        raise DownloadError("Published version and manifest disagree")
    catalog = next(a for a in manifest["artifacts"] if a["asset"] == "catalog.tsv.gz")
    url = (f"https://github.com/{manifest['owner']}/{manifest['repo']}/releases/download/"
           f"{manifest['tag']}/{catalog['asset']}")
    compressed = fetch_metadata(url, catalog["sha256"])
    files = read_hash_catalog(compressed)
    if len(files) != manifest["files"]:
        raise DownloadError("Published catalog count does not match manifest")
    print(f"Public snapshot: client {current['application']}, resource {current['resource']}, "
          f"{len(files):,} files", file=sys.stderr, flush=True)
    named = build_index(NAMED_SOURCE_GAME, NAMED_SOURCE_RESOURCE, cache)
    result = reconcile_snapshot(named, current, files)
    result["snapshot_manifest_sha256"] = current["manifest_sha256"]
    result["snapshot_catalog_sha256"] = catalog["sha256"]
    result["metadata_bytes"] = len(manifest_bytes) + len(compressed) + named["catalog_bytes"]
    return result


def select(entries, names, matches):
    selected = {}
    for name in names:
        found = [e for e in entries if name in [e["id"], e["name"], *e["contents"]]]
        if len(found) != 1:
            raise DownloadError(f"Exact name {name!r} matches {len(found)} bundles; use a qualified id")
        selected[found[0]["id"]] = found[0]
    for entry in entries:
        strings = [entry["id"], *entry["contents"]]
        if any(term.lower() in value.lower() for term in matches for value in strings):
            selected[entry["id"]] = entry
    return list(selected.values())


def discover_songs(entries):
    """Discover named body families; exclude cutscene and lesson variants."""
    families = defaultdict(lambda: {"numbered": set(), "shared": False, "formats": set()})
    expressions = defaultdict(set)
    names = {PurePosixPath(e["name"]).name.lower() for e in entries}
    for entry in entries:
        name = PurePosixPath(entry["name"]).name.lower()
        match = re.fullmatch(r"(\d{3}_[a-z0-9]+)(?:_(\d{2}))?(\.anim|_body\.asset)", name)
        if match:
            family = families[match[1]]
            family["formats"].add("anim" if match[3] == ".anim" else "body_asset")
            if match[2]:
                if 1 <= int(match[2]) <= 99:
                    family["numbered"].add(int(match[2]))
            else:
                family["shared"] = True
        match = re.fullmatch(r"(\d{3}_[a-z0-9]+)_(\d{2})_exp\.json", name)
        if match and 1 <= int(match[2]) <= 99:
            expressions[match[1]].add(int(match[2]))
    result = []
    for code, family in sorted(families.items()):
        if family["numbered"]:
            slots, mode = sorted(family["numbered"]), "numbered"
        elif family["shared"] and expressions[code]:
            slots, mode = sorted(expressions[code]), "shared"
        elif family["shared"]:
            # A bare auxiliary clip can resemble a song code (e.g. attachbonetarget).
            if family["formats"] == {"anim"} and not any(code + suffix in names for suffix in
                    ("_root.asset", "_exp.json", "_camera.json", "_unit.json", "_scenecreate.json", "_sequence.json", ".acb")):
                continue
            slots, mode = [], "single"
        else:
            continue
        result.append({"code": code, "slots": slots, "mode": mode, "formats": sorted(family["formats"])})
    return result


def select_song(entries, code, requested_slots=()):
    """Group the named main-dance family; catalog dependencies omit these links."""
    code = code.lower()
    if not re.fullmatch(r"\d{3}_[a-z0-9]+", code):
        raise DownloadError("Use an internal song code such as 002_yumeas")
    if any(slot < 1 or slot > 99 for slot in requested_slots):
        raise DownloadError("Song slots must be between 1 and 99")
    lookup = defaultdict(list)
    for entry in entries:
        lookup[PurePosixPath(entry["name"]).name.lower()].append(entry)
    family = next((song for song in discover_songs(entries) if song["code"] == code), None)
    if not family:
        raise DownloadError(f"No named body animation/data found for {code} in this index")
    available = family["slots"]
    slots = sorted(set(requested_slots)) if requested_slots else available
    if family["mode"] == "single" and requested_slots:
        raise DownloadError(f"{code} has an unnumbered body file; omit --slot")
    unavailable = set(slots) - set(available)
    if unavailable:
        raise DownloadError(f"No main-dance animation for {code}, slots {sorted(unavailable)}")
    selected, roles, missing = {}, {}, []

    def add(name, role, required=False):
        candidates = lookup.get(name, [])
        if len(candidates) > 1:
            raise DownloadError(f"Song companion {name!r} is ambiguous; use qualified --name selectors")
        if not candidates:
            if required:
                missing.append(f"song {code} -> {name} (0 matches)")
            return
        entry = candidates[0]
        selected[entry["id"]] = entry
        roles[entry["id"]] = role

    def add_body(stem):
        name = stem + ".anim" if lookup.get(stem + ".anim") else stem + "_body.asset"
        add(name, "body", required=True)

    if family["mode"] == "numbered":
        for slot in slots:
            stem = f"{code}_{slot:02d}"
            add_body(stem)
            add(stem + "_root.asset", "root", required=True)
            add(stem + "_exp.json", "expression", required=True)
    else:
        add_body(code)
        if slots:
            for slot in slots:
                stem = f"{code}_{slot:02d}"
                root_name = stem + "_root.asset" if lookup.get(stem + "_root.asset") else code + "_root.asset"
                add(root_name, "root", required=True)
                add(stem + "_exp.json", "expression", required=True)
        else:
            add(code + "_root.asset", "root", required=True)
            add(code + "_exp.json", "expression", required=True)
    for name, role in ((code + "_camera.json", "camera"),
                       (code + "_cameraanime.fbx", "camera_animation"),
                       (code + "_unit.json", "unit"),
                       (code + "_sequence.json", "sequence"),
                       (code.split("_", 1)[1] + ".playable", "timeline")):
        add(name, role)
    mouth_names = sorted(name for name in lookup if re.fullmatch(
        re.escape(code.split("_", 1)[1]) + r"_[a-z]+\.asset", name))
    for name in mouth_names:
        add(name, "mouth_samples")
    return list(selected.values()), {"code": code, "slots": slots,
                                     "mouth_resource_count": len(mouth_names),
                                     "mouth_selection": "all_named_variants" if mouth_names else "not_found",
                                     "available_slots": available, "body_mode": family["mode"],
                                     "body_formats": family["formats"],
                                     "roles": roles,
                                     "missing_companions": sorted(set(missing)),
                                     "includes_cutscene_variants": False}


def dependency_lookup(entries):
    lookup = defaultdict(list)
    for entry in entries:
        for name in set([entry["id"], entry["name"], *entry["contents"]]):
            lookup[name].append(entry)
    return lookup


def resolve_dependencies(entries, selected, lookup=None):
    if lookup is None:
        lookup = dependency_lookup(entries)
    result, queue, missing = {}, deque(selected), set()
    while queue:
        entry = queue.popleft()
        if entry["id"] in result:
            continue
        result[entry["id"]] = entry
        for dep in entry["dependencies"]:
            candidates = lookup.get(dep, [])
            same_scope = [e for e in candidates if e["catalog"] == entry["catalog"]]
            if same_scope:
                candidates = same_scope
            if len(candidates) == 1:
                queue.append(candidates[0])
            else:
                missing.add(f"{entry['id']} -> {dep} ({len(candidates)} matches)")
    return list(result.values()), sorted(missing)


def decode_asset(entry, data):
    kind = entry["resource_type"]
    if kind in (0, 64):
        return data
    if kind == 1:
        if len(data) < 4:
            raise DownloadError("Truncated padded bundle")
        return data[4:]
    if kind == 65:
        return decompress(data)
    if kind == 66:
        material = struct.pack(">QQQ", entry["seed"], entry["label_crc"], entry["size"])
        return decompress(crypt(data, material))
    raise DownloadError(f"Unsupported resource type {kind}")


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def safe_output(root, relative):
    relative = PurePosixPath(relative)
    if relative.is_absolute() or any(p in ("..", ".") or ":" in p or "\\" in p for p in relative.parts):
        raise DownloadError("Invalid output resource path")
    path = root.joinpath(*relative.parts).resolve()
    if not path.is_relative_to(root.resolve()):
        raise DownloadError("Output resource path escapes destination")
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    index = sub.add_parser("index", help="Download ONLY catalogs, not game assets")
    index.add_argument("--game-version", required=True)
    index.add_argument("--resource-version", required=True)
    index.add_argument("--index", type=Path, default=Path("index.json"))
    index.add_argument("--cache", type=Path, default=Path(".scsp-cache"))
    latest = sub.add_parser("latest-index", help="Index the newest public snapshot; reports unmapped new files")
    latest.add_argument("--index", type=Path, default=Path("index.json"))
    latest.add_argument("--cache", type=Path, default=Path(".scsp-cache"))
    for command in ("search", "plan", "fetch"):
        p = sub.add_parser(command)
        p.add_argument("--index", type=Path, default=Path("index.json"))
        p.add_argument("--name", action="append", default=[], help="Exact bundle id or typed content name; repeatable")
        p.add_argument("--match", action="append", default=[], help="Substring of bundle/content name; repeatable")
        p.add_argument("--song-code", help="Main dance plus named companions, e.g. 002_yumeas; excludes cutscenes")
        p.add_argument("--slot", action="append", type=int, default=[],
                       help="Main dance position (not character id); repeatable, defaults to all positions")
        if command != "search":
            p.add_argument("--plan-out", type=Path)
        if command == "fetch":
            p.add_argument("--out", type=Path, required=True)
            p.add_argument("--cache", type=Path, default=Path(".scsp-cache"))
            p.add_argument("--allow-unresolved", action="store_true",
                           help="Download resolvable bundles and record absent dependencies in manifest.json")
            p.add_argument("--max-total-mb", type=float, default=256,
                           help="Maximum selected compressed bytes (default 256 MiB)")
    args = parser.parse_args(argv)
    if args.command == "latest-index":
        data = build_latest_snapshot(args.cache)
        write_json(args.index, data)
        print(f"Snapshot {data['resource_version']}: {data['mapped_files']:,} named files / "
              f"{data['snapshot_files']:,}; {data['unmapped_files']:,} unmapped files. "
              "Name index is partial; this is not an official live version check.")
        return 0
    if args.command == "index":
        data = build_index(args.game_version, args.resource_version, args.cache)
        write_json(args.index, data)
        print(f"Indexed {len(data['entries']):,} bundles from {data['catalog_count']} catalogs "
              f"({data['catalog_bytes']:,} downloaded metadata bytes). No game assets downloaded.")
        return 0
    if not args.name and not args.match and not args.song_code:
        parser.error("Provide --name, --match or --song-code; whole-game downloads are not supported")
    if args.slot and not args.song_code:
        parser.error("--slot requires --song-code")
    data = json.loads(args.index.read_text(encoding="utf-8"))
    if data.get("schema") != 1:
        raise DownloadError("Unsupported index format")
    if data.get("source_kind") == "public_snapshot":
        print(f"Public snapshot {data['resource_version']}: "
              f"{data['mapped_files']:,}/{data['snapshot_files']:,} files named; "
              f"{data['unmapped_files']:,} unmapped. Snapshot may lag official updates.", file=sys.stderr)
    selected = select(data["entries"], args.name, args.match)
    song_selection = None
    if args.song_code:
        song_entries, song_selection = select_song(data["entries"], args.song_code, args.slot)
        selected = list({e["id"]: e for e in [*selected, *song_entries]}.values())
    if not selected:
        raise DownloadError("No matching resource in this version's catalogs")
    if args.command == "search":
        for entry in selected:
            print(f"{entry['id']}\t{entry['size']:,} bytes\t{len(entry['dependencies'])} deps")
            for content in entry["contents"][:8]:
                print(f"  {content}")
        print(f"{len(selected)} matching bundles")
        return 0
    planned, missing = resolve_dependencies(data["entries"], selected)
    if song_selection:
        missing.extend(song_selection["missing_companions"])
    unique = {e["file"]: e for e in planned}
    total = sum(e["size"] for e in unique.values())
    plan = {"game_version": data["game_version"], "resource_version": data["resource_version"],
            "selected_ids": [e["id"] for e in selected], "total_bytes": total,
            "unique_files": len(unique), "dependency_complete": not missing,
            "unresolved_dependencies": missing, "entries": planned}
    if song_selection:
        plan["song_selection"] = song_selection
    if data.get("source_kind") == "public_snapshot":
        plan["snapshot_provenance"] = {k: data[k] for k in (
            "snapshot_url", "snapshot_manifest_sha256", "snapshot_catalog_sha256",
            "source_game_version", "source_resource_version", "snapshot_files", "mapped_files",
            "unmapped_files", "name_index_complete", "official_live_latest_verified")}
    if args.plan_out:
        write_json(args.plan_out, plan)
    print(f"Selected {len(selected)} bundles; with dependencies: {len(planned)} entries, "
          f"{len(unique)} files, {total:,} bytes ({total / 1048576:.2f} MiB)")
    if missing and args.command == "fetch" and not args.allow_unresolved:
        raise DownloadError("Unresolved dependencies:\n" + "\n".join(missing[:20]))
    if missing:
        print("Unresolved dependencies / song companions (recorded in the plan or manifest):", file=sys.stderr)
        for dep in missing[:20]:
            print(dep, file=sys.stderr)
    if args.command == "plan":
        for entry in planned:
            print(entry["id"])
        return 0
    if total > args.max_total_mb * 1048576:
        raise DownloadError("Selected download exceeds --max-total-mb")
    output_records = []
    for i, entry in enumerate(unique.values(), 1):
        raw = get_file(entry, args.cache)
        decoded = decode_asset(entry, raw)
        relative = (f"bundles/{entry['file']}.unity3d" if entry["resource_type"] in (0, 1)
                    else f"raw/{entry['id']}")
        path = safe_output(args.out, relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".part")
        temporary.write_bytes(decoded)
        temporary.replace(path)
        output_records.append({"file": entry["file"], "output": relative,
                               "sha256": hashlib.sha256(decoded).hexdigest()})
        print(f"[{i}/{len(unique)}] {entry['name']} -> {relative}", flush=True)
    plan["outputs"] = output_records
    write_json(args.out / "manifest.json", plan)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (DownloadError, OSError, ValueError, IndexError, ImportError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
