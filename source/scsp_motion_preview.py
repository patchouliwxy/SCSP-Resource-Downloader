"""Temporary browser motion previews, retargeted by a bundled Unity Humanoid worker."""
from array import array
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import uuid

import scsp_download as core
from scsp_anim_export import export_animations
from scsp_preview import Previews
from resource_taxonomy import classify_resource
from runtime_paths import app_root

ROOT=app_root()
WORKER=ROOT/'tools/PoseWorker/SCSPPoseWorker.exe'
MODEL=ROOT/'tools/PoseWorker/model.json'
BODY_CATEGORIES={'dance','performance','story_motion','character_motion','lesson_motion','outfit_motion','animation'}


def supports_motion(entry):
    return (entry['type']=='anim' or entry['name'].lower().endswith('_body.asset')) and classify_resource(entry)['category'] in BODY_CATEGORIES


def normalize(name):
    return name.replace('LeftHand.','Left ').replace('RightHand.','Right ').replace('.',' ')


def sample_humanoid(path, model, fps=30):
    """Read only Animator float curves, retaining Hermite slopes and step keys.

    Streaming line parsing avoids constructing a huge YAML syntax tree. Weighted
    tangents are explicitly rejected until supported rather than approximated.
    """
    import numpy as np
    if path.stat().st_size>512*1048576:raise ValueError('动作文本超过预览解析上限')
    allowed={normalize(n) for n in model['muscles']}
    tracks=[];active=False;name='';start=0.;stop=None;current=None
    with path.open(encoding='utf-8-sig') as source:
        for line in source:
            if line.startswith('  m_Name:'):name=line.split(':',1)[1].strip()
            elif line.startswith('    m_StartTime:'):start=float(line.split(':',1)[1])
            elif line.startswith('    m_StopTime:'):stop=float(line.split(':',1)[1])
            if line.startswith('  m_FloatCurves:'):active=True;continue
            if line.startswith('  m_PPtrCurves:'):active=False
            if not active:continue
            if line.startswith('  - serializedVersion:'):
                current={k:array('d') for k in ('time','value','inSlope','outSlope')};current['weighted']=False
            elif current is not None:
                key,sep,value=line.strip().partition(':')
                if key in ('time','value','inSlope','outSlope'):current[key].append(float(value.strip().lower().replace('.inf','inf').replace('.nan','nan')))
                elif key=='weightedMode' and int(value.strip())!=0:current['weighted']=True
                elif key=='attribute':current['name']=value.strip().strip('"\'')
                elif key=='classID':
                    if int(value.strip())==95 and current.get('name') and len(current['time']):tracks.append(current)
                    current=None
    muscles=[t for t in tracks if normalize(t['name']) in allowed]
    if not muscles:raise ValueError('这个片段没有可用的 Humanoid 肌肉曲线，不能套用人形预览')
    selected=[t for t in tracks if normalize(t['name']) in allowed or re.fullmatch(r'Root[TQ]\.[xyzw]',t['name'])]
    if len({t['name'] for t in selected})!=len(selected):raise ValueError('动作有重复的人形曲线，拒绝猜测绑定')
    if stop is None:stop=max(t['time'][-1] for t in selected)
    duration=stop-start
    if not math.isfinite(duration) or not 0<duration<=600:raise ValueError('动作时长须在0至600秒之间')
    count=math.ceil(duration*fps)+1
    times=np.minimum(start+np.arange(count,dtype=np.float64)/fps,stop)
    output=np.empty((count,len(selected)),dtype=np.float32)
    for column,t in enumerate(selected):
        if t['weighted']:raise ValueError('此动作使用加权曲线切线，暂不支持可靠预览；独立anim下载不受影响')
        keys=np.asarray(t['time']);values=np.asarray(t['value'])
        if not np.isfinite(keys).all() or not np.isfinite(values).all() or np.any(np.diff(keys)<0):raise ValueError('动作曲线包含无效数值/时间')
        if len(keys)==1:output[:,column]=values[0];continue
        left=np.clip(np.searchsorted(keys,times,side='right')-1,0,len(keys)-2);right=left+1
        length=keys[right]-keys[left];u=np.clip((times-keys[left])/np.maximum(length,1e-12),0,1)
        ins=np.asarray(t['inSlope']);outs=np.asarray(t['outSlope'])
        if len(ins)!=len(keys) or len(outs)!=len(keys):raise ValueError('动作曲线切线数量不匹配')
        stepped=np.isinf(outs[left])|np.isinf(ins[right])
        if np.isnan(ins).any() or np.isnan(outs).any():raise ValueError('动作曲线切线包含NaN')
        a=np.where(stepped,0,outs[left])*length;b=np.where(stepped,0,ins[right])*length
        v=(2*u**3-3*u**2+1)*values[left]+(u**3-2*u**2+u)*a+(-2*u**3+3*u**2)*values[right]+(u**3-u**2)*b
        v=np.where(stepped,values[left],v);v=np.where(times<=keys[0],values[0],v);v=np.where(times>=keys[-1],values[-1],v)
        output[:,column]=v
    if not np.isfinite(output).all():raise ValueError('预览采样包含非有限值')
    selected_names={t['name'] for t in selected}
    return dict(name=name,fps=fps,duration=duration,frameCount=count,channels=[t['name'] for t in selected],omittedChannels=[t['name'] for t in tracks if t['name'] not in selected_names],samples=output.reshape(-1).tolist())


