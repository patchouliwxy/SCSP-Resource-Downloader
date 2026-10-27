"""Exact ACB/AWB sidecar pairing; never guess among duplicate catalog names."""
from collections import defaultdict


def with_audio_pairs(entries, selected):
    names=defaultdict(list)
    for entry in entries:
        if entry['type'] in ('acb','awb'):names[entry['name'].casefold()].append(entry)
    result={e['id']:e for e in selected}
    for entry in selected:
        if entry['type'] not in ('acb','awb'):continue
        extension='.awb' if entry['type']=='acb' else '.acb'
        name=entry['name'][:-4]+extension
        candidates=names[name.casefold()]
        if len(candidates)>1:raise ValueError('配套音频资源存在歧义：'+name)
        if candidates:result[candidates[0]['id']]=candidates[0]
    return list(result.values())
