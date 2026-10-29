"""Attach verified horizontal choreography curves without changing body curves."""
from pathlib import Path
import json,math,re


def clip_identity(name):
    name=Path(name).name
    while name.lower().endswith('.anim'):name=name[:-5]
    return name.casefold()


def prepare(root):
    if root.get('root')!=0:raise ValueError('尚未验证这种根节点模式')
    flag=root.get('rootScaling')
    if type(flag) not in (bool,int) or flag not in (0,1):raise ValueError('无效根缩放开关')
    # RootCurveData.rootScaling is Boolean, never a numeric amplitude.
    # Bake source curve units for the chosen reference Avatar; retain the flag
    # in the report instead of multiplying the trajectory by 0/1.
    scale=1.0
    if any(root.get(k,{}).get('m_Curve') for k in ('pos_y','rot_x','rot_y','rot_z','rot_w')):
        raise ValueError('根数据包含独立高度或旋转，需要另外验证组合方式；原始数据保留')
    curves={}
    for axis in 'xz':
        curve=root.get('pos_'+axis,{})
        keys=curve.get('m_Curve',[])
        if not keys:continue
        previous=-1
        for k in keys:
            if not all(isinstance(k.get(f),(int,float)) and math.isfinite(k[f]) for f in ('time','value','inSlope','outSlope')):raise ValueError('无效根关键帧')
            if k['time']<=previous:raise ValueError('根曲线时间须严格递增')
            previous=k['time']
        if abs(keys[0]['time'])>1e-5:raise ValueError('根曲线不是从零时刻开始')
        curves[axis]=dict(curve=curve,origin=keys[0]['value'],scale=scale)
    if not curves:raise ValueError('没有水平根位移曲线')
    return curves


def merge_clip(body,target,root,reference_scale=1):
    body,target=Path(body),Path(target)
    if target.exists():raise ValueError('不覆盖已有合并动作')
    curves=prepare(root)
    if not math.isfinite(reference_scale) or reference_scale<=0:raise ValueError('无效参考Avatar比例')
    # RootT carries the body trajectory; MotionT is the extracted object trajectory.
    # Both must be present so extraction does not counter-translate the body.
    # Never stack over an already-authored horizontal trajectory.
    stop=None;humanoid=False
    with body.open(encoding='utf-8-sig') as source:
        for line in source:
            if re.match(r'    attribute: (RootT|MotionT)\.[xz]\s*$',line):raise ValueError('身体动作已有水平根曲线，拒绝重复叠加')
            if line.strip()=='classID: 95':humanoid=True
            if line.startswith('    m_StopTime:'):stop=float(line.split(':',1)[1])
    if not humanoid or stop is None:raise ValueError('身体动作不是可识别的Humanoid片段')
    for c in curves.values():
        end=c['curve']['m_Curve'][-1]['time']
        if abs(end-stop)>.05:raise ValueError('根位移与身体动作时长不一致')
    target.parent.mkdir(parents=True,exist_ok=True)
    temp=target.with_suffix('.anim.part')
    try:
        inserted=False
        with body.open(encoding='utf-8-sig') as src,temp.open('w',encoding='utf-8',newline='\n') as dst:
            for line in src:
                if line.startswith('  m_Name:'):line='  m_Name: '+target.stem+'\n'
                if line.startswith('  m_PPtrCurves:'):
                    for attribute,data in ((prefix+'.'+axis,data) for axis,data in curves.items() for prefix in ('RootT','MotionT')):
                        c=data['curve'];scale=data['scale']/reference_scale;origin=data['origin']
                        dst.write('  - serializedVersion: 2\n    curve:\n      serializedVersion: 2\n      m_Curve:\n')
                        for k in c['m_Curve']:
                            dst.write('      - serializedVersion: 3\n')
                            values=dict(time=k['time'],value=(k['value']-origin)*scale,inSlope=k['inSlope']*scale,outSlope=k['outSlope']*scale,tangentMode=0,weightedMode=k.get('weightedMode',0),inWeight=k.get('inWeight',1/3),outWeight=k.get('outWeight',1/3))
                            for key,value in values.items():dst.write('        '+key+': '+format(value,'.17g')+'\n')
                        dst.write(f'      m_PreInfinity: {c.get("m_PreInfinity",2)}\n      m_PostInfinity: {c.get("m_PostInfinity",2)}\n      m_RotationOrder: {c.get("m_RotationOrder",4)}\n    attribute: {attribute}\n    path: \n    classID: 95\n    script: {{fileID: 0}}\n')
                    inserted=True
                dst.write(line)
        if not inserted:raise ValueError('未找到Humanoid曲线插入位置')
        temp.replace(target)
    finally:temp.unlink(missing_ok=True)
    return dict(axes=list(curves),source_root_scaling_flag=bool(root['rootScaling']),unit_policy='relative_source_curves_baked_for_reference_avatar',reference_human_scale=reference_scale,relative_start=True,duration=stop,root_pose_compensated=True,merge_version=2)


