"""Decode downloaded ACB/AWB tracks to independent PCM WAV files."""
import argparse
import json
from pathlib import Path
import subprocess
import wave
import shutil
import hashlib
import scsp_download as core

from scsp_anim_export import digest
from scsp_audio_index import cue_characters

from runtime_paths import app_root
ROOT = app_root()
DECODER = ROOT / 'tools/vgmstream/r2117/vgmstream-cli.exe'


def export_audio(sample, progress=lambda text: None, *, preview=False, track_numbers=None):
    sample = Path(sample).resolve()
    manifest = json.loads((sample / 'manifest.json').read_text(encoding='utf-8'))
    entries = {e['file']: e for e in manifest['entries']}
    character_names = {}
    character_path = ROOT / 'character-data.json'
    if character_path.is_file():
        character_data = json.loads(character_path.read_text(encoding='utf-8'))
        if (manifest.get('game_version'), manifest.get('resource_version')) == (character_data.get('game_version'), character_data.get('resource_version')):
            character_names = character_data['characters']
    inputs = []
    for item in manifest['outputs']:
        if entries[item['file']]['type'] not in ('acb', 'awb'):
            continue
        path = (sample / item['output']).resolve()
        if not path.is_relative_to(sample) or digest(path) != item['sha256']:
            raise ValueError('Audio input path or hash mismatch')
        resource=entries[item['file']]['name']
        # Downloaded bundles use hashes; external AWB discovery needs original
        # bank names side by side. Keep source folders to avoid cross-bank pairing.
        prepared=core.safe_output(sample/'audio-export-work/source',resource)
        prepared.parent.mkdir(parents=True,exist_ok=True)
        if not prepared.exists():shutil.copy2(path,prepared)
        elif digest(prepared)!=item['sha256']:raise ValueError('音频配套准备文件哈希不一致')
        inputs.append((prepared,resource))
    report = dict(decoder='vgmstream r2117', files=[], tracks=[])
    if not inputs:
        return report
    if not DECODER.is_file():
        raise RuntimeError('未找到vgmstream，无法导出WAV')
    output = sample / 'audio'
    output.mkdir(exist_ok=True)
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

    def run(args):
        result = subprocess.run([str(DECODER), *args], capture_output=True,
                                timeout=300, creationflags=flags)
        if result.returncode:
            raise RuntimeError('音频解码失败：' + result.stderr.decode('utf-8', errors='replace')[-2000:])
        return result.stdout

    inputs.sort(key=lambda item:(item[0].suffix.lower()!='.awb',item[1]))
    stems=[p.stem.casefold() for p,_ in inputs]
    track_offset=0
    for path, resource in inputs:
        info = json.loads(run(['-m', '-I', str(path)]))
        count = info.get('streamInfo', {}).get('total', 1) or 1
        if not 1 <= count <= 10000:
            raise ValueError('Unsupported audio track count')
        for number in range(1, count + 1):
            identity=track_offset+number
            if track_numbers is not None and identity not in track_numbers: continue
            progress(f'正在转WAV：{resource} · 音轨 {number}/{count}')
            stem=path.stem+('_'+path.suffix[1:].lower() if stems.count(path.stem.casefold())>1 else '')
            if sum(Path(r).name.casefold()==Path(resource).name.casefold() for _,r in inputs)>1:
                stem+='_'+hashlib.sha256(resource.encode()).hexdigest()[:8]
            target = output/(stem + (f'_track{number:02}' if count > 1 else '') + '.wav')
            target.parent.mkdir(parents=True,exist_ok=True)
            if target.exists() and not preview:
                raise ValueError('不覆盖已有WAV：' + str(target))
            track = json.loads(run(['-m', '-I', '-s', str(number), str(path)]))
            name=track.get('streamInfo',{}).get('name','')
            metadata=dict(file=target.relative_to(sample).as_posix(),resource=resource,track=identity,source_track=number,track_name=name,
                characters=[dict(id=k,name=character_names[k]) for k in cue_characters(name,character_names)],
                sample_rate=track['sampleRate'],channels=track.get('channels',track.get('channelCount',0)),
                duration=track['numberOfSamples']/track['sampleRate'])
            report['tracks'].append(metadata)
            if preview and track_numbers is None and report['files']: continue
            if not target.exists():
                temporary=target.with_suffix('.wav.part')
                try:
                    run(['-i', '-W', '1', '-s', str(number), '-o', str(temporary), str(path)])
                    temporary.replace(target)
                finally: temporary.unlink(missing_ok=True)
            with wave.open(str(target), 'rb') as wav:
                rate, channels, frames = wav.getframerate(), wav.getnchannels(), wav.getnframes()
                if wav.getsampwidth() != 2 or rate != track['sampleRate'] or frames != track['numberOfSamples']:
                    raise ValueError('WAV format or duration mismatch: ' + target.name)
                nonzero = False
                while block := wav.readframes(65536):
                    nonzero |= any(block)
            report['files'].append(dict(file=target.relative_to(sample).as_posix(), resource=resource,
                track=identity, source_track=number, track_name=track.get('streamInfo', {}).get('name', ''),
                characters=[dict(id=k,name=character_names[k]) for k in cue_characters(track.get('streamInfo', {}).get('name', ''),character_names)],
                sample_rate=rate, channels=channels, frames=frames, duration=frames / rate,
                non_silent=nonzero, bytes=target.stat().st_size, sha256=digest(target)))
        track_offset+=count
    (output / 'export-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sample', type=Path)
    args = parser.parse_args()
    print(json.dumps(export_audio(args.sample, print), ensure_ascii=False, indent=2))
