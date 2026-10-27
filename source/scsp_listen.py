"""Temporary, full-length WAV audition with original track names."""
import hashlib
import uuid
import shutil
import threading
from audio_companions import with_audio_pairs
from pathlib import Path
import scsp_download as core
from scsp_preview import Previews
from scsp_audio_export import export_audio


class Listens(Previews):
    def start(self, identity):
        entry = self.catalog.by_id.get(identity)
        if not entry or entry['type'] not in ('acb', 'awb'):
            raise core.DownloadError('请选择 ACB/AWB 音频包')
        entries, missing = core.resolve_dependencies(self.catalog.entries, with_audio_pairs(self.catalog.entries, [entry]))
        if sum(e['size'] for e in entries) > 256 * 1048576:
            raise core.DownloadError('试听音频包及配套文件超过256MiB')
        with self.lock:
            if sum(j['status'] in ('queued', 'running') for j in self.jobs.values()) >= 3:
                raise core.DownloadError('试听队列已满，请稍后再试')
            job = dict(key=uuid.uuid4().hex[:24], id=identity, name=entry['name'], status='queued', error='', missing=missing)
            job['decode_lock']=threading.Lock()
            self.jobs[job['key']] = job
            self.pool.submit(self.run, job, entries)
            return {k:v for k,v in job.items() if k!='decode_lock'}

    def run(self, job, entries):
        folder = self.root / job['key']
        try:
            with self.lock:
                if job.get('released'):
                    return
                job['status'] = 'running'
            manifest = dict(entries=entries, outputs=[], game_version=self.catalog.data['game_version'], resource_version=self.catalog.data['resource_version'])
            for entry in entries:
                data = core.decode_asset(entry, core.get_file(entry, self.cache))
                relative = 'source/' + entry['name']
                path = core.safe_output(folder, relative)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
                manifest['outputs'].append(dict(file=entry['file'], output=relative, sha256=hashlib.sha256(data).hexdigest()))
            core.write_json(folder / 'manifest.json', manifest)
            report = export_audio(folder,preview=True)
            if not report['files']:
                raise ValueError('该音频包没有可试听音轨')
            # Source sidecars are needed for lazy track decoding until the dialog closes.
            with self.lock:
                job.update(status='completed', tracks=report['tracks'],ready_tracks=[t['track'] for t in report['files']])
        except Exception as error:
            with self.lock:
                job.update(status='failed', error=str(error))
        finally:
            self.finish_released(job)

    def get(self,key):
        with self.lock:
            if key not in self.jobs: raise core.DownloadError('试听任务不存在')
            return {k:v for k,v in self.jobs[key].items() if k!='decode_lock'}

    def track_file(self,key,number):
        with self.lock:
            job=self.jobs.get(key)
            if not job or job.get('released') or job['status']!='completed': raise core.DownloadError('试听任务不存在或尚未就绪')
            track=next((t for t in job['tracks'] if t['track']==number),None)
            if not track: raise core.DownloadError('音轨编号不存在')
            lock=job['decode_lock']
        with lock:
            path=core.safe_output(self.root/key,track['file'])
            if not path.is_file():
                report=export_audio(self.root/key,preview=True,track_numbers=[number])
                if not report['files']: raise core.DownloadError('此音轨无法解码')
                with self.lock:
                    job.setdefault('ready_tracks',[]).append(number)
            return path

    def release(self,key):
        with self.lock: job=self.jobs.get(key)
        if job and 'decode_lock' in job:
            with job['decode_lock']: return super().release(key)
        return super().release(key)
