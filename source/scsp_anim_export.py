"""Restore independent AnimationClips from downloaded bundles, including body wrappers."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import socket
import subprocess
import time
import urllib.parse
import urllib.request

from runtime_paths import app_root
ROOT = app_root()
RIPPER = ROOT / "tools/AssetRipper/2.0.0/AssetRipper.GUI.Free.exe"


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1048576), b""):
            h.update(block)
    return h.hexdigest()


def export_animations(sample, output=None, progress=lambda text: None):
    import UnityPy
    sample = Path(sample).resolve()
    output = Path(output).resolve() if output else sample / "animations"
    manifest = json.loads((sample / "manifest.json").read_text(encoding="utf-8"))
    entries = {e["file"]: e for e in manifest["entries"]}
    carriers, sources, missing_clips = [], [], []
    for item in manifest["outputs"]:
        path = (sample / item["output"]).resolve()
        if not path.is_relative_to(sample):
            raise ValueError("Animation input escapes download directory")
        if digest(path) != item["sha256"]:
            raise ValueError("Decoded input hash mismatch: " + item["output"])
        with path.open("rb") as source:
            magic = source.read(8)
        if not magic.startswith((b"UnityFS", b"UnityRaw", b"UnityWeb")):
            continue
        env = UnityPy.load(path.read_bytes())  # Avoid Windows file handles surviving preview cleanup.
        objects = [o for o in env.objects if o.type.name == "AnimationClip"]
        resource = entries[item["file"]]
        if resource["id"] in manifest["selected_ids"] and (resource["type"] == "anim" or resource["name"].endswith("_body.asset")) and not objects:
            missing_clips.append(resource["name"])
        if objects:
            carriers.append(path)
        for obj in objects:
            tree = obj.read_typetree()
            muscle = tree.get("m_MuscleClip", {})
            sources.append({"resource": entries[item["file"]]["name"], "bundle": item["output"],
                            "path_id": obj.path_id, "name": tree["m_Name"],
                            "sample_rate": tree["m_SampleRate"], "stop_time": muscle.get("m_StopTime"),
                            "bindings": len(tree.get("m_ClipBindingConstant", {}).get("genericBindings", [])), "humanoid_bindings": sum(b.get("typeID")==95 for b in tree.get("m_ClipBindingConstant",{}).get("genericBindings",[]))})
        del env
    if missing_clips:
        raise RuntimeError("所选动作未找到内部AnimationClip，尚不支持此布局：" + ", ".join(missing_clips))
    report = {"exporter": "AssetRipper 2.0.0", "sources": sources, "clips": [],
              "unity_import_verified": False, "model_playback_verified": False}
    if not carriers:
        return report
    if not RIPPER.is_file():
        raise RuntimeError("未找到AssetRipper，不能把原始动作冒充为可用anim。")
    output.mkdir(parents=True, exist_ok=True)
    work = sample / "animation-export-work"
    work.mkdir(parents=True, exist_ok=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    log = (work / "process.log").open("wb")
    process = subprocess.Popen([str(RIPPER), "--port", str(port), "--headless", "--log-path", str(work / "assetripper.log")],
                               cwd=RIPPER.parent, stdout=log, stderr=subprocess.STDOUT,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 60
        while True:
            try:
                urllib.request.urlopen(base, timeout=2).close()
                break
            except OSError:
                if process.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("AssetRipper启动失败，详见 " + str(work / "process.log"))
                time.sleep(.2)
        progress(f"正在恢复 {len(sources)} 个内部AnimationClip（包括流式曲线）")
        data = urllib.parse.urlencode([("Path", str(p)) for p in carriers]).encode()
        urllib.request.urlopen(urllib.request.Request(base + "/LoadFile", data=data), timeout=900).close()
        ripped = work / "export"
        urllib.request.urlopen(urllib.request.Request(base + "/Export/UnityProject",
                              data=urllib.parse.urlencode({"Path": str(ripped)}).encode()), timeout=900).close()
        files = sorted((ripped / "ExportedProject/Assets").rglob("*.anim"))
        if len(files) != len(sources):
            raise RuntimeError(f"动画导出数量不一致：源{len(sources)}，输出{len(files)}；未静默跳过。")
        for source in files:
            name = source.name
            while name.lower().endswith(".anim.anim"):
                name = name[:-5]
            target = output / name
            if target.exists():
                raise ValueError("不覆盖已有动画：" + str(target))
            shutil.move(source, target)
            if source.with_suffix(source.suffix + ".meta").exists():
                shutil.copy2(source.with_suffix(source.suffix + ".meta"), target.with_suffix(".anim.meta"))
            report["clips"].append({"file": target.relative_to(sample).as_posix() if target.is_relative_to(sample) else str(target),
                                    "bytes": target.stat().st_size, "sha256": digest(target)})
        if manifest.get('convert_generic_humanoid'):
            from generic_motion import lip_data
            from scsp_motion_preview import retarget
            report['warnings']=[]
            for item in list(report['clips']):
                original=sample/item['file']
                source=next((s for s in sources if s['name'].casefold()==original.stem.casefold()),None)
                if not source or source.get('humanoid_bindings'):continue
                resource=next((e for e in manifest['entries'] if e['name']==source['resource']),None)
                if not resource or resource['id'] not in manifest['selected_ids'] or not (resource['type']=='anim' or resource['name'].endswith('_body.asset')):
                    item['kind']='auxiliary';continue
                try:
                    if lip_data(original):item['kind']='lip';continue
                    folder=sample/'animation-convert-work'/original.stem;folder.mkdir(parents=True,exist_ok=True)
                    result=retarget(original,folder)
                    if result.get('kind')=='generic_humanoid':
                        converted=output/(original.stem+'_humanoid.anim');shutil.copy2(folder/'converted.anim',converted)
                        report['clips'].append(dict(file=converted.relative_to(sample).as_posix(),bytes=converted.stat().st_size,sha256=digest(converted),kind='converted_humanoid',source_file=item['file']))
                except ValueError as error:report['warnings'].append(original.name+'：'+str(error))
        (output / "export-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill();process.wait()
        log.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sample", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    report = export_animations(args.sample, args.out, print)
    print(json.dumps(report, ensure_ascii=False, indent=2))
