"""Recover scene assets and references; never claim to reconstruct game logic or shaders."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import socket
import subprocess
import time
import urllib.parse
import urllib.request
from collections import Counter
from scsp_anim_export import RIPPER, digest


def has_scene(manifest):
    selected = set(manifest['selected_ids'])
    return any(e['id'] in selected and e['type'] == 'unity' for e in manifest['entries'])


def verified_bundles(sample, manifest):
    paths = []
    for item in manifest['outputs']:
        path = (sample / item['output']).resolve()
        if not path.is_relative_to(sample):
            raise ValueError('Scene input escapes download directory')
        if digest(path) != item['sha256']:
            raise ValueError('Decoded input hash mismatch: ' + item['output'])
        with path.open('rb') as source:
            magic = source.read(8)
        if magic.startswith((b'UnityFS', b'UnityRaw', b'UnityWeb')):
            paths.append(path)
    if not paths:
        raise RuntimeError('场景没有可用的 Unity 资源包')
    return paths


def finalize_project(sample, exported):
    assets = exported / 'ExportedProject/Assets'
    scenes = sorted(assets.rglob('*.unity'))
    if not scenes:
        raise RuntimeError('未恢复出 .unity 场景；原始资源和日志保留，不把附带 anim 当作场景。')
    target = sample / 'scene-project'
    if target.exists():
        raise ValueError('不覆盖已有场景导出：' + str(target))
    # Recovered script declarations are evidence, not executable game implementations.
    # Keep them outside Assets so they cannot introduce thousands of compile errors.
    blocked = {'.cs', '.asmdef', '.asmref', '.dll', '.rsp'}
    for source in sorted(assets.rglob('*')):
        if not source.is_file():
            continue
        relative = source.relative_to(assets)
        base = source.with_suffix('') if source.suffix == '.meta' else source
        evidence = 'Scripts' in relative.parts or base.suffix.lower() in blocked
        destination = target / ('RecoveryEvidence' if evidence else 'Assets') / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    settings = target / 'ProjectSettings'
    settings.mkdir(parents=True)
    version = exported / 'ExportedProject/ProjectSettings/ProjectVersion.txt'
    if version.is_file():
        shutil.copy2(version, settings / version.name)
    # Only include engine modules, no network package installs or recovered game assemblies.
    packages = target / 'Packages'
    packages.mkdir()
    (packages / 'manifest.json').write_text(json.dumps({'dependencies': {
        'com.unity.modules.animation': '1.0.0', 'com.unity.modules.audio': '1.0.0',
        'com.unity.modules.particlesystem': '1.0.0', 'com.unity.modules.physics': '1.0.0',
        'com.unity.modules.director': '1.0.0', 'com.unity.modules.video': '1.0.0',
        'com.unity.modules.imgui': '1.0.0', 'com.unity.modules.imageconversion': '1.0.0'}}), encoding='utf-8')
    counts = Counter(p.suffix for p in (target / 'Assets').rglob('*') if p.is_file())
    manifest = json.loads((sample / 'manifest.json').read_text('utf-8'))
    report = dict(exporter='AssetRipper 2.0.0', scenes=[(target / 'Assets' / p.relative_to(assets)).relative_to(sample).as_posix() for p in scenes],
                  asset_counts=dict(counts), dependency_complete=manifest['dependency_complete'],
                  unresolved_dependencies=manifest['unresolved_dependencies'],
                  source_editor_version=version.read_text('utf-8').strip() if version.is_file() else 'unknown',
                  scripts_restored=False, shaders_restored=False, unity_import_verified=False,
                  game_playback_verified=False)
    (target / 'scene-export-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    (target / '使用说明.txt').write_text(
        'SCSP 场景资源恢复\n\n'
        '1. Unity Hub → 添加项目 → 从磁盘添加，选择此 scene-project 文件夹。\n'
        '2. 优先使用 ProjectSettings/ProjectVersion.txt 指定的 Unity 版本。旧 Unity 向下兼容未保证。\n'
        '3. 打开 Assets 中的 .unity 场景；不要把 bundles/*.unity3d 改名成 .unity。\n'
        '4. 也可将整个 Assets 连同 .meta 导入单独测试工程；只复制 .unity 会丢失引用。\n\n'
        '恢复范围：场景层级、网格、材质参数、纹理、依赖中可导出的动画与时间线。\n'
        '未恢复游戏脚本执行、Shader 源码及完整演出控制。RecoveryEvidence 是脚本声明证据，不能放回 Assets 当作游戏源码。\n'
        'Missing Script、Timeline 脚本缺失、Shader 占位/黑屏/粉色仍需适配；这不是开箱即玩的游戏工程。\n'
        '需要查看基础外观时，可自行替换为对应渲染管线的基础材质。动态舞台效果需要另行适配。\n'
        '附带 .anim 是舞台特效等动画，不是场景；依赖是否完整请看 scene-export-report.json 和上级 manifest.json。\n', encoding='utf-8-sig')
    report['files'] = [dict(file=p.relative_to(sample).as_posix(), bytes=p.stat().st_size)
                       for p in sorted(target.rglob('*')) if p.is_file()]
    return report


def export_scenes(sample, progress=lambda text: None):
    sample = Path(sample).resolve()
    manifest = json.loads((sample / 'manifest.json').read_text('utf-8'))
    if not has_scene(manifest):
        return {'scenes': [], 'files': []}
    paths = verified_bundles(sample, manifest)
    if not RIPPER.is_file():
        raise RuntimeError('未找到 AssetRipper，无法恢复场景')
    if (sample / 'scene-project').exists():
        raise ValueError('不覆盖已有场景导出')
    work = sample / 'scene-export-work'
    work.mkdir(parents=True, exist_ok=True)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    with (work / 'process.log').open('wb') as log:
        process = subprocess.Popen([str(RIPPER), '--port', str(port), '--headless', '--log-path', str(work / 'assetripper.log')],
                                   cwd=RIPPER.parent, stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        base = f'http://127.0.0.1:{port}'
        try:
            deadline = time.monotonic() + 60
            while True:
                try:
                    urllib.request.urlopen(base, timeout=2).close(); break
                except OSError:
                    if process.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError('AssetRipper 启动失败，见场景导出日志')
                    time.sleep(.2)
            progress(f'正在恢复场景及 {len(paths)} 个依赖包（含网格、材质、贴图）')
            urllib.request.urlopen(urllib.request.Request(base + '/LoadFile', data=urllib.parse.urlencode([('Path', str(p)) for p in paths]).encode()), timeout=900).close()
            exported = work / 'export'
            urllib.request.urlopen(urllib.request.Request(base + '/Export/UnityProject', data=urllib.parse.urlencode({'Path': str(exported)}).encode()), timeout=900).close()
            return finalize_project(sample, exported)
        finally:
            process.terminate()
            try: process.wait(timeout=10)
            except subprocess.TimeoutExpired: process.kill(); process.wait()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sample', type=Path)
    args = parser.parse_args()
    result = export_scenes(args.sample, print)
    print(json.dumps({k:v for k,v in result.items() if k!='files'}, ensure_ascii=False, indent=2))
