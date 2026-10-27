"""On-demand, original-resolution texture previews; generated files expire on close."""
from pathlib import Path
import io
import uuid

import scsp_download as core
from scsp_preview import Previews


def texture_image(payload, name):
    from PIL import Image
    if payload.startswith((b'\x89PNG', b'\xff\xd8', b'RIFF')):
        im = Image.open(io.BytesIO(payload))
        if im.width * im.height > 64_000_000:
            raise ValueError('图片超过6400万像素预览上限')
        return im.convert('RGBA')
    import UnityPy
    groups = {'Texture2D': [], 'Sprite': []}
    stem = Path(name).stem.casefold()
    for obj in UnityPy.load(payload).objects:
        if obj.type.name in groups:
            data = obj.read()
            if data.m_Name.casefold() in (name.casefold(), stem):
                groups[obj.type.name].append(data)
    candidates = groups['Texture2D'] or groups['Sprite']
    if len(candidates) != 1:
        raise ValueError('贴图不存在或有多个同类型同名对象：' + name)
    data = candidates[0]
    if getattr(data, 'm_Width', 0) * getattr(data, 'm_Height', 0) > 64_000_000:
        raise ValueError('图片超过6400万像素预览上限')
    return data.image.convert('RGBA')


class ImagePreviews(Previews):
    def start(self, identity):
        entry = self.catalog.by_id.get(identity)
        if not entry or entry['type'] not in ('png', 'jpg', 'jpeg'):
            raise core.DownloadError('请选择图片贴图资源')
        if entry['size'] > 64 * 1048576:
            raise core.DownloadError('图片资源超过64MiB预览上限')
        with self.lock:
            if sum(j['status'] in ('queued', 'running') for j in self.jobs.values()) >= 3:
                raise core.DownloadError('图片预览队列已满，请稍后重试')
            job = dict(key=uuid.uuid4().hex[:24], id=identity, name=entry['name'], status='queued', error='')
            self.jobs[job['key']] = job
            self.pool.submit(self.run, job, entry)
            return dict(job)

    def run(self, job, entry):
        try:
            with self.lock:
                if job.get('released'): return
                job['status'] = 'running'
            payload = core.decode_asset(entry, core.get_file(entry, self.cache))
            image = texture_image(payload, Path(entry['name']).name)
            folder = self.root / job['key']
            folder.mkdir()
            target = folder / 'image.png'
            image.save(target, 'PNG')
            with self.lock:
                job.update(status='completed', width=image.width, height=image.height,
                           bytes=target.stat().st_size, alpha=image.getchannel('A').getextrema()[0] < 255)
        except Exception as error:
            with self.lock: job.update(status='failed', error=str(error))
        finally:
            self.finish_released(job)
