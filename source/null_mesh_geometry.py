"""Attach geometry entries for model prefabs whose SkinnedMeshRenderer m_Mesh is a
null PPtr {0,0} (geometry assigned by name at game runtime).

Stylistically mirrors appearance_resources.attach_makeup_models: resolved extra
entries are appended to the download plan and de-duplicated by entry id. Only
prefabs that the mesh audit flagged with ``null_pptr`` trigger association; normal
model prefabs are never modified.

The geometry mapping is data-driven from the audit result: for a null-mesh prefab
we attach the catalogue entries that supply the missing meshes by *file name*
(mirroring how GEOMETRY-LOCATE-REPORT located m_head_91 -> nvzw3gi/*.asset). This
module keeps a small explicit table for the verified case plus a generic
name-based resolver for future ones.
"""
from __future__ import annotations

import json
from pathlib import Path, PurePosixPath

from runtime_paths import app_root

# Verified mapping: null-mesh prefab short name -> list of geometry asset entry ids
# (each nvzw3gi/*.asset contains exactly one Mesh named like the stale GameObject).
# Derived from GEOMETRY-LOCATE-REPORT.md (16/16 mesh names matched).
HEAD_GEOMETRY_SHARED_DIR = "nvzw3gi/"
HEAD_GEOMETRY_FOR_91 = [
    "root/assetbundles/nvzw3gi/faceline.asset", "root/assetbundles/nvzw3gi/face_close.asset",
    "root/assetbundles/nvzw3gi/eyelash_l.asset", "root/assetbundles/nvzw3gi/face.asset",
    "root/assetbundles/nvzw3gi/eye_hole_l.asset", "root/assetbundles/nvzw3gi/eyelashop_r.asset",
    "root/assetbundles/nvzw3gi/eyebrow_r.asset", "root/assetbundles/nvzw3gi/mouthline.asset",
    "root/assetbundles/nvzw3gi/eyelash_r.asset", "root/assetbundles/nvzw3gi/eyelashop_l.asset",
    "root/assetbundles/nvzw3gi/eye_hole_r.asset", "root/assetbundles/nvzw3gi/tongue.asset",
    "root/assetbundles/nvzw3gi/mouth_hole.asset", "root/assetbundles/nvzw3gi/eyebrow_l.asset",
    "root/assetbundles/nvzw3gi/mouth_inner.asset", "root/assetbundles/nvzw3gi/teeth.asset",
]

_GEOMETRY_BY_PREFAB = {
    "m_head_91.prefab": HEAD_GEOMETRY_FOR_91,
    # Accessory geometry actually lives in the same-numbered hair prefab's closure
    # (e.g. m_hair_16_001_40358 / m_hair_28_002_40370). Attach the concrete .asset
    # entries that carry the required meshes (verified in-closure by name).
    "m_acce_40358_16ev01_00_16.prefab": [
        "root/assetbundles/xww64ea/cap.asset",
        "root/assetbundles/xww64ea/bow.asset",
    ],
    "m_acce_40370_28ev01_00_28.prefab": [
        "root/assetbundles/m2sagoa/cap.asset",
        "root/assetbundles/m2sagoa/headwear.asset",
    ],
    # hair_91 geometry: the original unified geometry bundle is absent from the
    # catalogue, but its five meshes survive as separate per-part bundles in the
    # orphan `nelt2ki/` prefix (all 5 frontHair/backHair1/2/3/sideHair present,
    # referenced by no other hair prefab). Verified mesh names in-closure.
    "m_hair_91_001_00000.prefab": [
        "root/assetbundles/nelt2ki/fronthair.asset",
        "root/assetbundles/nelt2ki/backhair1.asset",
        "root/assetbundles/nelt2ki/backhair2.asset",
        "root/assetbundles/nelt2ki/backhair3.asset",
        "root/assetbundles/nelt2ki/sidehair.asset",
    ],
}


def _audit_state_path():
    return app_root() / ".mesh-audit-state.json"


