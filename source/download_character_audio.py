"""Resumable SCSP dialogue corpus export using actual decoder stream names."""
from __future__ import annotations
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor,as_completed
import csv
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit
import wave
import scsp_download as core
from scsp_audio_index import cue_characters,fingerprint,save_json
from scsp_audio_export import DECODER
from resource_taxonomy import classify_resource
from runtime_paths import app_root
ROOT=app_root()


def safe_path(root,relative):
    path=(root/relative).resolve()
    if not path.is_relative_to(root) or path==root:raise ValueError('Dataset path escapes output root')
    return path


def safe_name(name,limit=90):
    name=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',name).strip(' .')[:limit].rstrip(' .')
    if not name or re.fullmatch(r'(?i:con|prn|aux|nul|com[1-9]|lpt[1-9])',name):name='audio_'+name
    return name


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        while b:=f.read(1048576):h.update(b)
    return h.hexdigest()


def inspect_wav(path,info):
    pcm=hashlib.sha256();nonzero=False
    with wave.open(str(path),'rb') as w:
        rate,channels,frames=w.getframerate(),w.getnchannels(),w.getnframes()
        if w.getsampwidth()!=2 or rate!=info['sampleRate'] or channels!=info['channels'] or frames!=info['numberOfSamples']:
            raise ValueError('WAV format / duration mismatch')
        while b:=w.readframes(65536):pcm.update(b);nonzero|=any(b)
    return dict(sample_rate=rate,channels=channels,frames=frames,duration=frames/rate,pcm_sha256=pcm.hexdigest(),non_silent=nonzero)


def role_folder(cue_name,names):
    roles=cue_characters(cue_name,names)
    folder=safe_name(roles[0]+'_'+names[roles[0]],70) if len(roles)==1 else ('_unknown' if not roles else '_multiple_roles')
    return folder,[dict(id=k,name=names[k]) for k in roles]


