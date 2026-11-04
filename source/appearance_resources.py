"""Locate source appearance PNGs, preserving role and exact filename evidence."""

def appearance_textures(row, names):
    kind, resource, character = row['kind'], row['resource'], row['character']
    if kind not in (3,4,5):
        return []
    number=resource//100-(90000 if kind==3 else 80000)
    # 1000-series generic preset images use their short number in texture names.
    numbers=[number]
    if 1000<=number<1100:
        numbers.append(number-1000)
    variant=resource%100
    roles=['make','paint'] if variant in (0,1) else ['make'] if variant==2 else ['paint'] if variant==3 else ['make','paint']
    for number in numbers:
        found={}
        for owner in (f'{int(character):02d}','00'):
            for token in dict.fromkeys((f'{number:02d}',f'{number:04d}',str(number))):
                if kind==3:
                    candidates=[f'{owner}_face_{token}_{role}{suffix}.png' for role in roles for suffix in ('_col','')]
                else:
                    side='_l' if kind==4 else '_r'
                    candidates=[f'{owner}_eye{s}_{token}_{suffix}.png' for s in (side,'') for suffix in ('col','high','plx','blm')]
                for name in candidates:
                    for entry in names.get(name,[]):
                        found[entry['id']]=entry
        if found:
            return list(found.values())
    return []


def attach_makeup_models(data, entries):
    """Keep exact-character makeup prefabs available; geometry is checked at export.

    A shared face mesh is still geometry. Dependency PNGs cannot establish that
    the prefab is texture-only. Run for both newly built and saved catalogs.
    """
    data = correct_makeup_cross_references(data, entries)
    by_id = {e['id']: e for e in entries}
    rows = []
    for original in data.get('records', []):
        if original.get('group') != 'accessory' or original.get('kind') != 3:
            rows.append(original)
            continue
        row = dict(original)
        models = {m['id']: m for m in row.get('models', [])}
        for carrier in row.get('appearance_prefabs', []):
            entry = by_id.get(carrier['id'])
            if not entry or entry.get('type') != 'prefab':
                continue
            name = entry['name'].rsplit('/', 1)[-1]
            # A cross-character fallback must not become a default mesh choice.
            if not name.lower().startswith('m_acce_') or name.rsplit('_', 1)[-1].lower() != f"{int(row['character']):02d}.prefab":
                continue
            models[entry['id']] = dict(id=entry['id'], name=entry['name'],
                                      size=entry['size'], type='prefab', category='accessory')
        row['models'] = list(models.values())
        if models:
            row['asset_kind'] = 'model'
            row['geometry_status'] = 'checked_at_export'
        rows.append(row)
    return {**data, 'records': rows}


