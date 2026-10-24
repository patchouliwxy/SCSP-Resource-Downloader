"""Export explicitly selected appearance Texture2Ds at original resolution."""
from pathlib import Path
import json
import re
import UnityPy
import scsp_download as core
from scsp_anim_export import digest


def export_textures(sample):
    sample=Path(sample)
    manifest=json.loads((sample/'manifest.json').read_text(encoding='utf-8'))
    selected=set(manifest['selected_ids'])
    entries=[e for e in manifest['entries'] if e['id'] in selected and e['type']=='png']
    if not entries:return []
    outputs={o['file']:o for o in manifest['outputs']}
    carriers=[]
    for item in manifest['outputs']:
        path=core.safe_output(sample,item['output'])
        if digest(path)!=item['sha256']:raise ValueError('贴图输入哈希不一致')
        decoded=path.read_bytes()
        if decoded[:8].startswith((b'UnityFS',b'UnityRaw',b'UnityWeb')):carriers.append(decoded)
    env=UnityPy.load(*carriers)
    textures={}
    for obj in env.objects:
        if obj.type.name in ('Texture2D','Sprite'):
            data=obj.read();textures.setdefault(data.m_Name.casefold(),[]).append(data)
    result=[]
    for entry in entries:
        name=Path(entry['name']).name
        candidates=textures.get(name.casefold(),[]) or textures.get(Path(name).stem.casefold(),[])
        if len(candidates)!=1:raise ValueError('所选贴图不存在或名称不唯一：'+name)
        owner=re.match(r'(\d{2})_(?:eye|face)',name,re.I)
        folder=sample/'models'/('head_'+owner[1] if owner else 'textures')
        folder.mkdir(parents=True,exist_ok=True)
        path=folder/name
        image=candidates[0].image
        if path.exists():
            from PIL import Image
            with Image.open(path) as existing:
                if existing.convert('RGBA').tobytes()!=image.convert('RGBA').tobytes() or existing.size!=image.size:
                    raise ValueError('同名贴图像素不同，拒绝覆盖：'+name)
            continue
        image.save(path,'PNG')
        result.append(dict(file=path.relative_to(sample).as_posix(),bytes=path.stat().st_size,sha256=digest(path),source=entry['id']))
    return result
