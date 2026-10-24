"""Decode downloaded ACB/AWB tracks to independent PCM WAV files."""
import argparse
import json
from pathlib import Path
import subprocess
import wave

from scsp_anim_export import digest
from scsp_audio_index import cue_characters

from runtime_paths import app_root
ROOT = app_root()
DECODER = ROOT / 'tools/vgmstream/r2117/vgmstream-cli.exe'


def export_audio(sample, progress=lambda text: None):
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
        inputs.append((path, entries[item['file']]['name']))
    report = dict(decoder='vgmstream r2117', files=[])
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

    for path, resource in inputs:
        if path.suffix.lower() == '.awb' and path.with_suffix('.acb').is_file():
            continue  # The paired ACB enumerates its AWB tracks.
        info = json.loads(run(['-m', '-I', str(path)]))
        count = info.get('streamInfo', {}).get('total', 1) or 1
        if not 1 <= count <= 10000:
            raise ValueError('Unsupported audio track count')
        for number in range(1, count + 1):
            progress(f'正在转WAV：{resource} · 音轨 {number}/{count}')
            target = output / (path.stem + (f'_track{number:02}' if count > 1 else '') + '.wav')
            if target.exists():
                raise ValueError('不覆盖已有WAV：' + str(target))
            track = json.loads(run(['-m', '-I', '-s', str(number), str(path)]))
            run(['-i', '-W', '1', '-s', str(number), '-o', str(target), str(path)])
            with wave.open(str(target), 'rb') as wav:
                rate, channels, frames = wav.getframerate(), wav.getnchannels(), wav.getnframes()
                if wav.getsampwidth() != 2 or rate != track['sampleRate'] or frames != track['numberOfSamples']:
                    raise ValueError('WAV format or duration mismatch: ' + target.name)
                nonzero = False
                while block := wav.readframes(65536):
                    nonzero |= any(block)
            report['files'].append(dict(file=target.relative_to(sample).as_posix(), resource=resource,
                track=number, track_name=track.get('streamInfo', {}).get('name', ''),
                characters=[dict(id=k,name=character_names[k]) for k in cue_characters(track.get('streamInfo', {}).get('name', ''),character_names)],
                sample_rate=rate, channels=channels, frames=frames, duration=frames / rate,
                non_silent=nonzero, bytes=target.stat().st_size, sha256=digest(target)))
    (output / 'export-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sample', type=Path)
    args = parser.parse_args()
    print(json.dumps(export_audio(args.sample, print), ensure_ascii=False, indent=2))
