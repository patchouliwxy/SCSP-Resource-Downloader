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
    result=[]
    for entry in entries:
        item=outputs.get(entry['file'])
        if item is None:raise ValueError('所选贴图缺少下载文件：'+entry['name'])
        path=core.safe_output(sample,item['output'])
        if digest(path)!=item['sha256']:raise ValueError('贴图输入哈希不一致')
        # Resolve inside the selected bundle. Sprite and its source Texture2D
        # commonly share a name; the full-resolution texture takes priority.
        env=UnityPy.load(path.read_bytes())
        textures={'Texture2D':{},'Sprite':{}}
        for obj in env.objects:
            if obj.type.name in textures:
                data=obj.read()
                textures[obj.type.name].setdefault(data.m_Name.casefold(),[]).append(data)
        name=Path(entry['name']).name
        candidates=[]
        for kind in ('Texture2D','Sprite'):
            group=textures[kind]
            candidates=group.get(name.casefold(),[]) or group.get(Path(name).stem.casefold(),[])
            if candidates:break
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
