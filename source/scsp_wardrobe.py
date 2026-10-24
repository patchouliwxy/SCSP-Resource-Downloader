"""Version-bound wardrobe browsing and on-demand official icon extraction."""
import json
from pathlib import Path
import threading
from collections import Counter

import scsp_download as core

CATEGORY_LABELS = {'glasses':'眼镜','earring':'耳饰','makeup':'妆容','eye_l':'左眼 / 瞳孔','eye_r':'右眼 / 瞳孔','teeth':'牙饰','other':'其他饰品'}


class Wardrobe:
    def __init__(self, catalog, path):
        self.catalog = catalog
        self.data = json.loads(Path(path).read_text(encoding='utf-8')) if Path(path).is_file() else {}
        if (self.data.get('game_version'), self.data.get('resource_version')) != (catalog.data['game_version'], catalog.data['resource_version']):
            self.data = {}
        self.records = self.data.get('records', [])
        self.by_key = {(r['group'], r['id']): r for r in self.records}

    def metadata(self):
        return dict(available=bool(self.data), version=self.data.get('game_version'), counts=self.data.get('counts', {}),
                    characters=[dict(id=k, name=v, count=sum(r['character']==k for r in self.records))
                                for k,v in self.catalog.character_names.items() if any(r['character']==k for r in self.records)],
                    accessory_categories=[dict(id=k, label=v) for k,v in CATEGORY_LABELS.items()])

    def search(self, character='12', group='dress', category='', query='', page=1):
        if group not in ('dress','hair','accessory','set'):
            raise ValueError('无效换装类别')
        rows = self.data.get('sets', []) if group == 'set' else [r for r in self.records if r['group']==group]
        rows = [r for r in rows if r['character']==character and (not category or r.get('subtype')==category)
                and query.casefold() in (str(r['id'])+' '+r.get('name','')+' '+ ' '.join(m['name'] for m in r.get('models',[]))).casefold()]
        rows = sorted(rows, key=lambda r:r['id'], reverse=True)
        result=[]
        for row in rows[(max(page,1)-1)*24:max(page,1)*24]:
            if group == 'set':
                parts=[self.by_key[(p['group'],p['id'])] for p in row['parts']]
                result.append({**row,'components':parts, 'icon':next((p['icon'] for p in parts if p['group']=='dress'),''),
                               'icon_hash':next((p.get('icon_hash','') for p in parts if p['group']=='dress'),''),
                               'missing':sum(not p['models'] and not p.get('textures') for p in parts)})
            else:
                result.append(row)
        return dict(items=result, total=len(rows), page=max(page,1), page_size=24)


class Thumbnails:
    def __init__(self, catalog, root, cache):
        self.catalog, self.root, self.cache = catalog, Path(root), Path(cache)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.limit = threading.Semaphore(4)
        self.locks = {}
        self.lookup_catalog = catalog
        self.lookup = core.dependency_lookup(catalog.entries)

    def get(self, identity):
        entry = self.catalog.by_id.get(identity)
        name = entry['name'].rsplit('/',1)[-1] if entry else ''
        if not name.startswith(('product_icon_24_', 'product_icon_25_', 'product_icon_26_')) or entry['type']!='png':
            raise ValueError('不是换装缩略图资源')
        path = core.safe_output(self.root, entry['file']+'.png')
        if path.is_file():
            return path
        with self.lock:
            if self.lookup_catalog is not self.catalog:
                self.lookup = core.dependency_lookup(self.catalog.entries)
                self.lookup_catalog = self.catalog
            lookup = self.lookup
            mutex = self.locks.setdefault(entry['file'],threading.Lock())
        with mutex, self.limit:
            if path.is_file():
                return path
            import UnityPy
            entries, missing = core.resolve_dependencies(self.catalog.entries,[entry], lookup)
            if sum(e['size'] for e in entries)>8*1048576 or missing:
                raise ValueError('缩略图依赖缺项或超过8MiB')
            env=UnityPy.load(*[core.decode_asset(e,core.get_file(e,self.cache)) for e in entries])
            candidates=[o for o in env.objects if o.type.name in ('Sprite','Texture2D')]
            candidates.sort(key=lambda o:o.type.name!='Sprite')
            for obj in candidates:
                data=obj.read()
                if data.m_Name.casefold() not in (name.casefold(),Path(name).stem.casefold()):
                    continue
                img=data.image;img.thumbnail((320,320));img.save(path,'PNG')
                # Bound generated thumbnail storage. Original verified cache remains reusable.
                files=sorted(self.root.glob('*.png'),key=lambda p:p.stat().st_mtime)
                total=sum(p.stat().st_size for p in files)
                for old in files:
                    if total<=64*1048576:break
                    if old!=path:
                        total-=old.stat().st_size;old.unlink(missing_ok=True)
                return path
            raise ValueError('包中未找到对应换装图片')
