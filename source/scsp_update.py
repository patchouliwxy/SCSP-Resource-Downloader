"""Repeatable official catalog/name/formation update with validation and rollback."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import urllib.error
import urllib.request
import uuid

import build_character_data
import build_song_names
import build_wardrobe
import scsp_download as core

from runtime_paths import app_root
ROOT = app_root()
PUBLISHED = ('official-current-index.json', 'song-names.json', 'character-data.json',
             'wardrobe-data.json',
             'docs/角色编号与歌曲默认编队.md', 'update-report.json',
             'song-names-source/localizetext.json',
             'song-names-source/raw/root/raw/localizetext.bytes',
             'song-names-source/raw/root/raw/masterdata.bytes')


def console_version(text):
    matches = re.findall(r'Plugin Loaded - Game Version:\s*([\d.]+), Resource Version:\s*(\d{8}@[A-Za-z0-9+/=]+)', text)
    if not matches:
        raise ValueError('未找到Plugin Loaded版本行；需要完整资源版本的@后编码。')
    return matches[-1]


def validate(index, songs, characters):
    version = (index['game_version'], index['resource_version'])
    for report in (songs, characters):
        if (report['game_version'], report['resource_version']) != version:
            raise ValueError('生成文件版本不一致，停止发布')
    families = core.discover_songs(index['entries'])
    if not families:
        raise ValueError('没有识别到歌曲动作文件族，需检查新版本布局')
    for song in families:
        code = song['code']
        if not songs['songs'].get(code, {}).get('title'):
            raise ValueError(f'{code}未匹配到主表场景代码和官方歌名；可能需要适配新主表布局')
        lineup = characters['formations'].get(code, {}).get('members', [])
        if not lineup or any(not m['name'] for m in lineup):
            raise ValueError(f'{code}默认编队缺失或有未知角色，停止发布')
        if any(slot > len(lineup) for slot in song['slots']):
            raise ValueError(f'{code}动作编号超过默认编队人数，不能自动认定角色')
    for entry in index['entries']:
        match = re.fullmatch(r'm_head_(\d+)\.prefab', core.PurePosixPath(entry['name']).name)
        if match and f'{int(match[1]):02}' not in characters['characters']:
            raise ValueError('头部编号没有官方姓名：' + entry['name'])
    return len(families)


def publish(stage, root=ROOT):
    """Back up old files, atomically replace each file, roll back on any failure."""
    backup = stage.parent / 'backup'
    for name in PUBLISHED:
        target = root / name
        if target.is_file():
            saved = backup / name
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, saved)
    changed = []
    try:
        for name in PUBLISHED:
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(target.name + '.update-part')
            shutil.copy2(stage / name, temporary)
            changed.append(name)
            temporary.replace(target)
    except Exception:
        for name in reversed(changed):
            target, saved = root / name, backup / name
            if saved.is_file():
                shutil.copy2(saved, target)
            else:
                target.unlink(missing_ok=True)
        for name in PUBLISHED:
            target = root / name
            target.with_name(target.name + '.update-part').unlink(missing_ok=True)
        raise


def reload_backend(port=8765):
    base = f'http://127.0.0.1:{port}'
    try:
        req = urllib.request.Request(base + '/api/reload', data=b'{}',
            headers={'Content-Type': 'application/json', 'X-SCSP-Client': '1'})
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.load(response)
        print('后端已重载：', result, flush=True)
        return True
    except urllib.error.HTTPError as error:
        message = error.read().decode('utf-8', errors='replace')
        print(f'数据已生成；后端暂未重载（HTTP {error.code}）：{message}', flush=True)
    except OSError:
        print('数据已生成；后端未运行或不可访问。运行 Start-Web.ps1 即可加载。', flush=True)
    return False


def update(game_version, resource_version, root=ROOT):
    # Validate input before any network call.
    core.root_manifest(game_version, resource_version)
    root = Path(root).resolve()
    run = root / 'updates' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8])
    stage = run / 'staging'
    stage.mkdir(parents=True)
    print('更新记录：' + str(run), flush=True)
    report = dict(game_version=game_version, resource_version=resource_version,
                  status='building', official_live_latest_verified=False,
                  version_source='user game console/version arguments', run_directory=str(run))
    try:
        index = core.build_index(game_version, resource_version, root / '.scsp-cache')
        index.update(source_kind='official_catalog', version_source=report['version_source'],
                     official_live_latest_verified=False)
        # Preserve previously verified SHA-256 only for this exact version.
        prior_path = root / 'official-current-index.json'
        verified = {}
        if prior_path.is_file():
            prior = json.loads(prior_path.read_text(encoding='utf-8'))
            if (prior['game_version'], prior['resource_version']) == (game_version, resource_version):
                verified = {e['file']: e for e in prior['entries'] if e.get('sha256')}
        for entry in index['entries']:
            old = verified.get(entry['file'])
            if old and old['size'] == entry['size']:
                entry['sha256'] = old['sha256']
        index['sha256_covered_entries'] = sum(bool(e.get('sha256')) for e in index['entries'])
        core.write_json(stage / 'official-current-index.json', index)
        sources = []
        raw = stage / 'song-names-source/raw/root/raw'
        raw.mkdir(parents=True)
        for name in ('localizetext.bytes', 'masterdata.bytes'):
            candidates = [e for e in index['entries'] if e['id'] == 'root/raw/' + name]
            if len(candidates) != 1:
                raise ValueError('官方文本/主表资源缺失或不唯一：' + name)
            entry = candidates[0]
            data = core.decode_asset(entry, core.get_file(entry, root / '.scsp-cache'))
            (raw / name).write_bytes(data)
            sources.append(dict(id=entry['id'], bytes=len(data), decoded_sha256=hashlib.sha256(data).hexdigest()))
        tables = build_song_names.read_text_tables((raw / 'localizetext.bytes').read_bytes())
        core.write_json(stage / 'song-names-source/localizetext.json', tables)
        songs = build_song_names.build(index, tables, (raw / 'masterdata.bytes').read_bytes())
        core.write_json(stage / 'song-names.json', songs)
        characters = build_character_data.build(stage, root / '.scsp-cache')
        wardrobe = build_wardrobe.build(index, tables, (raw / 'masterdata.bytes').read_bytes())
        core.write_json(stage / 'wardrobe-data.json', wardrobe)
        count = validate(index, songs, characters)
        report.update(status='validated', entries=len(index['entries']), songs=count,
                      characters=len(characters['characters']), sources=sources,
                      wardrobe_counts=wardrobe['counts'],
                      sha256_covered_entries=index['sha256_covered_entries'],
                      name_layout='MstSong 23 fields; UTF-16 localizetext dictionary',
                      formation_basis='unitIdolData array order; runtime roles not verified')
        core.write_json(stage / 'update-report.json', report)
        publish(stage, root)
        report['status'] = 'published'
        core.write_json(run / 'result.json', report)
        print(f'已发布：{len(index["entries"]):,}条资源 / {count}个动作文件族 / {len(characters["characters"])}个角色', flush=True)
        print(f'SHA-256覆盖：{index["sha256_covered_entries"]}/{len(index["entries"])}；未覆盖项仅校验下载大小。', flush=True)
        return report
    except Exception as error:
        report.update(status='failed', error=str(error))
        core.write_json(run / 'result.json', report)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game-version')
    parser.add_argument('--resource-version')
    parser.add_argument('--console-log', type=Path)
    parser.add_argument('--reload-only', action='store_true')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    if args.reload_only:
        return 0 if reload_backend(args.port) else 2
    version = (args.game_version, args.resource_version)
    if args.console_log:
        from_log = console_version(args.console_log.read_text(encoding='utf-8-sig'))
        if any(version) and version != from_log:
            parser.error('参数版本与控制台日志版本不一致')
        version = from_log
    if not all(version):
        parser.error('指定 --console-log，或同时提供 --game-version 和 --resource-version')
    lock = ROOT / '.update.lock'
    try:
        with lock.open('x', encoding='utf-8') as handle:
            handle.write(json.dumps(dict(game_version=version[0], resource_version=version[1])))
    except FileExistsError:
        parser.error('已有更新任务或上次异常退出的锁文件；确认无更新任务后移除 .update.lock')
    try:
        update(*version)
        reload_backend(args.port)
        print('刷新浏览器即可查看新目录。', flush=True)
        return 0
    except Exception as error:
        print('更新失败，旧索引保留：' + str(error), file=sys.stderr)
        return 1
    finally:
        lock.unlink(missing_ok=True)


if __name__ == '__main__':
    raise SystemExit(main())
