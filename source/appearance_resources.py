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
