"""Export selected character prefabs as FBX plus textures with bundled AssetStudioMod."""
from pathlib import Path
import argparse
import json
import re
import subprocess
import shutil

import scsp_download as core
from scsp_anim_export import digest

from runtime_paths import app_root
ROOT = app_root()
STUDIO = ROOT / 'tools/AssetStudioMod/cli/AssetStudioModCLI_net472_win32_64/AssetStudioModCLI.exe'


def is_model(entry):
    return entry['type'] == 'prefab' and entry['name'].rsplit('/',1)[-1].lower().startswith(('m_head_', 'm_hair_', 'm_dress_', 'm_acce_'))


def model_folder(name):
    stem = Path(name).stem
    label = stem[8:] if stem.lower().startswith('m_dress_') else stem[2:]
    if not re.fullmatch(r'[a-zA-Z0-9_-]+', label):
        raise ValueError('模型编号包含不支持的字符：' + name)
    return label


def export_models(sample, progress=lambda text: None):
    sample = Path(sample).resolve()
    manifest = json.loads((sample / 'manifest.json').read_text(encoding='utf-8'))
    selected = set(manifest['selected_ids'])
    models = [e for e in manifest['entries'] if e['id'] in selected and is_model(e)]
    report = dict(exporter='AssetStudioMod CLI 0.19.0.0', models=[], files=[],
                  unity_import_verified=False, model_playback_verified=False,
                  animation_mode='skip', scale_factor=1)
    if not models:
        return report
    if not STUDIO.is_file():
        raise RuntimeError('缺少内置 AssetStudioMod CLI，无法导出 FBX')
    for item in manifest['outputs']:
        path = core.safe_output(sample, item['output'])
        if digest(path) != item['sha256']:
            raise ValueError('模型导出输入哈希不一致：' + item['output'])
    output = sample / 'models'
    if output.exists():
        raise ValueError('不覆盖已有 models 目录，请使用新的下载任务目录')
    output.mkdir()
    work = sample / 'model-export-work'
    work.mkdir(exist_ok=True)
    for index, entry in enumerate(models, 1):
        name = Path(entry['name']).stem
        # Output identities are controlled, not resource names interpreted as paths.
        folder = work / f'{index:03d}'
        target_folder = output / model_folder(entry['name'])
        if target_folder.exists():
            raise ValueError('模型编号重复：' + entry['name'])
        progress('正在导出 FBX 和贴图：' + entry['name'])
        with (work / f'{index:03d}.log').open('wb') as log:
            result = subprocess.run([str(STUDIO), str(sample / 'bundles'), '-m', 'splitObjects',
                                     '--filter-by-name', '(?i)^' + re.escape(name) + '$',
                                     '--filter-with-regex', '--fbx-animation', 'skip',
                                     '--fbx-scale-factor', '1', '--max-export-tasks', '1',
                                     '-o', str(folder), '--log-level', 'warning'],
                                    cwd=work, stdout=log, stderr=subprocess.STDOUT,
                                    timeout=900, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        fbxs = sorted(folder.rglob('*.fbx'))
        if result.returncode or not fbxs:
            raise RuntimeError(f'{entry["name"]} FBX 导出失败，详见 model-export-work/{index:03d}.log')
        for path in fbxs:
            with path.open('rb') as source:
                if source.read(23) != b'Kaydara FBX Binary  \x00\x1a\x00':
                    raise RuntimeError('导出的 FBX 头无效：' + path.name)
        target_folder.mkdir()
        exported = []
        for path in sorted(folder.rglob('*')):
            if not path.is_file() or path.suffix.lower() not in ('.fbx', '.png'):
                continue
            target = target_folder / path.name
            if target.exists():
                if digest(target) != digest(path):
                    raise RuntimeError('模型导出存在同名不同文件：' + path.name)
                continue
            shutil.copy2(path, target)
            if target.suffix.lower() == '.fbx':
                exported.append(target)
        report['models'].append(dict(resource=entry['id'], name=entry['name'],
                                     fbxs=[p.relative_to(sample).as_posix() for p in exported]))
    report['files'] = [dict(file=p.relative_to(sample).as_posix(), bytes=p.stat().st_size, sha256=digest(p))
                       for p in sorted(output.rglob('*')) if p.is_file()]
    core.write_json(output / 'export-report.json', report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sample', type=Path)
    args = parser.parse_args()
    print(json.dumps(export_models(args.sample, print), ensure_ascii=False, indent=2))
