"""Build Japanese character names and default song formations from official metadata."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path

import scsp_download as core

from runtime_paths import app_root
ROOT = app_root()


def build(root=ROOT, cache=None):
    root = Path(root).resolve()
    cache = Path(cache) if cache else root / ".scsp-cache"
    index = json.loads((root / 'official-current-index.json').read_text(encoding='utf-8'))
    texts = json.loads((root / 'song-names-source/localizetext.json').read_text(encoding='utf-8'))
    characters = {f'{int(k):02}': v.replace('\u00a0', ' ') for k, v in texts['mlCharacterText_Name'].items()}
    lookup = {e['name']: e for e in index['entries']}
    songs = core.discover_songs(index['entries'])
    output = root / 'character-data-source'
    output.mkdir(exist_ok=True)
    entries = [lookup[s['code'] + '_unit.json'] for s in songs if s['code'] + '_unit.json' in lookup]
    print(f'Default formation metadata: {len(entries)} files, {sum(e["size"] for e in entries)} bytes', flush=True)

    def download(entry):
        data = core.decode_asset(entry, core.get_file(entry, cache))
        (output / entry['name']).write_bytes(data)
        unit = json.loads(data)
        if not isinstance(unit.get('unitIdolData'), list):
            raise ValueError('Unsupported formation layout: ' + entry['name'])
        members = []
        for position, member in enumerate(unit['unitIdolData'], 1):
            identity = member['chara_id']
            members.append(dict(position=position, character_id=identity,
                name=characters.get(f'{identity:02}', ''), cloth_id=member.get('cloth_id'),
                hair_id=member.get('hair_id'), accessory_ids=member.get('accessory_ids', [])))
        return entry['name'][:-10], dict(source=entry['id'], source_sha256=hashlib.sha256(data).hexdigest(),
            position_basis='unitIdolData array order (1-based)', members=members)

    with ThreadPoolExecutor(max_workers=6) as pool:
        formations = dict(pool.map(download, entries))
    report = dict(game_version=index['game_version'], resource_version=index['resource_version'],
        name_source='official localizetext.bytes: mlCharacterText_Name',
        characters=characters, formations=formations,
        note='Default formation order only; runtime reassignment and physical stage placement are not inferred.')
    core.write_json(root / 'character-data.json', report)
    heads = sorted({core.PurePosixPath(e['name']).name[7:9] for e in index['entries']
        if e['type'] == 'prefab' and core.PurePosixPath(e['name']).name.startswith('m_head_')})
    lines = ['# 角色编号与日文原名', '', '来源：当前官方文本表；默认编队顺序来自各歌曲unitIdolData数组。', '',
             '| 编号 | 日文原名 | 头部prefab |', '|---|---|---|']
    lines += [f'| {identity} | {name} | {"有" if identity in heads else "未匹配"} |'
              for identity, name in sorted(characters.items())]
    lines += ['', '## 歌曲默认编队', '', '位置按unitIdolData数组从1编号；不等于角色编号，也不推断左右空间位置。', '']
    titles = json.loads((root / 'song-names.json').read_text(encoding='utf-8'))['songs']
    for code, formation in sorted(formations.items()):
        lines += [f'### {titles.get(code, {}).get("title", code)}（{code}）', '',
                  '、'.join(f'{m["position"]}：{m["name"] or "未知角色"}（{m["character_id"]:02}）'
                           for m in formation['members']), '']
    (root / 'docs').mkdir(exist_ok=True)
    (root / 'docs/角色编号与歌曲默认编队.md').write_text('\n'.join(lines), encoding='utf-8')
    print(f'Built {len(characters)} character names and {len(formations)} default formations', flush=True)
    return report


if __name__ == '__main__':
    build()
