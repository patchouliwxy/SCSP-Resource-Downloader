"""On-demand static GLB previews from verified Unity bundles."""
import hashlib
import io
import json
from pathlib import Path
import shutil
import struct
import threading
import uuid
import os
import stat
from concurrent.futures import ThreadPoolExecutor

import scsp_download as core


def build_glb(paths, output):
    import numpy as np
    import UnityPy
    from UnityPy.helpers.MeshHelper import MeshHandler

    env = UnityPy.Environment()
    selected_renderers = set()
    for index, path in enumerate(paths):
        env.load_file(path.read_bytes())
        if index == 0:
            selected_renderers = {(o.assets_file.name, o.path_id) for o in env.objects
                if o.type.name in ('SkinnedMeshRenderer', 'MeshRenderer')}
    binary = bytearray()
    gltf = dict(asset={'version': '2.0', 'generator': 'SCSP static preview 1'},
                extensionsUsed=['KHR_materials_unlit'], scene=0, scenes=[{'nodes': []}],
                nodes=[], meshes=[], materials=[], textures=[], images=[], samplers=[{'wrapS': 10497, 'wrapT': 10497}],
                bufferViews=[], accessors=[], buffers=[])
    materials, textures = {}, {}
    warnings = []

    def view(data, target=None):
        while len(binary) % 4:
            binary.append(0)
        item = dict(buffer=0, byteOffset=len(binary), byteLength=len(data))
        if target:
            item['target'] = target
        binary.extend(data)
        gltf['bufferViews'].append(item)
        return len(gltf['bufferViews']) - 1

    def accessor(array, kind, component=5126, bounds=False):
        item = dict(bufferView=view(array.tobytes(), 34963 if kind == 'SCALAR' else 34962),
                    componentType=component, count=len(array), type=kind)
        if bounds:
            item.update(min=array.min(axis=0).tolist(), max=array.max(axis=0).tolist())
        gltf['accessors'].append(item)
        return len(gltf['accessors']) - 1

    def material(pointer):
        key = (pointer.assetsfile.name, pointer.m_FileID, pointer.m_PathID)
        if key in materials:
            return materials[key]
        record = dict(name='Default', doubleSided=True, extensions={'KHR_materials_unlit': {}},
                      pbrMetallicRoughness=dict(baseColorFactor=[.78, .78, .82, 1], metallicFactor=0, roughnessFactor=1))
        try:
            data = pointer.deref().read()
            record['name'] = data.m_Name
            texenvs = dict(data.m_SavedProperties.m_TexEnvs)
            texture = next((texenvs[n].m_Texture for n in ('_MainTex', '_IrisTex', '_BaseMap', '_ColorTex', '_BaseTex')
                            if n in texenvs and texenvs[n].m_Texture.m_PathID), None)
            if texture:
                obj = texture.deref()
                texture_key = (obj.assets_file.name, obj.path_id)
                if texture_key not in textures:
                    image = obj.read().image
                    if '_IrisTex' in texenvs and texture == texenvs['_IrisTex'].m_Texture:
                        from PIL import Image
                        base = Image.new('RGBA', image.size, (255, 255, 255, 255))
                        base.alpha_composite(image.convert('RGBA'))
                        image = base
                    image.thumbnail((1024, 1024))
                    buffer = io.BytesIO()
                    image.save(buffer, format='PNG')
                    gltf['images'].append(dict(bufferView=view(buffer.getvalue()), mimeType='image/png'))
                    textures[texture_key] = len(gltf['textures'])
                    gltf['textures'].append(dict(source=len(gltf['images']) - 1, sampler=0))
                record['pbrMetallicRoughness'].update(baseColorFactor=[1, 1, 1, 1],
                    baseColorTexture={'index': textures[texture_key]})
                record.update(alphaMode='MASK', alphaCutoff=.3)
        except Exception as error:
            warnings.append('材质使用默认外观：' + str(error)[:200])
        materials[key] = len(gltf['materials'])
        gltf['materials'].append(record)
        return materials[key]

    vertex_count = 0
    transform_cache = {}

    def world_matrix(transform):
        key = (transform.object_reader.assets_file.name, transform.object_reader.path_id)
        if key in transform_cache:
            return transform_cache[key]
        p, q, scale = transform.m_LocalPosition, transform.m_LocalRotation, transform.m_LocalScale
        x, y, z, w = q.x, q.y, q.z, q.w
        rotation = np.array([[1-2*y*y-2*z*z, 2*x*y-2*z*w, 2*x*z+2*y*w],
                             [2*x*y+2*z*w, 1-2*x*x-2*z*z, 2*y*z-2*x*w],
                             [2*x*z-2*y*w, 2*y*z+2*x*w, 1-2*x*x-2*y*y]])
        matrix = np.eye(4)
        matrix[:3, :3] = rotation @ np.diag([scale.x, scale.y, scale.z])
        matrix[:3, 3] = [p.x, p.y, p.z]
        if transform.m_Father.m_PathID:
            matrix = world_matrix(transform.m_Father.deref().read()) @ matrix
        transform_cache[key] = matrix
        return matrix

    for obj in env.objects:
        if obj.type.name not in ('SkinnedMeshRenderer', 'MeshRenderer'):
            continue
        if selected_renderers and (obj.assets_file.name, obj.path_id) not in selected_renderers:
            continue  # Dependency FBXs are not additional instances of the selected prefab.
        renderer = obj.read()
        go = renderer.m_GameObject.deref().read()
        if go.m_Name.lower().endswith('_shadow') or '_hole' in go.m_Name.lower() or go.m_Name == 'face_close':
            continue  # These depend on game-only stencil/shadow or alternate face passes.
        if (not renderer.m_Enabled or not go.m_IsActive) and go.m_Name != 'face':
            continue
        if obj.type.name == 'MeshRenderer':
            filters = [p.component.deref().read() for p in go.m_Component if p.component.deref().type.name == 'MeshFilter']
            if not filters:
                continue
            mesh = filters[0].m_Mesh.deref().read()
        else:
            mesh = renderer.m_Mesh.deref().read()
        handler = MeshHandler(mesh)
        handler.process()
        vertices = np.array(handler.m_Vertices, dtype='<f4')[:, :3].copy()
        if not len(vertices) or not np.isfinite(vertices).all():
            raise ValueError('Invalid mesh positions')
        matrix = None
        if obj.type.name == 'MeshRenderer':
            transform = next(p.component.deref().read() for p in go.m_Component if p.component.deref().type.name == 'Transform')
            matrix = world_matrix(transform)
            vertices = (np.column_stack((vertices, np.ones(len(vertices)))) @ matrix.T)[:, :3].astype('<f4')
        vertices[:, 0] *= -1
        attributes = {'POSITION': accessor(vertices, 'VEC3', bounds=True)}
        if handler.m_Normals:
            normals = np.array(handler.m_Normals, dtype='<f4')[:, :3].copy()
            if matrix is not None:
                normals = (normals @ np.linalg.inv(matrix[:3, :3])).astype('<f4')
            normals[:, 0] *= -1
            attributes['NORMAL'] = accessor(normals, 'VEC3')
        if handler.m_UV0:
            uv = np.array(handler.m_UV0, dtype='<f4')[:, :2].copy()
            uv[:, 1] = 1 - uv[:, 1]
            attributes['TEXCOORD_0'] = accessor(uv, 'VEC2')
        primitives = []
        for index, triangles in enumerate(handler.get_triangles()):
            indices = np.array(triangles, dtype='<u4').reshape(-1, 3)[:, [0, 2, 1]].copy().reshape(-1)
            if not len(indices):
                continue
            if indices.max() >= len(vertices):
                raise ValueError('Mesh index out of range')
            primitive = dict(attributes=attributes, indices=accessor(indices, 'SCALAR', 5125))
            if renderer.m_Materials:
                primitive['material'] = material(renderer.m_Materials[min(index, len(renderer.m_Materials) - 1)])
            primitives.append(primitive)
        if primitives:
            gltf['meshes'].append(dict(name=mesh.m_Name, primitives=primitives))
            gltf['nodes'].append(dict(mesh=len(gltf['meshes']) - 1, name=go.m_Name))
            gltf['scenes'][0]['nodes'].append(len(gltf['nodes']) - 1)
            vertex_count += len(vertices)
    if not gltf['meshes']:
        raise ValueError('资源中没有可预览的网格')
    gltf['buffers'] = [{'byteLength': len(binary)}]
    text = json.dumps(gltf, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()
    text += b' ' * (-len(text) % 4)
    binary += b'\0' * (-len(binary) % 4)
    glb = struct.pack('<4sII', b'glTF', 2, 12 + 8 + len(text) + 8 + len(binary))
    glb += struct.pack('<I4s', len(text), b'JSON') + text + struct.pack('<I4s', len(binary), b'BIN\0') + binary
    output.write_bytes(glb)
    return dict(meshes=len(gltf['meshes']), vertices=vertex_count, textures=len(gltf['textures']), warnings=warnings,
                bytes=len(glb), pose='static bind pose; original game shader and physics are not reproduced')


class Previews:
    def __init__(self, catalog, root, cache):
        self.catalog, self.root, self.cache = catalog, Path(root).resolve(), Path(cache)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.jobs = {}

    def start(self, identity):
        entry = self.catalog.by_id.get(identity)
        if not entry or not entry['name'].lower().startswith(('m_head_', 'm_hair_', 'm_dress_', 'm_acce_')) or entry['type'] != 'prefab':
            raise core.DownloadError('该资源暂不支持模型部件预览')
        planned, missing = core.resolve_dependencies(self.catalog.entries, [entry])
        if sum(e['size'] for e in planned) > 64 * 1048576:
            raise core.DownloadError('预览依赖超过64MiB，请先按需下载并检查资源')
        key = uuid.uuid4().hex[:24]
        with self.lock:
            if sum(j['status'] in ('queued', 'running') for j in self.jobs.values()) >= 3:
                raise core.DownloadError('预览队列已满，请稍后再试')
            job = dict(key=key, id=identity, name=entry['name'], status='queued', error='', missing=missing)
            self.jobs[key] = job
            self.pool.submit(self.run, job, planned)
            return dict(job)

    def get(self, key):
        with self.lock:
            if key not in self.jobs:
                raise core.DownloadError('预览任务不存在')
            return dict(self.jobs[key])

    def cleanup_folder(self, key):
        import re
        if not re.fullmatch(r'[a-f0-9]{24}', key):
            raise core.DownloadError('无效预览编号')
        folder = self.root / key
        if not folder.resolve().is_relative_to(self.root) or folder.is_symlink():
            raise core.DownloadError('预览目录包含链接，拒绝清理')
        if folder.exists():
            for current, dirs, files in os.walk(folder, followlinks=False):
                for name in dirs + files:
                    path = Path(current) / name
                    if path.is_symlink() or getattr(path.lstat(), 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                        raise core.DownloadError('预览内部包含链接，拒绝清理')
            shutil.rmtree(folder)

    def cleanup_stale(self):
        import re
        for folder in self.root.iterdir():
            if re.fullmatch(r'[a-f0-9]{24}', folder.name) and folder.name not in self.jobs:
                self.cleanup_folder(folder.name)

    def release(self, key):
        with self.lock:
            job = self.jobs.get(key)
            if not job:
                return {'released': True}
            job['released'] = True
            if job['status'] in ('completed', 'failed'):
                self.cleanup_folder(key)
                del self.jobs[key]
            return {'released': True}

    def finish_released(self, job):
        with self.lock:
            if job.get('released'):
                self.cleanup_folder(job['key'])
                self.jobs.pop(job['key'], None)

    def run(self, job, entries):
        folder = self.root / job['key']
        work = folder / '_work'
        try:
            with self.lock:
                if job.get('released'):
                    return
                job['status'] = 'running'
            work.mkdir(parents=True, exist_ok=True)
            paths = []
            for entry in {e['file']: e for e in entries}.values():
                decoded = core.decode_asset(entry, core.get_file(entry, self.cache))
                if decoded.startswith((b'UnityFS', b'UnityRaw', b'UnityWeb')):
                    path = work / (entry['file'] + '.unity3d')
                    path.write_bytes(decoded)
                    paths.append(path)
            report = build_glb(paths, folder / 'model.glb')
            with self.lock:
                job.update(status='completed', **report)
                core.write_json(folder / 'preview.json', job)
        except Exception as error:
            with self.lock:
                job.update(status='failed', error=str(error))
        finally:
            # Only generated decoded copies; original verified cache is retained.
            if work.exists() and work.resolve().is_relative_to(self.root) and not work.is_symlink():
                try:
                    shutil.rmtree(work)
                except OSError:
                    pass
            self.finish_released(job)
