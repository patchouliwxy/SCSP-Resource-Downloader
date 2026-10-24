"""Read actual ACB CueNameTable metadata, independently of audio decoding.

UTF format reference: vgmstream src/util/cri_utf.c and src/meta/acb.c.
CueIndex is NOT a vgmstream subsong index. Cues can alias/reuse waveforms.
"""
from __future__ import annotations
import hashlib
import http.client
import json
from pathlib import Path
import re
import struct
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlsplit
import scsp_download as core

PARSER_VERSION = 1
FORMATS = {0:'B',1:'b',2:'H',3:'h',4:'I',5:'i',6:'Q',7:'q',8:'f',9:'d',10:'I',11:'II',12:'16s'}


class UtfTable:
    def __init__(self, read, size, offset=0):
        self.read, self.offset = read, offset
        h=read(offset,32)
        if len(h)!=32 or h[:4]!=b'@UTF': raise ValueError('Unsupported ACB @UTF signature')
        self.size=struct.unpack_from('>I',h,4)[0]+8
        version,rows=struct.unpack_from('>HH',h,8)
        strings,data,name,self.columns,self.width,self.count=struct.unpack_from('>IIIHHI',h,12)
        self.rows,self.strings,self.data=rows+8,strings+8,data+8
        if version not in (0,1) or not (32<=self.rows<=self.strings<=self.data<=self.size<=size-offset):
            raise ValueError('Invalid UTF table bounds/version')
        if not 0<self.columns<=256 or self.count>128000 or self.count*self.width>self.strings-self.rows:
            raise ValueError('Invalid UTF row layout')
        if self.rows>32768 or self.data-self.strings>524288: raise ValueError('UTF metadata exceeds limits')
        schema=read(offset+32,self.rows-32)
        strings=read(offset+self.strings,self.data-self.strings)
        def text(index):
            if not 0<=index<len(strings): raise ValueError('UTF string offset out of bounds')
            end=strings.find(b'\0',index)
            if end<0: raise ValueError('Unterminated UTF string')
            return strings[index:end].decode('utf-8',errors='strict')
        self.text=text;self.name=text(name);self.fields={};cursor=0;row_pos=0
        for _ in range(self.columns):
            if cursor+5>len(schema):raise ValueError('Truncated UTF schema')
            flags=schema[cursor];key=text(struct.unpack_from('>I',schema,cursor+1)[0]);cursor+=5
            kind,storage=flags&15,flags&240
            if kind not in FORMATS or not storage&16 or storage&128:raise ValueError('Unsupported UTF column')
            width=struct.calcsize('>'+FORMATS[kind]);constant=None;position=None
            if storage&32:
                constant=schema[cursor:cursor+width];cursor+=width
                if len(constant)!=width:raise ValueError('Truncated UTF default')
            elif storage&64:
                position=row_pos;row_pos+=width
                if self.count and row_pos>self.strings-self.rows:raise ValueError('UTF column exceeds row section')
            self.fields[key]=(kind,width,constant,position)
    def value(self,row,key):
        if not 0<=row<self.count:raise ValueError('UTF row out of bounds')
        kind,width,constant,position=self.fields[key]
        if constant is not None:raw=constant
        elif position is not None:
            at=self.rows+row*self.width+position
            if at+width>self.strings:raise ValueError('UTF row value outside section')
            raw=self.read(self.offset+at,width)
        else:raw=bytes(width)
        values=struct.unpack('>'+FORMATS[kind],raw)
        if kind==10:return self.text(values[0])
        if kind==11:
            at,length=values
            if at+length>self.size-self.data:raise ValueError('UTF data reference out of bounds')
            return self.offset+self.data+at,length
        return values[0]


def cue_characters(name,known):
    """Only explicit NNname suffixes, including decoder aliases; no story ID guessing."""
    result=set()
    for alias in name.split('; '):
        alias=re.sub(r' \[pre\]$','',alias).lower()
        m=re.search(r'_(\d{2})[a-z][a-z0-9]*$',alias)
        if m and m[1] in known:result.add(m[1])
    return sorted(result)


