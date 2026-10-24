"""Export inspection assets from downloaded SCSP manifests; no retargeting."""
from __future__ import annotations

import argparse
from array import array
import hashlib
import json
from pathlib import Path
import re
import sys


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def contained(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"Path escapes sample directory: {relative}")
    return path


def dense_payload(clip):
    """Validate and preserve dense floats without interpreting Animator attributes."""
    data = clip["m_MuscleClip"]["m_Clip"]["data"]
    dense = data["m_DenseClip"]
    count = dense["m_FrameCount"] * dense["m_CurveCount"]
    if len(dense["m_SampleArray"]) != count:
        raise ValueError("Dense sample count does not match frame/channel dimensions")
    samples = array("f", dense["m_SampleArray"])
    if samples.itemsize != 4:
        raise ValueError("Platform float size is not 32 bits")
    if sys.byteorder != "little":
        samples.byteswap()
    metadata = {k: v for k, v in dense.items() if k != "m_SampleArray"}
    metadata.update({"encoding": "float32 little-endian", "layout": "frame-major",
                     "scalar_count": count})
    return samples.tobytes(), metadata


def object_key(obj):
    return f"{obj.assets_file.name}:{obj.path_id}"


def export_sample(sample, destination, cache=None):
    import UnityPy
    from UnityPy.export.MeshExporter import export_mesh_obj
    from UnityPy.helpers.MeshHelper import MeshHandler

    sample, destination = sample.resolve(), destination.resolve()
    if destination.exists() and any(destination.iterdir()):
        raise ValueError(f"Output directory must be empty: {destination}")
    manifest = json.loads((sample / "manifest.json").read_text(encoding="utf-8"))
    outputs = {r["file"]: r["output"] for r in manifest["outputs"]}
    output_hashes = {r["file"]: r["sha256"] for r in manifest["outputs"]}
    bundle_sources = {Path(outputs[e["file"]]).name: e for e in manifest["entries"]}
    # Verify the original CDN bytes, when a cache is supplied, before exporting.
    verified = 0
    for entry in manifest["entries"]:
        if cache is not None:
            raw = contained(cache, entry["file"]).read_bytes()
            if len(raw) != entry["size"]:
                raise ValueError(f"Source size mismatch: {entry['name']}")
            if entry.get("sha256") and hashlib.sha256(raw).hexdigest() != entry["sha256"]:
                raise ValueError(f"Source SHA-256 mismatch: {entry['name']}")
            if entry.get("sha256"):
                verified += 1
        decoded = contained(sample, outputs[entry["file"]]).read_bytes()
        if hashlib.sha256(decoded).hexdigest() != output_hashes[entry["file"]]:
            raise ValueError(f"Decoded output SHA-256 mismatch: {entry['name']}")

    destination.mkdir(parents=True, exist_ok=True)
    report = {"schema": 1, "game_version": manifest["game_version"],
              "resource_version": manifest["resource_version"],
              "snapshot_provenance": manifest.get("snapshot_provenance"),
              "source_sha256_verified_files": verified,
              "dependency_complete": manifest["dependency_complete"],
              "unresolved_dependencies": manifest["unresolved_dependencies"],
              "official_live_latest_verified": False,
              "model_animation_playback_verified": False, "fbx_export_tested": False,
              "coordinate_notes": "Mesh JSON and rig JSON retain Unity coordinates. OBJ uses UnityPy's X reflection and reversed triangle winding.",
              "objects": [], "animations": [], "reference_checks": [], "warnings": [], "errors": []}
    bundle_paths = [str(contained(sample, r["output"])) for r in manifest["outputs"]
                    if r["output"].endswith(".unity3d")]
    env = UnityPy.load(*bundle_paths)
    rig = []

    def check_pointer(pointer):
        if pointer.m_PathID == 0:
            return {"status": "null"}
        try:
            return {"status": "resolved", "target": object_key(pointer.deref())}
        except Exception as exc:
            return {"status": "unresolved", "file_id": pointer.m_FileID,
                    "path_id": pointer.m_PathID, "error": str(exc)}

    selected_types = {"Mesh", "Texture2D", "Avatar", "AnimationClip", "MonoBehaviour",
                      "Transform", "GameObject", "SkinnedMeshRenderer", "Animator", "Material"}
    for obj in env.objects:
        kind = obj.type.name
        if kind not in selected_types:
            continue
        identity = object_key(obj)
        stem = re.sub(r"[^A-Za-z0-9_.-]", "_", identity)
        record = {"id": identity, "type": kind}
        source = bundle_sources.get(obj.assets_file.parent.name)
        if source:
            record.update({"resource": source["name"], "source_file": source["file"]})
        report["objects"].append(record)
        try:
            data = obj.read()
            record["name"] = getattr(data, "m_Name", None)
            if kind == "Mesh":
                mesh = MeshHandler(data)
                mesh.process()
                native = obj.parse_as_dict()
                mesh_data = {"name": data.m_Name, "vertices": mesh.m_Vertices,
                             "normals": mesh.m_Normals, "uv0": mesh.m_UV0,
                             "triangles_by_submesh": mesh.get_triangles(),
                             "bone_indices": mesh.m_BoneIndices, "bone_weights": mesh.m_BoneWeights,
                             "bind_poses": native.get("m_BindPose"),
                             "blend_shapes": native.get("m_Shapes")}
                if mesh.m_BoneIndices and not mesh.m_BoneWeights:
                    report["warnings"].append({"id": identity, "type": "skin_weights_not_decoded",
                        "message": "Bone indices are present but no explicit weights were decoded. No weights were invented; original mesh bytes are preserved."})
                write_json(destination / "meshes" / f"{stem}.json", mesh_data)
                (destination / "meshes" / f"{stem}.bytes").write_bytes(obj.get_raw_data())
                obj_text = export_mesh_obj(data)
                if not obj_text:
                    raise ValueError("Mesh has no exportable vertices")
                (destination / "meshes" / f"{stem}.obj").write_text(obj_text, encoding="utf-8")
                record.update({"vertices": mesh.m_VertexCount,
                               "mesh_json": f"meshes/{stem}.json", "obj": f"meshes/{stem}.obj",
                               "native_mesh_bytes": f"meshes/{stem}.bytes"})
            elif kind == "Texture2D":
                path = destination / "textures" / f"{stem}.png"
                path.parent.mkdir(parents=True, exist_ok=True)
                data.image.save(path)
                record.update({"png": f"textures/{stem}.png", "width": data.m_Width,
                               "height": data.m_Height})
            elif kind == "AnimationClip":
                clip = obj.parse_as_dict()
                payload, dense = dense_payload(clip)
                anim_dir = destination / "animations"
                anim_dir.mkdir(exist_ok=True)
                (anim_dir / f"{stem}.f32").write_bytes(payload)
                clip["m_MuscleClip"]["m_Clip"]["data"]["m_DenseClip"].pop("m_SampleArray")
                write_json(anim_dir / f"{stem}.json", clip)
                muscle = clip["m_MuscleClip"]
                report["animations"].append({**record, "name": data.m_Name,
                    "sample_rate_hz": data.m_SampleRate,
                    "duration_seconds": muscle["m_StopTime"] - muscle["m_StartTime"],
                    "dense": dense, "samples": f"animations/{stem}.f32",
                    "clip_metadata": f"animations/{stem}.json",
                    "binding_type_ids": sorted({b["typeID"] for b in clip["m_ClipBindingConstant"]["genericBindings"]})})
            elif kind in {"Transform", "GameObject", "SkinnedMeshRenderer", "Animator"}:
                rig.append({**record, "serialized_file": obj.assets_file.name,
                            "data": obj.parse_as_dict()})
                if kind == "SkinnedMeshRenderer":
                    report["reference_checks"].append({"id": identity,
                        "mesh": check_pointer(data.m_Mesh),
                        "bones": [check_pointer(bone) for bone in data.m_Bones],
                        "root_bone": check_pointer(data.m_RootBone)})
                elif kind == "Animator":
                    report["reference_checks"].append({"id": identity,
                        "avatar": check_pointer(data.m_Avatar)})
            else:
                write_json(destination / "serialized" / f"{stem}.json", obj.parse_as_dict())
                record["json"] = f"serialized/{stem}.json"
        except Exception as exc:
            report["errors"].append({"id": identity, "type": kind,
                                     "error": f"{type(exc).__name__}: {exc}"})

    write_json(destination / "rig.json", rig)
    # Non-bundle companions preserve root/expression/camera/sequence data and resource names.
    companions = []
    for entry in manifest["entries"]:
        relative = outputs[entry["file"]]
        if relative.endswith(".unity3d"):
            continue
        path = contained(destination / "companions", relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contained(sample, relative).read_bytes())
        companions.append({"resource": entry["name"], "path": str(path.relative_to(destination))})
    report["companions"] = companions
    report["exported_files"] = [{"path": str(p.relative_to(destination)), "bytes": p.stat().st_size,
                                  "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                                 for p in sorted(destination.rglob("*")) if p.is_file()]
    write_json(destination / "report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cache", type=Path, help="Verify cached CDN source bytes against the sample manifest")
    args = parser.parse_args()
    report = export_sample(args.sample, args.out, args.cache)
    print(json.dumps({"output": str(args.out.resolve()), "objects": len(report["objects"]),
                      "animations": len(report["animations"]), "warnings": len(report["warnings"]),
                      "errors": report["errors"]}, ensure_ascii=False))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