def export_merged_roots(sample,manifest,report,output,progress=lambda text:None):
    import UnityPy
    import scsp_download as core
    from scsp_anim_export import digest
    from runtime_paths import app_root
    sample,output=Path(sample),Path(output)
    roots=[e for e in manifest['entries'] if e['id'] in manifest['selected_ids'] and e['name'].lower().endswith('_root.asset')]
    if not roots:return
    model=app_root()/'tools/PoseWorker/model.json'
    reference=json.loads(model.read_text(encoding='utf-8'))['humanScale']
    outputs={o['file']:o for o in manifest['outputs']}
    initial=list(report['clips'])
    report.setdefault('root_merges',[])
    for item in initial:
        body=sample/item['file']
        # Only source-backed original clips; never merge auxiliary or converted clips.
        source=next((s for s in report['sources'] if clip_identity(s['name'])==clip_identity(body.name)),None)
        if not source:continue
        entry=next((e for e in manifest['entries'] if e['name']==source['resource'] and e['id'] in manifest['selected_ids']),None)
        if not entry or not (entry['type']=='anim' or entry['name'].lower().endswith('_body.asset')):continue
        stem=Path(entry['name']).stem.removesuffix('_body')
        matched=[e for e in roots if re.fullmatch(re.escape(stem)+r'(?:_\d+)?_root\.asset',Path(e['name']).name,re.I)]
        if len({Path(e['name']).name.casefold() for e in matched})!=len(matched):
            report.setdefault('warnings',[]).append(entry['name']+'：根资源同名且不唯一，未猜配')
            continue
        for root in matched:
            record=dict(source_file=item['file'],root_resource=root['id'])
            try:
                raw=outputs[root['file']];path=core.safe_output(sample,raw['output'])
                if digest(path)!=raw['sha256']:raise ValueError('根数据输入哈希不一致')
                trees=[o.read_typetree() for o in UnityPy.load(path.read_bytes()).objects if o.type.name=='MonoBehaviour']
                datas=[t['rootCurveData'] for t in trees if 'rootCurveData' in t]
                if len(datas)!=1:raise ValueError('根数据结构不存在或不唯一')
                slot=Path(root['name']).stem[len(stem):-5].strip('_')
                suffix=('_slot'+slot if slot else '')+'_with_root.anim'
                target=output/(body.stem+suffix)
                progress('合并身体动作与根位移：'+target.name)
                info=merge_clip(body,target,datas[0],reference)
                relative=target.relative_to(sample).as_posix() if target.is_relative_to(sample) else str(target)
                clip=dict(file=relative,bytes=target.stat().st_size,sha256=digest(target),kind='body_with_root',**record,**info)
                report['clips'].append(clip);record.update(status='merged',file=relative,**info)
            except (ValueError,KeyError) as error:
                record.update(status='not_merged',reason=str(error))
                report.setdefault('warnings',[]).append(root['name']+'：未合并根位移，'+str(error))
            report['root_merges'].append(record)
