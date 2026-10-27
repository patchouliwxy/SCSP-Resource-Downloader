"""Explicit song companion selection without weakening dependency reporting."""
from pathlib import PurePosixPath
import re


def mouth_candidates(entries, code):
    stem=code.split('_',1)[1]
    return [dict(id=e['id'],name=e['name'],size=e['size']) for e in entries
            if e['type']=='asset' and re.fullmatch(re.escape(stem)+r'_[a-z]+\.asset',PurePosixPath(e['name']).name.lower())
            and PurePosixPath(e['name']).stem.lower()!=stem+'_lmv']


def select_companions(entries, song, options):
    candidates=mouth_candidates(entries,song['code'])
    song={**song,'mouth_candidates':candidates}
    if options is None:
        return entries,song
    if not isinstance(options,dict) or set(options)-{'expression','camera','timeline','mouth_ids'}:
        raise ValueError('无效歌曲配套选项')
    for key in ('expression','camera','timeline'):
        if type(options.get(key,False)) is not bool:raise ValueError('歌曲配套选项应为布尔值')
    mouths=options.get('mouth_ids')
    automatic=mouths is None
    if automatic:mouths=[e['id'] for e in candidates]
    allowed={e['id'] for e in candidates}
    if not isinstance(mouths,list) or any(not isinstance(i,str) or i not in allowed for i in mouths):
        raise ValueError('口型选择不在当前歌曲候选列表中')
    roles=song['roles']
    def keep(entry):
        role=roles[entry['id']]
        return role in ('body','root') or role=='expression' and options.get('expression',False) or role in ('camera','camera_animation') and options.get('camera',False) or role in ('timeline','unit','sequence') and options.get('timeline',False) or role=='mouth_samples' and entry['id'] in mouths
    selected=[e for e in entries if keep(e)]
    song.update(roles={e['id']:roles[e['id']] for e in selected},mouth_required_ids=[] if automatic else list(dict.fromkeys(mouths)),
                selected_options=options,mouth_resource_count=len(mouths),mouth_selection='automatic' if automatic else 'explicit',
                missing_companions=[m for m in song['missing_companions'] if options.get('expression',False) or '_exp.json' not in m])
    return selected,song