def parse_cues(read,size):
    table=UtfTable(read,size)
    if table.name!='Header' or table.count!=1:raise ValueError('Expected ACB Header table')
    if 'CueNameTable' not in table.fields:raise ValueError('Missing ACB CueNameTable')
    offset,length=table.value(0,'CueNameTable')
    if not length:return []
    if length>4*1048576:raise ValueError('CueNameTable exceeds 4MiB limit')
    blob=read(offset,length)
    sub=UtfTable(lambda at,n:blob[at:at+n],len(blob))
    if not {'CueIndex','CueName'}<=sub.fields.keys():raise ValueError('Unknown CueNameTable schema')
    return [dict(cue_index=sub.value(i,'CueIndex'),cue_name=sub.value(i,'CueName')) for i in range(sub.count)]


_connections=threading.local()
class RangeReader:
    """Read only bounded metadata pages. A server ignoring Range is an error."""
    def __init__(self,entry,cache,stop=None):
        self.entry,self.size=entry,entry['size'];self.pages={};self.fetched=0
        self.local=Path(cache)/core.real_name(entry)
        if not self.local.is_file() or self.local.stat().st_size!=self.size:self.local=None
        if entry['resource_type']!=64:raise ValueError('Only plain raw ACB supports metadata range indexing')
        self.etag=None;self.stop=stop
    def __call__(self,offset,length):
        if offset<0 or length<0 or offset+length>self.size:raise ValueError('Metadata read outside ACB')
        if not length:return b''
        if self.local:
            with self.local.open('rb') as f:f.seek(offset);data=f.read(length)
            if len(data)!=length:raise ValueError('Truncated cached ACB')
            return data
        chunks=[];end=offset+length
        while offset<end:
            page=offset//4096;start=page*4096;count=min(4096,self.size-start)
            if page not in self.pages:
                if self.fetched+count>512*1024:raise ValueError('ACB metadata range budget exceeded')
                self.pages[page]=self.fetch(start,count);self.fetched+=count
            piece=self.pages[page][offset-start:min(end-start,count)];chunks.append(piece);offset+=len(piece)
        return b''.join(chunks)
    def fetch(self,start,length):
        url=urlsplit(core.CDN);filename=core.real_name(self.entry)
        path=url.path.rstrip('/')+'/'+filename[:2]+'/'+filename
        for attempt in range(4):
            if self.stop and self.stop.is_set():raise ValueError('Audio metadata indexing paused')
            conn=getattr(_connections,'conn',None)
            if conn is None:
                conn=http.client.HTTPSConnection(url.hostname,timeout=20);_connections.conn=conn
            try:
                conn.request('GET',path,headers={'Range':f'bytes={start}-{start+length-1}','Accept-Encoding':'identity'})
                response=conn.getresponse()
                if response.status in (429,500,502,503,504):
                    retry=response.getheader('Retry-After','');response.close();conn.close();_connections.conn=None
                    if attempt==3:raise ValueError('CDN metadata temporarily unavailable')
                    delay=min(30,float(retry) if retry.isdigit() else 2**attempt)
                    if self.stop:self.stop.wait(delay)
                    else:time.sleep(delay)
                    continue
                expected=f'bytes {start}-{start+length-1}/{self.size}'
                if response.status!=206 or response.getheader('Content-Range')!=expected:
                    response.close();conn.close();_connections.conn=None
                    raise ValueError('CDN did not honor bounded Range; no full-audio fallback')
                etag=response.getheader('ETag')
                if self.etag is not None and etag!=self.etag:raise ValueError('ACB changed during metadata read')
                self.etag=etag;data=response.read(length+1)
                if len(data)!=length:raise ValueError('Truncated metadata range')
                return data
            except (OSError,http.client.HTTPException):
                conn.close();_connections.conn=None
                if attempt==3:raise
                if self.stop:self.stop.wait(2**attempt)
                else:time.sleep(2**attempt)


def fingerprint(entry):
    return hashlib.sha256(json.dumps([PARSER_VERSION,entry['file'],entry['size'],entry['checksum'],entry['resource_type']],separators=(',',':')).encode()).hexdigest()


def read_bank(entry,cache,stop=None):
    reader=RangeReader(entry,cache,stop);cues=parse_cues(reader,entry['size'])
    return dict(schema=PARSER_VERSION,identity=fingerprint(entry),file=entry['file'],source_size=entry['size'],
                cues=cues,cue_count=len(cues),metadata_bytes_fetched=reader.fetched,
                source='local_cached_acb' if reader.local else 'cdn_http_range',
                full_file_sha256_verified=False)


