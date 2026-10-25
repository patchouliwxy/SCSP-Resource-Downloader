"""Build version-scoped wardrobe records from bounded official MasterData tables."""
from pathlib import Path
import json
import re
import struct
from collections import defaultdict

import scsp_download as core
from appearance_resources import appearance_textures
from wardrobe_headwear import attach_headwear

from runtime_paths import app_root
ROOT = app_root()


class Reader:
    def __init__(self, data, pos):
        self.data, self.pos = data, pos

    def unpack(self, fmt):
        value = struct.unpack_from('<' + fmt, self.data, self.pos)
        self.pos += struct.calcsize('<' + fmt)
        return value

    def integer(self):
        return self.unpack('i')[0]

    def array(self):
        size = self.integer()
        if not 0 <= size <= 100:
            raise ValueError('Unsupported wardrobe array size')
        return list(self.unpack('i' * size)) if size else []


def table(data, expected, header, parser):
    ids = {int(k) for k in expected}
    first = min(ids)
    signature = struct.pack('<iB', len(ids), header) + struct.pack('<i', first)
    positions = [m.start() for m in re.finditer(re.escape(signature), data)]
    valid = []
    for pos in positions:
        reader = Reader(data, pos + 4)
        rows = {}
        try:
            for _ in range(len(ids)):
                if reader.unpack('B')[0] != header:
                    raise ValueError('Wardrobe table layout changed')
                row = parser(reader)
                if row['id'] in rows:
                    raise ValueError('Duplicate wardrobe record')
                rows[row['id']] = row
            if set(rows) == ids:
                valid.append(rows)
        except (ValueError, struct.error):
            continue
    if len(valid) != 1:
        raise ValueError('换装主表布局或名称覆盖改变，拒绝发布不可靠配对')
    return valid[0]


def costume(r):
    identity, character, kind, resource = r.unpack('iiii')
    flag = r.unpack('B')[0];r.unpack('q');r.array();flags = r.unpack('BB')
    if flag not in (0, 1) or any(f not in (0, 1) for f in flags):
        raise ValueError('Invalid costume flags')
    return dict(id=identity, character=character, kind=kind, resource=resource)


def hair(r):
    identity, character, kind, resource = r.unpack('iiii')
    linked_resources = r.array()
    if r.unpack('B')[0] not in (0, 1):
        raise ValueError('Invalid hairstyle flag')
    return dict(id=identity, character=character, kind=kind, resource=resource, linked_resources=linked_resources)


def accessory(r):
    identity, character, category, kind, resource = r.unpack('iiiii')
    if r.unpack('B')[0] not in (0, 1):
        raise ValueError('Invalid accessory flag')
    return dict(id=identity, character=character, category=category, kind=kind, resource=resource)


def costume_set(r):
    identity, dress_id, hair_id = r.unpack('iii')
    accessories = r.array();r.integer();r.array()
    return dict(id=identity, dress_id=dress_id, hair_id=hair_id, accessory_ids=accessories)