def correct_makeup_cross_references(data, entries):
    """Repair reciprocal cross-character references backed by unanimous set data.

    Original MasterData resource values remain untouched. No character IDs,
    costume IDs, or version-specific overrides are embedded in this rule.
    """
    import re
    by_key = {(r['group'], r['id']): r for r in data.get('records', [])}
    by_id = {e['id']: e for e in entries}
    by_name = {}
    carriers = {}
    for e in entries:
        by_name.setdefault(e['name'], []).append(e)
        if e.get('type') != 'prefab':
            continue
        match = re.fullmatch(r'm_acce_(\d+)_[a-z0-9]+_(all|make|paint|00)_(\d+)\.prefab', e['name'].rsplit('/', 1)[-1], re.I)
        if match:
            carriers.setdefault((int(match[1]), match[2].lower(), int(match[3])), []).append(e)

    proposals = {}
    for row in data.get('records', []):
        if row.get('group') != 'accessory' or row.get('kind') != 3 or not row.get('appearance_prefabs'):
            continue
        owner = int(row['character'])
        # Only consider genuine cross-character references; ordinary choices stay intact.
        source = [by_id.get(c['id']) for c in row['appearance_prefabs']]
        if any(not e for e in source):
            continue
        source_owners = []
        for e in source:
            match = re.search(r'_(\d+)\.prefab$', e['name'], re.I)
            if match:
                source_owners.append(int(match[1]))
        if len(source_owners) != len(source) or owner in source_owners:
            continue
        evidence = []
        invalid = False
        for outfit in data.get('sets', []):
            parts = outfit.get('parts', [])
            if not any(p['group'] == 'accessory' and p['id'] == row['id'] for p in parts):
                continue
            dress_keys = [(p['group'], p['id']) for p in parts if p['group'] == 'dress']
            if len(dress_keys) != 1 or int(outfit['character']) != owner:
                invalid = True
                break
            dress = by_key.get(dress_keys[0])
            if not dress or int(dress['character']) != owner:
                invalid = True
                break
            numbers = {int(m[1]) for model in dress.get('models', [])
                       if (m := re.fullmatch(r'm_dress_(\d+)_[a-z0-9]+_\d+\.prefab', model['name'].rsplit('/', 1)[-1], re.I))}
            if len(numbers) != 1 or int(dress['resource']) not in numbers:
                invalid = True
                break
            number = next(iter(numbers))
            if not 0 <= number < 10000:
                invalid = True
                break
            support = []
            for p in parts:
                part = by_key.get((p['group'], p['id']))
                if (part and part.get('group') == 'accessory' and part.get('kind') in (1, 2, 6)
                        and int(part['character']) == owner and part['resource'] // 100 % 10000 == number
                        and part.get('models')):
                    support.append(part['id'])
            if not support:
                invalid = True
                break
            evidence.append(dict(set_id=outfit['id'], dress_id=dress['id'], costume_number=number, supporting_accessory_ids=support))
        if invalid or not evidence or len({e['costume_number'] for e in evidence}) != 1:
            continue
        variant = row['resource'] % 100
        tokens = {0: ['00', 'all'], 1: ['all', '00'], 2: ['make'], 3: ['paint']}.get(variant)
        if tokens is None:
            continue
        number = 90000 + evidence[0]['costume_number']
        candidates = {e['id']: e for token in tokens for e in carriers.get((number, token, owner), [])}
        if len(candidates) != 1:
            continue
        proposals[row['id']] = dict(row=row, resolved=number * 100 + variant,
                                    carrier=next(iter(candidates.values())), evidence=evidence,
                                    source_owners=source_owners)

    changed = {}
    for identity, proposal in proposals.items():
        row = proposal['row']
        partners = [p for other, p in proposals.items() if other != identity
                    and p['row']['resource'] == proposal['resolved'] and p['resolved'] == row['resource']
                    and int(p['row']['character']) in proposal['source_owners']
                    and int(row['character']) in p['source_owners']]
        if len(partners) != 1:
            continue
        carrier = proposal['carrier']
        textures, materials = {}, {}
        for name in carrier.get('dependencies', []):
            for e in by_name.get(name, []):
                if e['type'] == 'png':
                    textures[e['id']] = dict(id=e['id'], name=e['name'], size=e['size'], type='png', category='texture')
                elif e['type'] == 'mat':
                    materials[e['id']] = dict(id=e['id'], name=e['name'])
        if not textures:
            continue
        changed[identity] = {**row, 'models': [], 'appearance_prefabs': [dict(id=carrier['id'], name=carrier['name'])],
                            'textures': list(textures.values()), 'materials': list(materials.values()),
                            'binding_warning': '', 'evidence': 'reciprocal cross-reference + unanimous costume-set evidence + prefab dependencies',
                            'resolved_resource': proposal['resolved'],
                            'appearance_correction': dict(rule='reciprocal_cross_character_set_match',
                                original_resource=row['resource'], resolved_resource=proposal['resolved'],
                                original_prefabs=row['appearance_prefabs'], original_textures=row.get('textures', []),
                                original_materials=row.get('materials', []), source_version=data.get('resource_version'),
                                reciprocal_record_id=partners[0]['row']['id'], set_evidence=proposal['evidence'])}
    return {**data, 'records': [changed.get(r['id'], r) if r.get('group') == 'accessory' else r for r in data.get('records', [])]}