class Corpus:
    def __init__(self,index,characters,out,cache,workers=4):
        self.index,self.names=index,characters
        self.out,self.cache=Path(out).resolve(),Path(cache).resolve();self.workers=workers
        self.entries=[e for e in index['entries'] if classify_resource(e)['category']=='audio_story']
        self.out.mkdir(parents=True,exist_ok=True);self.cache.mkdir(parents=True,exist_ok=True)
        self.lock=threading.RLock();self.local=threading.local();self.stop=threading.Event()
        self.completed=0;self.reused=0;self.failed={};self.tracks=0;self.bytes=0;self.started=time.time()
        self.config=dict(schema=1,game_version=index['game_version'],resource_version=index['resource_version'],scope='audio_story',
                         banks=len(self.entries),raw_bytes=sum(e['size'] for e in self.entries),decoder=str(DECODER),
                         original_audio_preserved_in_cache=True,transcripts_provided=False,
                         dependency_complete=all(not e['dependencies'] for e in self.entries),
                         unresolved_dependencies=[e['id']+' -> '+dep for e in self.entries for dep in e['dependencies']])
    def initialize(self):
        path=self.out/'dataset.json'
        if path.is_file():
            previous=json.loads(path.read_text('utf-8'))
            if any(previous.get(k)!=self.config[k] for k in ('schema','game_version','resource_version','scope')):
                raise ValueError('目标目录属于另一版本/用途，请为新版本选择独立目录，避免混入旧训练集')
        if not DECODER.is_file():raise ValueError('Missing bundled vgmstream decoder')
        if not self.config['dependency_complete']:raise ValueError('当前批量导出不支持带外部依赖的剧情包，缺项保留在计划中')
        if shutil.disk_usage(self.out).free<max(256*1048576,self.config['raw_bytes']*12):raise ValueError('Free disk space below conservative WAV export estimate')
        save_json(path,self.config)
        # Pin only this corpus's inputs; a later downloader catalog update must not
        # silently change the remaining banks or Japanese character names on resume.
        snapshot=self.out/'_state/catalog.json'
        if not snapshot.exists():save_json(snapshot,dict(schema=1,game_version=self.index['game_version'],resource_version=self.index['resource_version'],entries=self.entries))
        character_snapshot=self.out/'_state/character-data.json'
        if not character_snapshot.exists():save_json(character_snapshot,dict(game_version=self.index['game_version'],resource_version=self.index['resource_version'],characters=self.names))
        (self.out/'README.md').write_text(
            '# SCSP 角色对白音频\n\n角色目录为编号加日语姓名，WAV 保留原始采样率和声道，输出 PCM16。\n'
            '仅包含当前目录的剧情对白，不混入歌曲、伴奏或音效库。\n'
            '角色按解码器返回的实际音轨名称识别。_unknown 为未知角色，_multiple_roles 为多角色别名歧义，不应直接当单人训练样本。\n\n'
            'progress.json 为当前进度；summary.json 为最后一次汇总；manifest.jsonl/CSV 为来源、角色、时长、SHA 和重复标记。\n'
            '每个角色目录也有 manifest.jsonl。subsong 是实际解码器音轨编号，不是 CueIndex。\n'
            '原始包保存在共用缓存，不在角色目录重复交付。中断后运行 Resume.cmd，已完成包按 SHA 校验后复用。\n\n'
            '这是原始音频语料，不是直接可训练的语言模型数据集：没有配对台词文本（transcript=null），未做人声分离、VAD、降噪或音质人工筛选。\n'
            'duplicate_of 表示 PCM 内容重复；划分训练/验证集前应去重，同一句或同一剧情不应跨集合泄漏。\n'
            '新资源版本应选择新输出目录，避免把不同版本混合到一个训练集。\n',encoding='utf-8')
    def state_path(self,e):return self.out/'_state/banks'/(fingerprint(e)+'.json')
    def resume(self,e):
        path=self.state_path(e)
        if not path.is_file():return None
        r=json.loads(path.read_text('utf-8'))
        if r['identity']!=fingerprint(e) or not r.get('complete'):raise ValueError('Invalid completed bank receipt')
        for t in r['tracks']:
            p=safe_path(self.out,t['file'])
            if not p.is_file() or p.stat().st_size!=t['bytes'] or digest(p)!=t['sha256']:
                raise ValueError('Existing corpus audio changed/missing: '+str(p))
        return r
    def fetch(self,e):
        target=self.cache/core.real_name(e)
        if target.is_file() and target.stat().st_size==e['size']:
            if not e.get('sha256') or digest(target)==e['sha256']:return target
        if not 0<e['size']<=64*1048576:raise ValueError('Unsupported dialogue bank size')
        url=urlsplit(core.CDN);name=core.real_name(e);path=url.path.rstrip('/')+'/'+name[:2]+'/'+name
        for attempt in range(5):
            if self.stop.is_set():raise ValueError('Corpus export stopped')
            conn=getattr(self.local,'conn',None)
            if conn is None:conn=http.client.HTTPSConnection(url.hostname,timeout=45);self.local.conn=conn
            try:
                conn.request('GET',path,headers={'Accept-Encoding':'identity'});r=conn.getresponse()
                if r.status in (429,500,502,503,504):
                    retry=r.getheader('Retry-After','');r.close();conn.close();self.local.conn=None
                    if attempt==4:raise ValueError('CDN temporarily unavailable: '+str(r.status))
                    self.stop.wait(min(60,int(retry) if retry.isdigit() else 2**attempt));continue
                if r.status!=200:r.close();conn.close();self.local.conn=None;raise ValueError('CDN HTTP '+str(r.status))
                data=r.read(e['size']+1)
                if len(data)!=e['size']:raise ValueError('CDN resource size mismatch')
                if e.get('sha256') and hashlib.sha256(data).hexdigest()!=e['sha256']:raise ValueError('CDN SHA-256 mismatch')
                part=target.with_suffix('.character-audio.part');part.write_bytes(data);part.replace(target);return target
            except (OSError,http.client.HTTPException):
                conn.close();self.local.conn=None
                if attempt==4:raise
                self.stop.wait(2**attempt)
    def decode(self,e):
        restored=self.resume(e)
        if restored:return restored,True
        raw=self.fetch(e);data=core.decode_asset(e,raw.read_bytes())
        work=safe_path(self.out,'_work/'+fingerprint(e));work.mkdir(parents=True,exist_ok=True)
        original=work/safe_name(Path(e['name']).name,140);original.write_bytes(data)
        flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
        metadata=subprocess.run([str(DECODER),'-m','-I','-S','0',str(original)],capture_output=True,timeout=300,creationflags=flags)
        (work/'metadata.log').write_bytes(metadata.stdout+metadata.stderr)
        if metadata.returncode:raise ValueError('Audio metadata failed: '+metadata.stderr.decode('utf-8','replace')[-1200:])
        infos=[json.loads(line) for line in metadata.stdout.decode('utf-8').splitlines() if line.strip()]
        if not infos or len(infos)>10000:raise ValueError('Invalid subsong metadata count')
        if any(i['streamInfo']['index']!=n or i['streamInfo']['total']!=len(infos) for n,i in enumerate(infos,1)):
            raise ValueError('Subsong index/count mismatch; CueIndex is not used as subsong index')
        waves=work/'wav';waves.mkdir(exist_ok=True)
        with (work/'decoder.log').open('wb') as log:
            result=subprocess.run([str(DECODER),'-i','-W','1','-S','0','-o',str(waves/'track_?s.wav'),str(original)],stdout=log,stderr=subprocess.STDOUT,timeout=300,creationflags=flags)
        if result.returncode:raise ValueError('Audio decode failed; see '+str(work/'decoder.log'))
        outputs=list(waves.glob('*.wav'))
        if len(outputs)!=len(infos):raise ValueError('Decoded WAV count mismatch')
        tracks=[]
        for number,info in enumerate(infos,1):
            source=waves/f'track_{number}.wav'
            properties=inspect_wav(source,info);cue=info['streamInfo'].get('name','')
            folder,roles=role_folder(cue,self.names)
            basename=f'{safe_name(Path(e["name"]).stem,65)}__s{number:05d}__{fingerprint(e)[:10]}.wav'
            relative=folder+'/'+basename;target=safe_path(self.out,relative);target.parent.mkdir(parents=True,exist_ok=True)
            sha=digest(source)
            if target.exists():
                if digest(target)!=sha:raise ValueError('Refusing to overwrite changed WAV: '+str(target))
                source.unlink()
            else:source.replace(target)
            tracks.append(dict(file=relative,characters=roles,resource_id=e['id'],resource=e['name'],source_file=e['file'],
                               subsong=number,track_name=cue,transcript=None,
                               training_review_required=len(roles)!=1 or properties['channels']!=1 or not properties['non_silent'],
                               bytes=target.stat().st_size,sha256=sha,**properties))
        receipt=dict(identity=fingerprint(e),complete=True,resource_id=e['id'],resource=e['name'],source_file=e['file'],
                     source_sha256=digest(raw),authoritative_source_sha256_verified=bool(e.get('sha256')),
                     tracks=tracks,game_version=self.index['game_version'],resource_version=self.index['resource_version'])
        save_json(self.state_path(e),receipt)
        # Only delete this validated, tool-created workspace after the bank receipt is durable.
        if not work.resolve().is_relative_to((self.out/'_work').resolve()):raise ValueError('Unsafe cleanup path')
        if any(p.is_symlink() for p in work.rglob('*')):raise ValueError('Workspace contains symlink')
        shutil.rmtree(work)
        return receipt,False
    def progress(self,status='running'):
        with self.lock:
            value=dict(status=status,completed_banks=self.completed,total_banks=len(self.entries),reused_banks=self.reused,
                       failed_banks=len(self.failed),wav_files=self.tracks,wav_bytes=self.bytes,elapsed_seconds=round(time.time()-self.started,1),
                       errors=[dict(id=k,error=v) for k,v in list(self.failed.items())[:30]])
            save_json(self.out/'progress.json',value);return value
    def one(self,e):
        if self.stop.is_set():return
        try:
            receipt,reused=self.decode(e)
            with self.lock:
                self.completed+=1;self.reused+=reused;self.tracks+=len(receipt['tracks']);self.bytes+=sum(t['bytes'] for t in receipt['tracks'])
                self.failed.pop(e['id'],None)
                if self.completed%50==0:print(json.dumps(self.progress(),ensure_ascii=True),flush=True)
        except Exception as exc:
            with self.lock:
                self.failed[e['id']]=str(exc)
                save_json(self.out/'_state/errors'/(fingerprint(e)+'.json'),dict(id=e['id'],error=str(exc)))
        finally:
            if getattr(self.local,'conn',None):
                # Connections remain alive for the next bank handled by this same worker.
                pass
    def manifests(self):
        paths={};counts=Counter();seconds=Counter();all_rows=[]
        for e in self.entries:
            p=self.state_path(e)
            if not p.is_file():continue
            receipt=json.loads(p.read_text('utf-8'))
            for row in receipt['tracks']:
                key=(row['sample_rate'],row['channels'],row['pcm_sha256'])
                row['duplicate_of']=paths.get(key);paths.setdefault(key,row['file'])
                counts[row['file'].split('/')[0]]+=1;seconds[row['file'].split('/')[0]]+=row['duration'];all_rows.append(row)
        temporary=self.out/'manifest.jsonl.part'
        with temporary.open('w',encoding='utf-8',newline='\n') as f:
            for row in all_rows:f.write(json.dumps(row,ensure_ascii=False)+'\n')
        temporary.replace(self.out/'manifest.jsonl')
        for folder in counts:
            with (self.out/folder/'manifest.jsonl').open('w',encoding='utf-8',newline='\n') as f:
                for row in all_rows:
                    if row['file'].split('/')[0]==folder:f.write(json.dumps(row,ensure_ascii=False)+'\n')
        fields=['file','characters','resource','subsong','track_name','duration','sample_rate','channels','transcript','duplicate_of','sha256']
        with (self.out/'manifest.csv').open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader()
            for row in all_rows:w.writerow({**row,'characters':' / '.join(c['id']+' '+c['name'] for c in row['characters'])})
        summary=dict(**self.config,**self.progress('completed' if not self.failed else 'completed_with_errors'),
                     folders=[dict(folder=k,files=v,hours=seconds[k]/3600) for k,v in sorted(counts.items())],
                     duplicate_wav_files=sum(bool(r['duplicate_of']) for r in all_rows),
                     total_hours=sum(seconds.values())/3600,missing_transcripts=True)
        save_json(self.out/'summary.json',summary)
        return summary
    def run(self):
        self.initialize();self.progress()
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            for offset in range(0,len(self.entries),64):
                futures=[pool.submit(self.one,e) for e in self.entries[offset:offset+64]]
                for future in as_completed(futures):future.result()
                self.progress()
        # Retry only failures; successful bank receipts are never redownloaded or decoded.
        retry=[e for e in self.entries if e['id'] in self.failed]
        if retry:
            with ThreadPoolExecutor(max_workers=min(2,self.workers)) as pool:
                for f in as_completed([pool.submit(self.one,e) for e in retry]):f.result()
        return self.manifests()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--index',type=Path,default=ROOT/'official-current-index.json')
    p.add_argument('--characters',type=Path,default=ROOT/'character-data.json')
    p.add_argument('--out',type=Path,required=True);p.add_argument('--cache',type=Path,default=ROOT/'.scsp-cache')
    p.add_argument('--workers',type=int,default=4);p.add_argument('--limit',type=int,default=0)
    args=p.parse_args()
    if not 1<=args.workers<=8:p.error('workers must be 1..8')
    index=json.loads(args.index.read_text('utf-8'));characters=json.loads(args.characters.read_text('utf-8'))
    if any(index[k]!=characters[k] for k in ('game_version','resource_version')):raise ValueError('Character master/catalog version mismatch')
    corpus=Corpus(index,characters['characters'],args.out,args.cache,args.workers)
    if args.limit:corpus.entries=corpus.entries[:args.limit];corpus.config.update(banks=len(corpus.entries),raw_bytes=sum(e['size'] for e in corpus.entries))
    lock=(corpus.out/'.dataset.lock').open('a+b')
    try:
        if os.name=='nt':
            import msvcrt
            if lock.tell()==0:lock.write(b'0');lock.flush()
            lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl;fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        print(json.dumps(corpus.config,ensure_ascii=True),flush=True)
        summary=corpus.run();print(json.dumps(summary,ensure_ascii=True),flush=True)
        return 0 if not corpus.failed else 2
    finally:lock.close()


if __name__=='__main__':raise SystemExit(main())