def save_json(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.part');temp.write_text(json.dumps(data,ensure_ascii=False,separators=(',',':')),encoding='utf-8');temp.replace(path)


class AudioIndex:
    def __init__(self,catalog,root,cache):
        self.catalog,self.root,self.cache=catalog,Path(root),Path(cache)
        catalog.audio_indexer=self
        self.lock=threading.RLock();self.stop=threading.Event();self.worker=None
        self.records={};self.errors={};self.running=False;self.transferred=0
        self.entries=[e for e in catalog.entries if e['type']=='acb' and catalog.classifications[e['id']]['category']=='audio_story']
        version=hashlib.sha256((catalog.data['game_version']+'\n'+catalog.data['resource_version']).encode()).hexdigest()
        self.version_file=self.root/'versions'/(version+'.json')
        for e in self.entries:
            p=self.bank_path(e)
            if p.is_file():
                try:
                    r=json.loads(p.read_text('utf-8'))
                    if r['identity']==fingerprint(e):self.attach(e,r)
                except (OSError,ValueError,KeyError,TypeError):pass
    def bank_path(self,e):return self.root/'banks'/(fingerprint(e)+'.json')
    def attach(self,e,record):
        counts={};unknown=0;cues=[]
        for cue in record['cues']:
            roles=cue_characters(cue['cue_name'],self.catalog.character_names)
            if not roles:unknown+=1
            for role in roles:counts[role]=counts.get(role,0)+1
            cues.append(dict(cue,characters=[dict(id=k,name=self.catalog.character_names[k]) for k in roles]))
        tags=[dict(id=k,name=self.catalog.character_names[k],cue_count=v) for k,v in sorted(counts.items())]
        self.records[e['id']]=dict(record,cues=cues,characters=tags,unknown_cues=unknown)
        row=self.catalog.row_by_id[e['id']]
        row.update(audio_character_ids=sorted(counts),audio_characters=tags,audio_cue_count=record['cue_count'],audio_indexed=True,
                   audio_character_search=' '.join(t['name']+' '+t['name'].replace(' ','') for t in tags))
    def status(self):
        with self.lock:return dict(running=self.running,total=len(self.entries),indexed=len(self.records),failed=len(self.errors),
                                   metadata_bytes_fetched=self.transferred,complete=len(self.records)==len(self.entries),
                                   errors=[dict(id=k,error=v) for k,v in list(self.errors.items())[:20]])
    def persist(self):
        save_json(self.version_file,dict(game_version=self.catalog.data['game_version'],resource_version=self.catalog.data['resource_version'],
                                      parser_version=PARSER_VERSION,**self.status(),banks={k:v['identity'] for k,v in self.records.items()}))
    def start(self):
        with self.lock:
            if self.running:return self.status()
            self.stop.clear();self.running=True;self.errors={}
            self.worker=threading.Thread(target=self.run,daemon=True);self.worker.start();return self.status()
    def run(self):
        def one(e):
            if self.stop.is_set():return
            try:
                record=read_bank(e,self.cache,self.stop);save_json(self.bank_path(e),record)
                with self.lock:self.attach(e,record);self.transferred+=record['metadata_bytes_fetched']
            except Exception as exc:
                if not self.stop.is_set():
                    with self.lock:self.errors[e['id']]=str(exc)
        try:
            pending=[e for e in self.entries if e['id'] not in self.records]
            with ThreadPoolExecutor(max_workers=4) as pool:
                for offset in range(0,len(pending),32):
                    if self.stop.is_set():break
                    futures=[pool.submit(one,e) for e in pending[offset:offset+32]]
                    for f in as_completed(futures):f.result()
                    with self.lock:self.persist()
        finally:
            with self.lock:self.running=False;self.persist()
    def close(self):
        self.stop.set()
        if self.worker:self.worker.join(timeout=30)
        if self.worker and self.worker.is_alive():raise ValueError('角色索引仍在停止，请稍后重试')
    def bank(self,identity):
        with self.lock:
            if identity not in self.catalog.by_id:raise ValueError('Unknown audio resource')
            return self.records.get(identity)