def load_null_mesh_prefabs(state_path=None, entries=None):
    """Return {prefab_id: [stale GameObject names]} for null_pptr issue prefabs.

    Self-contained on purpose: the export fix must remain fully usable even when
    the mesh-audit module is not shipped. Two independent sources are unioned:

    1.  The explicit verified table ``_GEOMETRY_BY_PREFAB`` (prefab file name ->
        geometry assets). These prefabs are *known* null-mesh cases; their stale
        GameObject names are derived from the geometry asset file names
        (``<mesh>.asset``), which is exactly the naming convention verified during
        geometry location. No audit state file is required for these.
    2.  A previously produced ``.mesh-audit-state.json`` (if present), which lets
        newly audited prefabs join without a code change.
    """
    result = {}
    # Source 2 first (so explicit table can refine), then source 1.
    path = Path(state_path) if state_path else _audit_state_path()
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        for prefab_id, rec in data.get("results", {}).items():
            if not isinstance(rec, dict) or rec.get("status") != "issue":
                continue
            problems = [p for p in rec.get("problems", []) if p.get("type") == "null_pptr"]
            if problems:
                result[prefab_id] = [p.get("game_object") for p in problems]
    # Explicit table: resolve prefab ids from entries (by file name) and derive names.
    if entries is not None:
        by_file = {}
        for e in entries:
            if e.get("type") == "prefab":
                by_file.setdefault(PurePosixPath(e["name"]).name.lower(), e)
        for short, gids in _GEOMETRY_BY_PREFAB.items():
            e = by_file.get(short)
            if not e:
                continue
            names = [PurePosixPath(g).name[:-6] for g in gids]  # "<mesh>.asset" -> mesh
            # Union; state names (if any) kept first for order stability.
            existing = result.get(e["id"], [])
            result[e["id"]] = existing + [n for n in names if n not in existing]
    return result


def geometry_entry_ids(prefab_entry, null_names, by_name):
    """Resolve geometry entry ids for one null-mesh prefab.

    Returns (entry_ids, matches) where matches = {game_object_name: entry_id}.
    First tries the explicit verified table; falls back to matching catalogue
    ``.asset`` entries whose file name is ``<game_object>.asset`` and which are
    unique across the whole catalogue (same rationale as the locate step).
    """
    short = PurePosixPath(prefab_entry["name"]).name.lower()
    ids, matches = [], {}
    explicit = _GEOMETRY_BY_PREFAB.get(short)
    if explicit:
        for gid in explicit:
            matches[PurePosixPath(gid).name[:-6]] = gid  # strip ".asset"
        return list(dict.fromkeys(explicit)), matches
    # Generic fallback: unique <mesh>.asset per stale name.
    for go in null_names:
        cands = by_name.get((go + ".asset").lower(), [])
        cands = [c for c in cands if c.get("type") == "asset"]
        if len(cands) == 1:
            ids.append(cands[0]["id"])
            matches[go] = cands[0]["id"]
    return list(dict.fromkeys(ids)), matches


def attach_null_mesh_geometry(entries, selected_entries, null_prefabs, by_id=None, by_name=None):
    """Return (extra_entries, records) for null-mesh prefabs present in selection.

    ``selected_entries`` is the list of currently selected catalogue entries.
    Only prefabs whose id is a key in ``null_prefabs`` trigger association.
    """
    if by_id is None:
        by_id = {e["id"]: e for e in entries}
    if by_name is None:
        by_name = {}
        for e in entries:
            by_name.setdefault(PurePosixPath(e["name"]).name.lower(), []).append(e)
    extra = {}
    records = []
    selected_ids = {e["id"] for e in selected_entries}
    for prefab in selected_entries:
        if prefab.get("type") != "prefab":
            continue
        if prefab["id"] not in null_prefabs:
            continue
        names = null_prefabs[prefab["id"]]
        gids, matches = geometry_entry_ids(prefab, names, by_name)
        added = []
        for gid in gids:
            e = by_id.get(gid)
            if not e:
                continue
            if gid not in selected_ids:
                extra[gid] = e
            added.append(gid)
        records.append({
            "prefab_id": prefab["id"], "prefab_name": prefab["name"],
            "reason": "null_pptr_geometry", "stale_objects": names,
            "geometry_entry_ids": added, "matches": matches,
        })
    return list(extra.values()), records
