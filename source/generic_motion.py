"""Recover explicit Transform channels, keeping unknown bindings visible."""
from pathlib import Path
import math,re,zlib,json

VOWELS={zlib.crc32(('Lip'+c.upper()).encode()):c for c in 'aiueo'}

def vector_tracks(path):
    tracks=[];section='';curve=None;key=None
    with Path(path).open(encoding='utf-8-sig') as f:
        for line in f:
            m=re.match(r'  m_(Position|Rotation|Euler|Scale)Curves:',line)
            if m:section=m[1];curve=None;continue
            if re.match(r'  m_\w+:',line):section='';continue
            if not section:continue
            if line.startswith('  - curve:'):curve={'kind':section,'keys':[]};key=None
            elif curve is not None:
                if line.startswith('        time:'):
                    key={'time':float(line.split(':',1)[1])};curve['keys'].append(key)
                elif key is not None and re.match(r'        (value|inSlope|outSlope):',line):
                    field=line.strip().split(':',1)[0]
                    values={k:float(v.replace('.inf','inf')) for k,v in re.findall(r'([xyzw]): ([^,}]+)',line)}
                    key[field]=values
                elif key is not None and '        weightedMode:' in line:
                    if int(line.split(':',1)[1]):raise ValueError('通用曲线含加权切线，尚不能可靠转换')
                elif line.startswith('    path:'):
                    curve['path']=line.split(':',1)[1].strip().strip('"\'');tracks.append(curve);curve=None
    return tracks

def sample(keys,axis,time):
    if not keys:raise ValueError('曲线没有关键帧')
    if time<=keys[0]['time']:return keys[0]['value'][axis]
    if time>=keys[-1]['time']:return keys[-1]['value'][axis]
    import bisect
    left=bisect.bisect_right([k['time'] for k in keys],time)-1;a,b=keys[left:left+2]
    length=b['time']-a['time'];u=(time-a['time'])/length
    start=a['value'][axis];end=b['value'][axis]
    out=a.get('outSlope',{}).get(axis,0);ins=b.get('inSlope',{}).get(axis,0)
    if not math.isfinite(out) or not math.isfinite(ins):return start
    return (2*u**3-3*u**2+1)*start+(u**3-2*u**2+u)*out*length+(-2*u**3+3*u**2)*end+(u**3-u**2)*ins*length

def path_hash(path):
    m=re.match(r'path_0x([0-9A-Fa-f]{8})_',path)
    return int(m[1],16) if m else zlib.crc32(path.encode())

def lip_data(path,fps=60):
    with Path(path).open(encoding='utf-8-sig') as f:
        if '  m_PositionCurves: []' in f.read(262144):return None
    tracks=vector_tracks(path)
    if not tracks or any(t['kind']!='Position' or path_hash(t['path']) not in VOWELS for t in tracks):return None
    if len({path_hash(t['path']) for t in tracks})!=len(tracks):raise ValueError('重复口型绑定')
    for track in tracks:
        if any(abs(k['value'].get(a,0))>1e-6 for k in track['keys'] for a in 'yz'):return None
    duration=max(k['time'] for t in tracks for k in t['keys'])
    if not 0<duration<=600:raise ValueError('口型片段时长超限')
    frames=[]
    for i in range(math.ceil(duration*fps)+1):
        frame={v:0.0 for v in 'aiueo'}
        for track in tracks:frame[VOWELS[path_hash(track['path'])]]=sample(track['keys'],'x',min(i/fps,duration))
        if not all(math.isfinite(v) for v in frame.values()):raise ValueError('口型有非有限值')
        frames.append(frame)
    return dict(frameRate=fps,offsetFrame=0,datas=frames,duration=duration,binding_basis='CRC32 exact LipA/LipI/LipU/LipE/LipO Transform paths',source_format='transform_lip_animation')

def generic_input(path,model,fps=30):
    tracks=vector_tracks(path)
    if not tracks:raise ValueError('片段既无Humanoid肌肉曲线，也没有可采样的Transform曲线')
    paths={0:''};ambiguous=set()
    for i,node in enumerate(model['nodes']):
        components=[];j=i
        while model['nodes'][j]['parent']>=0:
            components.insert(0,model['nodes'][j]['name']);j=model['nodes'][j]['parent']
        p='/'.join(components);h=zlib.crc32(p.encode())
        if h in paths and paths[h]!=p:ambiguous.add(h)
        paths[h]=p
    bindings=[];unknown=[]
    for track in tracks:
        h=path_hash(track['path'])
        if h not in paths or h in ambiguous:unknown.append(track['path']);continue
        for axis in ('xyzw' if track['kind']=='Rotation' else 'xyz'):
            bindings.append((track,axis,paths[h],{'Position':'position','Rotation':'rotation','Euler':'euler','Scale':'scale'}[track['kind']]+'.'+axis))
    if unknown:raise ValueError('通用动作绑定无法对应预览骨架：'+', '.join(unknown[:5])+'；需要原始骨架或显式路径映射，不能猜配')
    duration=max(k['time'] for t in tracks for k in t['keys'])
    if not 0<duration<=600:raise ValueError('通用动作时长超限')
    count=math.ceil(duration*fps)+1
    values=[sample(t['keys'],a,min(i/fps,duration)) for i in range(count) for t,a,_,_ in bindings]
    if not all(math.isfinite(v) for v in values):raise ValueError('通用动作包含无效值')
    return dict(name=Path(path).stem,fps=fps,duration=duration,frameCount=count,generic=True,
                channels=[prop for _,_,_,prop in bindings],paths=[p for _,_,p,_ in bindings],samples=values,omittedChannels=[])

def save_humanoid(path,data):
    """Write independent Animator curves; the original Transform clip is preserved."""
    import io
    out=io.StringIO();out.write('%YAML 1.1\n%TAG !u! tag:unity3d.com,2011:\n--- !u!74 &7400000\nAnimationClip:\n  serializedVersion: 7\n  m_ObjectHideFlags: 0\n  m_Name: '+Path(path).stem+'\n  m_Legacy: 0\n  m_Compressed: 0\n  m_RotationCurves: []\n  m_PositionCurves: []\n  m_ScaleCurves: []\n  m_FloatCurves:\n')
    names=data['channels'];values=data['samples'];count=data['frameCount'];fps=data['fps']
    for c,name in enumerate(names):
        m=re.match(r'(Left|Right) (Thumb|Index|Middle|Ring|Little) (.+)',name)
        if m:name=m[1]+'Hand.'+m[2]+'.'+m[3]
        out.write('  - serializedVersion: 2\n    curve:\n      serializedVersion: 2\n      m_Curve:\n')
        for i in range(count):
            out.write(f'      - serializedVersion: 3\n        time: {min(i/fps,data["duration"]):.9g}\n        value: {values[i*len(names)+c]:.9g}\n        inSlope: 0\n        outSlope: 0\n        weightedMode: 0\n')
        out.write('      m_PreInfinity: 2\n      m_PostInfinity: 2\n      m_RotationOrder: 4\n    attribute: '+name+'\n    path: \n    classID: 95\n    script: {fileID: 0}\n')
    out.write(f'  m_PPtrCurves: []\n  m_SampleRate: {fps}\n  m_AnimationClipSettings:\n    serializedVersion: 2\n    m_StartTime: 0\n    m_StopTime: {data["duration"]:.9g}\n    m_LoopTime: 0\n')
    Path(path).write_text(out.getvalue(),encoding='utf-8')
