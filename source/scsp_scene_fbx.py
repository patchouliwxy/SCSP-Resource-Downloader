"""Single FBX per selected scene, using its roots rather than dependency prefabs."""
import json
from pathlib import Path
import re
import shutil
import subprocess

import scsp_download as core
from scsp_model_export import STUDIO
from scsp_scene_export import has_scene, verified_bundles
from scsp_anim_export import digest


def export_scene_fbx(sample, progress=lambda text: None):
    sample = Path(sample).resolve()
    manifest = json.loads((sample/'manifest.json').read_text('utf-8'))
    report = dict(format='fbx', exporter='SCSPSceneFbx + bundled AssetStudioMod',
        scenes=[], files=[], geometry=[], warnings=[], dependency_complete=manifest['dependency_complete'],
        unresolved_dependencies=manifest['unresolved_dependencies'],
        hierarchy_preserved=True, animations_exported=False, shaders_restored=False,
        game_playback_verified=False, unity_import_verified=False)
    if not has_scene(manifest):
        return report
    paths = verified_bundles(sample, manifest)
    tool = STUDIO.with_name('SCSPSceneFbx.exe')
    if not tool.is_file():
        raise RuntimeError('缺少内置场景 FBX 导出器，请更新完整下载器目录')
    target = sample/'scene-fbx'
    if target.exists():
        raise ValueError('不覆盖已有 scene-fbx 目录')
    selected = set(manifest['selected_ids'])
    scenes = [e for e in manifest['entries'] if e['id'] in selected and e['type']=='unity']
    used = set()
    for n, entry in enumerate(scenes, 1):
        name = Path(entry['name']).stem
        if not re.fullmatch(r'[A-Za-z0-9_-]+', name) or name.casefold() in used:
            raise ValueError('场景导出文件名不安全或重复：'+entry['name'])
        used.add(name.casefold())
        source = [o for o in manifest['outputs'] if o['file']==entry['file']]
        if len(source)!=1:
            raise ValueError('所选场景输入缺失或不唯一：'+entry['id'])
        scene_input = core.safe_output(sample, source[0]['output'])
        if scene_input not in paths:
            raise ValueError('所选场景不是已校验 Unity 资源包')
        work = sample/'scene-fbx-work'/f'{n:03d}'
        work.mkdir(parents=True, exist_ok=True)
        raw = work/'export'
        request = work/'request.json'
        core.write_json(request, dict(inputs=[str(p) for p in paths],
            scene_input=str(scene_input), name=name, output=str(raw)))
        progress('正在导出场景单文件 FBX 和贴图：'+entry['name'])
        with (work/'process.log').open('wb') as log:
            result = subprocess.run([str(tool), str(request)], cwd=tool.parent,
                stdout=log, stderr=subprocess.STDOUT, timeout=900,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        fbxs = list(raw.glob('*.fbx'))
        if result.returncode or len(fbxs)!=1:
            raise RuntimeError('场景 FBX 导出失败，原始包与日志保留：'+str(work))
        with fbxs[0].open('rb') as stream:
            if stream.read(23)!=b'Kaydara FBX Binary  \x00\x1a\x00':
                raise RuntimeError('场景 FBX 文件头无效')
        geometry = json.loads((raw/'geometry-report.json').read_text('utf-8'))
        if geometry.get('meshes',0)<=0:
            raise RuntimeError('场景没有导出可用网格')
        missing = geometry.get('source_mesh_renderers',0)-geometry['meshes']
        if missing>0:
            report['warnings'].append(f'{entry["name"]}：{missing} 个网格节点未转换，详见 export-report.json')
        destination = target/name
        destination.mkdir(parents=True)
        for f in sorted(raw.rglob('*')):
            if f.is_file() and f.suffix.lower() in ('.fbx','.png'):
                out = destination/f.relative_to(raw)
                out.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(f,out)
        report['scenes'].append((destination/fbxs[0].name).relative_to(sample).as_posix())
        report['geometry'].append(dict(resource=entry['id'],name=entry['name'],**geometry))
    core.write_json(target/'export-report.json', report)
    report['files'] = [dict(file=p.relative_to(sample).as_posix(),bytes=p.stat().st_size,sha256=digest(p))
        for p in sorted(target.rglob('*')) if p.is_file()]
    return report
