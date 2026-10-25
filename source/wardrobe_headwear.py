"""Resolve hairstyle-attached headwear from this version's explicit resource IDs."""
from copy import deepcopy
from collections import defaultdict
import re


def attach_headwear(data, entries):
    data = deepcopy(data)
    models = defaultdict(list)
    for entry in entries:
        if entry['type'] != 'prefab':
            continue
        match = re.fullmatch(r'm_acce_(\d+)_[a-z0-9]+_(\d+)_(\d+)\.prefab', entry['name'].rsplit('/', 1)[-1], re.I)
        if match:
            resource = int(match[1]) * 100 + int(match[2])
            models[(f'{int(match[3]):02d}', resource)].append({k: entry[k] for k in ('id', 'name', 'size', 'type')})
    # Drop our prior derived records/links so reloading and version updates are idempotent.
    records = [r for r in data.get('records', []) if r.get('derived_from') != 'hairstyle_headwear']
    heads = {}
    for hair in records:
        if hair['group'] != 'hair':
            continue
        hair.pop('attachments', None)
        refs = []
        for resource in dict.fromkeys(hair.get('linked_resources', [])):
            if not resource:
                continue
            identity = f'headwear-{hair["character"]}-{resource}'
            refs.append(identity)
            if identity not in heads:
                matches = [{**m, 'category': 'accessory'} for m in models[(hair['character'], resource)]]
                heads[identity] = dict(id=identity, display_id=resource, group='accessory', subtype='headwear',
                    character=hair['character'], resource=resource, kind=None, models=matches, textures=[],
                    asset_kind='model' if matches else 'unresolved', name=f'头饰 · {resource}',
                    icon=hair.get('icon', ''), icon_hash=hair.get('icon_hash', ''),
                    icon_basis='linked hairstyle thumbnail', source_hair_ids=[], derived_from='hairstyle_headwear',
                    mapping='exact hairstyle linked resource + character; not an independent accessory master row',
                    binding_warning='' if matches else '发型主表声明了附带头饰，但当前目录没有匹配到同角色模型。')
            heads[identity]['source_hair_ids'].append(hair['id'])
        hair['headwear_refs'] = refs
    records.extend(heads.values())
    by_key = {(r['group'], r['id']): r for r in records}
    for hair in records:
        if hair['group'] == 'hair':
            hair['attachments'] = [heads[i] for i in hair['headwear_refs']]
    for outfit in data.get('sets', []):
        parts = [p for p in outfit['parts'] if not str(p['id']).startswith('headwear-')]
        expanded = []
        seen = set()
        for part in parts:
            row = by_key.get((part['group'], part['id']))
            additions = [part]
            if row and row['group'] == 'hair':
                additions += [dict(group='accessory', id=i) for i in row['headwear_refs']]
            for item in additions:
                key = item['group'], item['id']
                if key not in seen:
                    expanded.append(item)
                    seen.add(key)
        outfit['parts'] = expanded
    data['records'] = records
    data.setdefault('counts', {})['headwear'] = len(heads)
    data['headwear_mapping_version'] = 1
    return data
