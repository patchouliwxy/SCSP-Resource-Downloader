"""Convert existing lists without relabelling, redownloading or touching WAV."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil


def convert(audio):
    audio=Path(audio).resolve();plans=[];checked=0
    for folder in [audio]+sorted(p for p in audio.iterdir() if p.is_dir() and p.name!='_state'):
        for name in ('labels.list','labels.all-matched.list'):
            path=folder/name
            if not path.is_file():continue
            lines=[]
            for n,line in enumerate(path.read_text('utf-8-sig').splitlines(),1):
                if not line.strip():continue
                parts=line.split('|',3)
                if len(parts)!=4:raise ValueError(f'{path}:{n}: 不是标准四列')
                source=Path(parts[0]);source=(source if source.is_absolute() else folder/source).resolve()
                if not source.is_relative_to(audio) or not source.is_file():
                    raise ValueError(f'{path}:{n}: 音频缺失或超出根目录：{source}')
                parts[0]=Path(os.path.relpath(source,folder)).as_posix()
                lines.append('|'.join(parts));checked+=1
            data=('\n'.join(lines)+ ('\n' if lines else '')).encode('utf-8')
            if data!=path.read_bytes():plans.append((path,data))
    backup=audio/'_state/list-path-backups'/datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    for path,data in plans:
        saved=backup/path.relative_to(audio);saved.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(path,saved)
    for path,data in plans:
        temporary=path.with_suffix('.list.tmp');temporary.write_bytes(data);temporary.replace(path)
    report=dict(changed_files=len(plans),checked_lines=checked,backup=str(backup) if plans else None,
        original_audio_modified=False,files=[dict(path=str(p),sha256=hashlib.sha256(data).hexdigest()) for p,data in plans])
    if plans:(backup/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--audio',required=True)
    print(json.dumps(convert(p.parse_args().audio),ensure_ascii=False,indent=2))
