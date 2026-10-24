"""Extract original vowel samples into SCSPMouthPlayer-compatible JSON."""
import argparse
import json
import math
import re
from pathlib import Path
from scsp_anim_export import digest


def export_mouth(sample, progress=lambda text: None):
    import UnityPy
    sample = Path(sample).resolve()
    manifest = json.loads((sample / 'manifest.json').read_text(encoding='utf-8'))
    entries = {e['file']: e for e in manifest['entries']}
    roles = manifest.get('song_selection', {}).get('roles', {})
    report = dict(files=[], source='original vowel samples', automatic_slot_assignment=False)
    for item in manifest['outputs']:
        entry = entries[item['file']]
        if entry['type'] != 'asset' or (roles.get(entry['id']) != 'mouth_samples' and not re.fullmatch(
                r'[a-z][a-z0-9]*_[a-z]+\.asset', Path(entry['name']).name.lower())):
            continue
        path = (sample / item['output']).resolve()
        if not path.is_relative_to(sample) or digest(path) != item['sha256']:
            raise ValueError('Mouth input path or hash mismatch')
        with path.open('rb') as stream:
            if not stream.read(8).startswith((b'UnityFS', b'UnityRaw', b'UnityWeb')):
                continue
        env = UnityPy.load(path.read_bytes())
        matched = 0
        for obj in env.objects:
            if obj.type.name != 'MonoBehaviour':
                continue
            tree = obj.read_typetree()
            rate, frames = tree.get('frameRate', 0), tree.get('datas')
            if not rate or not isinstance(frames, list) or not frames:
                continue
            if rate <= 0 or any(not all(isinstance(f.get(k), (int, float)) and math.isfinite(f[k])
                                       for k in ('a', 'i', 'u', 'e', 'o')) for f in frames):
                raise ValueError('Invalid vowel samples: ' + entry['name'])
            matched += 1
            name = Path(entry['name']).stem + (f'_{obj.path_id}' if matched > 1 else '') + '_mouth.json'
            target = sample / 'mouth' / name
            target.parent.mkdir(exist_ok=True)
            if target.exists():
                raise ValueError('不覆盖已有口型JSON：' + str(target))
            data = {k: tree[k] for k in ('frameRate', 'offsetFrame', 'datas')}
            progress('正在导出口型：' + entry['name'])
            target.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False), encoding='utf-8')
            assert json.loads(target.read_text(encoding='utf-8')) == data
            report['files'].append(dict(file=target.relative_to(sample).as_posix(), resource=entry['name'],
                frame_rate=rate, frames=len(frames), offset_frame=tree['offsetFrame'], sha256=digest(target)))
        if roles.get(entry['id']) == 'mouth_samples' and not matched:
            raise ValueError('所选口型资源未找到有效元音数据：' + entry['name'])
    if report['files']:
        (sample / 'mouth/export-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sample', type=Path)
    args = parser.parse_args()
    print(json.dumps(export_mouth(args.sample, print), ensure_ascii=False, indent=2))