def build(index, texts, master):
    texts = {name: {str(k): v for k, v in values.items()} for name, values in texts.items()}
    dresses = table(master, texts['mlCostume_UnlockPremise'], 9, costume)
    hairs = table(master, texts['mlHairstyle_UnlockPremise'], 6, hair)
    accessories = table(master, texts['mlAccessory_UnlockPremise'], 6, accessory)
    sets = table(master, texts['mlCostumeSet_Name'], 6, costume_set)
    entries = index['entries']
    prefabs = [e for e in entries if e['type'] == 'prefab']
    model_lookup = defaultdict(list)
    hair_variants = defaultdict(list)
    appearance_prefabs = defaultdict(list)
    for e in prefabs:
        name = e['name'].rsplit('/', 1)[-1]
        dress = re.fullmatch(r'm_dress_(\d+)_[a-z0-9]+_\d+\.prefab', name, re.I)
        hair_match = re.fullmatch(r'm_hair_(\d+)_(\d+)_\d+\.prefab', name, re.I)
        acc_match = re.fullmatch(r'm_acce_(\d+)_[a-z0-9]+_(\d+)_(\d+)\.prefab', name, re.I)
        appearance_match = re.fullmatch(r'm_acce_(\d+)_[a-z0-9]+_(all|make|paint|l\d+|r\d+|00)_(\d+)\.prefab',name,re.I)
        row = dict(id=e['id'], name=e['name'], size=e['size'], type='prefab')
        if dress:
            model_lookup[('dress', int(dress[1]))].append({**row, 'category': 'dress'})
        if hair_match:
            model_lookup[('hair', int(hair_match[1]), int(hair_match[2]))].append({**row, 'category': 'hair'})
            variant = int(name.rsplit('_',1)[-1].split('.')[0])
            hair_variants[(int(hair_match[1]),variant)].append({**row,'category':'hair'})
        if acc_match:
            model_lookup[('accessory', int(acc_match[1])*100+int(acc_match[2]), int(acc_match[3]))].append({**row, 'category': 'accessory'})
        if appearance_match:
            appearance_prefabs[(int(appearance_match[1]),appearance_match[2].lower(),int(appearance_match[3]))].append(e)
    icons = {e['name'].rsplit('/', 1)[-1]: e['id'] for e in entries if e['type'] == 'png'}
    icon_hashes = {e['id']: e['file'] for e in entries if e['type']=='png'}
    texture_names = defaultdict(list)
    entry_names = defaultdict(list)
    for e in entries:
        entry_names[e['name']].append(e)
        if e['type']=='png':
            texture_names[e['name'].rsplit('/',1)[-1]].append(dict(id=e['id'],name=e['name'],size=e['size'],type='png',category='texture'))
    characters = texts['mlCharacterText_Name']
    records = []
    for group, rows, icon_type in (('dress', dresses, 24), ('hair', hairs, 25), ('accessory', accessories, 26)):
        for row in rows.values():
            if str(row['character']) not in characters:
                raise ValueError('换装主表出现未知角色')
            resource, character = row['resource'], row['character']
            style = resource//10 if resource >= 10 else resource
            key = ('dress', resource) if group == 'dress' else (group, character, style) if group == 'hair' else (group, resource, character)
            matches = model_lookup[key]
            if group=='hair' and resource>=40000:
                matches=hair_variants[(character,resource)]
            textures=[]
            carriers=[]
            materials=[]
            binding_warning=''
            if group=='accessory':
                textures=appearance_textures(row,texture_names)
                if row['kind'] in (3,4,5):
                    variant=resource%100
                    tokens=({'1':['all','00'],'2':['make'],'3':['paint']}.get(str(variant),['00','all']) if row['kind']==3 else ['l1','l2'] if row['kind']==4 else ['r1','r2'])
                    for token in tokens:
                        carriers.extend(appearance_prefabs[(resource//100,token,character)])
                    if not carriers:
                        other=[e for (num,token,owner),values in appearance_prefabs.items() if num==resource//100 and token in tokens for e in values]
                        if len(other)==1:
                            carriers=other
                            binding_warning='主表引用的资源编号仅匹配到其他角色的素材；保留实际文件，不自动替换。'
                    bound={}
                    for carrier in carriers:
                        for dep in carrier['dependencies']:
                            for target in entry_names.get(dep,[]):
                                if target['type']=='png':
                                    bound[target['id']]=dict(id=target['id'],name=target['name'],size=target['size'],type='png',category='texture')
                                if target['type']=='mat':
                                    materials.append(dict(id=target['id'],name=target['name']))
                    if carriers:
                        textures=list(bound.values())
                        matches=[]  # These face/eye carriers share the base head geometry.
            records.append({**row, 'group': group, 'character': f'{character:02d}', 'models': matches,
                            'textures':textures,
                            'asset_kind':'model' if matches else 'texture' if textures else 'unresolved',
                            'appearance_prefabs':[dict(id=e['id'],name=e['name']) for e in carriers],
                            'materials':materials,
                            'binding_warning':binding_warning,
                            'evidence':'appearance prefab dependency list' if carriers else 'catalog texture filename' if textures else 'no carrier matched',
                            'subtype': {1:'glasses',2:'earring',3:'makeup',4:'eye_l',5:'eye_r',6:'teeth'}.get(row['kind'],'other') if group=='accessory' else '',
                            'icon': icons.get(f'product_icon_{icon_type}_{row["id"]:07d}.png', ''),
                            'mapping': 'resource id + character + variation from official MasterData; unmatched preserved'})
    by_key = {(r['group'], r['id']): r for r in records}
    result_sets = []
    for row in sets.values():
        parts = [('dress', row['dress_id']), ('hair', row['hair_id'])] + [('accessory', a) for a in row['accessory_ids'] if a]
        if any(p not in by_key for p in parts):
            raise ValueError('套装引用不存在的换装部件')
        chars = {by_key[p]['character'] for p in parts}
        if len(chars) != 1:
            raise ValueError('套装角色引用不一致')
        result_sets.append({**row, 'character': next(iter(chars)), 'name': texts['mlCostumeSet_Name'][str(row['id'])],
                            'description': texts['mlCostumeSet_Description'].get(str(row['id']), ''),
                            'parts': [dict(group=g, id=i) for g, i in parts]})
    for row in records:
        row['icon_hash'] = icon_hashes.get(row['icon'], '')
    return attach_headwear(dict(game_version=index['game_version'], resource_version=index['resource_version'],
                source='official MasterData wardrobe tables + localization + product icons',
                schema=1, records=records, sets=result_sets,
                counts=dict(dresses=len(dresses), hairs=len(hairs), accessories=len(accessories), sets=len(sets)),
                note='No account ownership inferred. Missing model/thumbnail bindings remain visible.'), entries)


if __name__ == '__main__':
    index = json.loads((ROOT / 'official-current-index.json').read_text(encoding='utf-8'))
    texts = json.loads((ROOT / 'song-names-source/localizetext.json').read_text(encoding='utf-8'))
    master = (ROOT / 'song-names-source/raw/root/raw/masterdata.bytes').read_bytes()
    report = build(index, texts, master)
    core.write_json(ROOT / 'wardrobe-data.json', report)
    print(report['counts'])
    for group in ('dress', 'hair', 'accessory'):
        rows = [r for r in report['records'] if r['group'] == group]
        print(group, 'models', sum(bool(r['models']) for r in rows), '/', len(rows), 'icons', sum(bool(r['icon']) for r in rows))
