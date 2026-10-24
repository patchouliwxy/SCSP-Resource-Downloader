"""Display reliable official song titles; never invent names for numbered assets."""
from pathlib import PurePosixPath
import re


def scene_names(entries, classifications, songs):
    result = {}
    usage = {}
    for e in entries:
        if e['type'] != 'unity':
            continue
        stem = PurePosixPath(e['name']).stem.lower()
        lesson = re.fullmatch(r'(\d{3}_[a-z0-9]+)_dancelesson',stem)
        code = lesson[1] if lesson else stem
        song = songs.get(code, {})
        if not song.get('title'):
            continue
        title = song['title']
        result[e['id']] = dict(display_name=title+(' · ダンスレッスン' if lesson else ''),
            scene_title=title, scene_title_kind='official_song_title',
            scene_title_basis='同版本官方 MstSong + mlMusic_Name；场景资源代码精确对应',
            scene_song_code=code)
        if not lesson:
            for dep in e['dependencies']:
                usage.setdefault(dep.rsplit('/',1)[-1].casefold(), {})[code]=title
    for e in entries:
        if classifications[e['id']]['category'] not in ('stage_model','background_model'):
            continue
        related = usage.get(e['name'].rsplit('/',1)[-1].casefold(),{})
        if related:
            result[e['id']] = dict(related_song_titles=list(related.values()),
                scene_title_kind='dependency_usage',
                scene_title_basis='同版本 MV 场景目录声明的直接依赖；不是模型官方名称')
    office_scenes={'dioramabackground_0001_0101','dioramabackground_0001_0201','dioramabackground_0001_0301'}
    for e in entries:
        stem=PurePosixPath(e['name']).stem.lower()
        deps={d.rsplit('/',1)[-1].lower() for d in e['dependencies']}
        confirmed={'office_living.fbx','office_kitchen.fbx','office_pdesk.fbx'}<=deps
        if e['type']=='unity' and confirmed:
            row=result.setdefault(e['id'],{})
            row['scene_aliases']=['283事务所','283事務所','事务所','事務所','office']
            if stem in office_scenes:
                row.update(display_name='283事务所 · '+stem.rsplit('_',1)[-1],
                    scene_title_kind='verified_resource_alias',
                    scene_title_basis='事务所场景使用别名；目录依赖 office_living / office_kitchen / office_pdesk，非官方场景标题')
        if e['type'] in ('fbx','prefab') and stem.startswith('office_'):
            row=result.setdefault(e['id'],{})
            row['scene_aliases']=['283事务所','283事務所','事务所','事務所','office']
    return result
