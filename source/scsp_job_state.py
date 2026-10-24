"""Persistent same-task recovery; checkpoints are local hashes, not CDN proof."""
import hashlib
import json
from pathlib import Path
import shutil
import time
import uuid
import zipfile

import scsp_download as core

ACTIVE = {'queued','running','canceling','exporting','packaging'}
STAGES = {
    'scene':('scene-project','scene-fbx','scene-export-work','scene-fbx-work'),
    'animation':('animations','animation-export-work'),
    'model':('models','model-export-work'),
    'audio':('audio','audio-export-work'),
    'mouth':('mouth',),
}


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


class JobRecovery:
    def valid_inputs(self, output, plan):
        unique={e['file']:e for e in plan['entries']}
        found={}
        for item in plan.get('outputs',[]):
            if item.get('file') not in unique or item['file'] in found:continue
            path=core.safe_output(output,item['output'])
            if path.is_file() and sha(path)==item['sha256']:found[item['file']]=item
        return found

    def retry(self, identity, mode='resume'):
        if mode not in ('resume','export'):raise core.DownloadError('未知重试方式')
        with self.lock:
            job=self.jobs.get(identity)
            if not job:raise core.DownloadError('任务不存在')
            if job['status'] in ACTIVE:raise core.DownloadError('任务正在处理，不能重复启动')
            if mode=='resume' and job['status']=='completed':raise core.DownloadError('已完成任务可选择仅重新导出')
            if sum(j['status'] in ACTIVE for j in self.jobs.values())>=5:raise core.DownloadError('待处理任务已满')
            output,*_=self.task_paths(identity)
            self.storage_bytes(identity)  # Reject links before reading or archiving previous outputs.
            plan=json.loads((output/'manifest.json').read_text('utf-8'))
            if plan['selected_ids']!=job['selected_ids']:raise core.DownloadError('任务选择与原始清单不一致')
            if mode=='export' and len(self.valid_inputs(output,plan))!=len({e['file'] for e in plan['entries']}):
                raise core.DownloadError('原始输入缺失或校验失败；未完成任务可用“继续任务”，已清理原始输入的完成任务需从资源库重新提交')
            self.update(job,status='queued',error='',current='',phase='queued',
                        retry_mode=mode,attempt=int(job.get('attempt',1))+1,stored_bytes=None,
                        scene_count=0,model_count=0,animation_count=0,audio_count=0,mouth_count=0,
                        scene_files=[],model_files=[],animation_files=[],audio_files=[],mouth_files=[],scene_warnings=[])
            self.pool.submit(self.run,job,plan)
            return dict(job)

    def checkpoint_valid(self, output, checkpoint):
        try:
            return isinstance(checkpoint.get('report'),dict) and all(
                (p:=core.safe_output(output,item['file'])).is_file() and sha(p)==item['sha256']
                for item in checkpoint['files'])
        except (OSError,ValueError,KeyError):return False

    def preserve(self, job, names):
        output,*_=self.task_paths(job['id'])
        self.storage_bytes(job['id'])
        existing=[output/name for name in names if (output/name).exists()]
        if existing:
            history=output/'history'/f'{int(job.get("attempt",1)):03d}_{uuid.uuid4().hex[:8]}'
            history.mkdir(parents=True)
            for path in existing:
                path.rename(history/path.name)

    def stage(self, job, plan, name, label, action, index):
        output=self.output/job['id']
        self.update(job,phase='exporting',phase_label=label,phase_completed=index,
                    phase_total=5,current=label)
        checkpoints=plan.setdefault('export_checkpoints',{})
        checkpoint=checkpoints.get(name,{})
        if job.get('retry_mode')!='export' and self.checkpoint_valid(output,checkpoint):
            self.update(job,reused_stages=job.get('reused_stages',0)+1)
            return checkpoint['report']
        self.preserve(job,STAGES[name])
        report=action()
        files=[]
        for folder in STAGES[name]:
            if 'work' in folder:continue
            for p in sorted((output/folder).rglob('*')):
                if p.is_file():
                    safe=core.safe_output(output,p.relative_to(output).as_posix())
                    files.append(dict(file=safe.relative_to(output).as_posix(),sha256=sha(safe)))
        checkpoints[name]=dict(report=report,files=files)
        core.write_json(output/'manifest.json',plan)
        return report

    def package(self,job,plan,scene,animation,model,audio,mouth):
        output=self.output/job['id'];model_only=plan.get('model_only',False)
        items=[]
        if not model_only:items.append(('manifest.json','manifest.json'))
        if not model_only and not plan.get('scene_fbx_only'):
            items.extend((i['output'],i['output']) for i in plan['outputs'])
        items.extend((i['file'],i['file']) for i in scene['files'])
        items.extend((i['file'],i['file']) for i in animation['clips'])
        if animation['clips']:items.append(('animations/export-report.json','animations/export-report.json'))
        for name,report in (('audio',audio),('mouth',mouth)):
            items.extend((i['file'],i['file']) for i in report['files'])
            if report['files']:items.append((name+'/export-report.json',name+'/export-report.json'))
        items.extend((i['file'],i['file'].removeprefix('models/') if model_only else i['file']) for i in model['files'])
        if model['models'] and not model_only:items.append(('models/export-report.json','models/export-report.json'))
        unique={}
        for local,name in items:
            p=core.safe_output(output,local)
            if name in unique and unique[name]!=p:raise ValueError('ZIP路径重复：'+name)
            unique[name]=p
        total=sum(p.stat().st_size for p in unique.values())
        self.update(job,phase='packaging',phase_label='打包 ZIP',phase_completed=0,
                    phase_total=len(unique),packaged_bytes=0,package_total_bytes=total)
        done=0
        temporary=self.output/(job['id']+'.zip.part')
        with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED,compresslevel=1) as archive:
            for n,(name,p) in enumerate(unique.items(),1):
                archive.write(p,name);done+=p.stat().st_size
                self.update(job,phase_completed=n,packaged_bytes=done,current=name)
        final=self.output/(job['id']+'.zip')
        if final.exists():
            self.storage_bytes(job['id'])
            history=output/'history'/f'{int(job.get("attempt",1)):03d}_{uuid.uuid4().hex[:8]}'
            history.mkdir(parents=True)
            final.rename(history/'previous.zip')
        temporary.replace(final)