def retarget(anim,folder):
    model=json.loads(MODEL.read_text(encoding='utf-8'))
    data=sample_humanoid(anim,model)
    request=folder/'_work/pose-input.json';request.write_text(json.dumps(data,allow_nan=False,separators=(',',':')),encoding='utf-8')
    target=folder/'motion'
    with (folder/'_work/worker-process.log').open('wb') as log:
        result=subprocess.run([str(WORKER),'-batchmode','-nographics','--pose-input',str(request),'--pose-out',str(target),'-logFile',str(folder/'_work/worker.log')],cwd=WORKER.parent,stdout=log,stderr=subprocess.STDOUT,timeout=120,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode or not target.with_suffix('.json').is_file():raise RuntimeError('后台Humanoid重定向失败；该片段可能不兼容预览模型')
    meta=json.loads(target.with_suffix('.json').read_text(encoding='utf-8'))
    meta['source_omitted_channels']=data['omittedChannels']
    target.with_suffix('.json').write_text(json.dumps(meta,ensure_ascii=False),encoding='utf-8')
    expected=meta['frameCount']*meta['boneCount']*7*4
    if target.with_suffix('.bin').stat().st_size!=expected:raise RuntimeError('预览骨骼数据尺寸不一致')
    return meta


class MotionPreviews(Previews):
    def start(self,identity):
        entry=self.catalog.by_id.get(identity)
        if not entry or not supports_motion(entry):raise core.DownloadError('请选择身体动作anim或body.asset；镜头、表情、场景动画不套用人形')
        if not WORKER.is_file() or not MODEL.is_file():raise core.DownloadError('缺少内置Humanoid预览工具，请使用完整发行目录')
        planned,missing=core.resolve_dependencies(self.catalog.entries,[entry])
        if sum(e['size'] for e in planned)>64*1048576:raise core.DownloadError('动作预览依赖超过64MiB，请改用独立下载')
        with self.lock:
            if sum(j['status'] in ('queued','running') for j in self.jobs.values())>=3:raise core.DownloadError('动作预览队列已满，请稍后再试')
            job=dict(key=uuid.uuid4().hex[:24],id=identity,name=entry['name'],status='queued',stage='等待准备',error='',missing=missing)
            self.jobs[job['key']]=job;self.pool.submit(self.run,job,planned);return dict(job)

    def run(self,job,entries):
        folder=self.root/job['key'];work=folder/'_work'
        try:
            with self.lock:
                if job.get('released'):return
                job.update(status='running',stage='读取动作资源')
            work.mkdir(parents=True)
            outputs=[]
            for entry in {e['file']:e for e in entries}.values():
                decoded=core.decode_asset(entry,core.get_file(entry,self.cache))
                relative='_work/'+entry['file']+'.unity3d';(folder/relative).write_bytes(decoded)
                import hashlib
                outputs.append(dict(file=entry['file'],output=relative,sha256=hashlib.sha256(decoded).hexdigest()))
            core.write_json(folder/'manifest.json',dict(game_version=self.catalog.data['game_version'],resource_version=self.catalog.data['resource_version'],selected_ids=[job['id']],entries=entries,outputs=outputs))
            job['stage']='恢复独立动作曲线'
            report=export_animations(folder,progress=lambda text:job.update(stage=text))
            clips=report['clips']
            stem=Path(job['name']).stem.removesuffix('_body').casefold()
            exact=[c for c in clips if Path(c['file']).stem.casefold()==stem]
            selected=exact or clips
            if len(selected)!=1:raise ValueError('资源包内含多个片段或没有片段，无法唯一选择身体动作；请先下载检查')
            job['stage']='在Humanoid模型上重定向'
            meta=retarget(core.safe_output(folder,selected[0]['file']),folder)
            with self.lock:
                job.update(status='completed',stage='预览就绪',motion=meta,bytes=(folder/'motion.bin').stat().st_size,model_name='園田 智代子')
        except Exception as error:
            with self.lock:job.update(status='failed',error=str(error),stage='无法预览')
        finally:
            # Only the temporary preview and sampled bones survive until close.
            for name in ('_work','animations','animation-export-work'):
                path=folder/name
                if path.exists() and path.resolve().is_relative_to(folder.resolve()) and not path.is_symlink():shutil.rmtree(path,ignore_errors=True)
            (folder/'manifest.json').unlink(missing_ok=True)
            self.finish_released(job)
