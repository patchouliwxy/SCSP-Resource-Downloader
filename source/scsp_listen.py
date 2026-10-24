"""Temporary, full-length WAV audition with original track names."""
import hashlib
import uuid
import shutil
from pathlib import Path
import scsp_download as core
from scsp_preview import Previews
from scsp_audio_export import export_audio


class Listens(Previews):
    def start(self, identity):
        entry = self.catalog.by_id.get(identity)
        if not entry or entry['type'] not in ('acb', 'awb'):
            raise core.DownloadError('请选择 ACB/AWB 音频包')
        entries, missing = core.resolve_dependencies(self.catalog.entries, [entry])
        if sum(e['size'] for e in entries) > 32 * 1048576:
            raise core.DownloadError('试听音频包超过32MiB')
        with self.lock:
            if sum(j['status'] in ('queued', 'running') for j in self.jobs.values()) >= 3:
                raise core.DownloadError('试听队列已满，请稍后再试')
            job = dict(key=uuid.uuid4().hex[:24], id=identity, name=entry['name'], status='queued', error='', missing=missing)
            self.jobs[job['key']] = job
            self.pool.submit(self.run, job, entries)
            return dict(job)

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
                relative = 'source/' + Path(entry['name']).name
                path = core.safe_output(folder, relative)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
                manifest['outputs'].append(dict(file=entry['file'], output=relative, sha256=hashlib.sha256(data).hexdigest()))
            core.write_json(folder / 'manifest.json', manifest)
            report = export_audio(folder)
            if not report['files']:
                raise ValueError('该音频包没有可试听音轨')
            shutil.rmtree(folder / 'source')
            with self.lock:
                job.update(status='completed', tracks=report['files'])
        except Exception as error:
            with self.lock:
                job.update(status='failed', error=str(error))
        finally:
            self.finish_released(job)
