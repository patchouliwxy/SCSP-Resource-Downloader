"""Build GPT-SoVITS lists from exact original-game identifiers, without ASR."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
import os
from pathlib import Path
import re

from scsp_transcripts import cue_keys, localize, scenario, storylog, training_text, voice_resources


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def jsonl(path, rows):
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('w', encoding='utf-8', newline='\n') as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')
    temporary.replace(path)


def write_lists(folder, group, audio, absolute_paths=False):
    folder=Path(folder).resolve();audio=Path(audio).resolve()
    selected,all_matched=[],[]
    for r in group:
        if r['status']!='matched' or len(r['characters'])!=1:continue
        source=(audio/r['file']).resolve()
        if not source.is_relative_to(audio) or not source.is_file():
            raise ValueError('Missing/outside audio: '+str(source))
        value=source.as_posix() if absolute_paths else Path(os.path.relpath(source,folder)).as_posix()
        speaker=r['characters'][0]
        line=f'{value}|{speaker["id"]}_{speaker["name"]}|ja|{r["transcript"]}'
        all_matched.append(line)
        if not r['excluded_from_training']:selected.append(line)
    for name,lines in (('labels.list',selected),('labels.all-matched.list',all_matched)):
        target=folder/name;temporary=target.with_suffix('.list.tmp')
        temporary.write_text('\n'.join(lines)+ ('\n' if lines else ''),encoding='utf-8',newline='\n')
        temporary.replace(target)


def build_sources(decoded, receipt):
    exact, keys = defaultdict(list), defaultdict(list)
    errors = []
    for source in receipt['sources']:
        p = decoded / source['name']
        if hashlib.sha256(p.read_bytes()).hexdigest() != source['decoded_sha256']:
            raise ValueError('Changed original-text source: ' + p.name)
    def evidence(text, source, key, kind):
        return dict(text=text, source=source, key=key, kind=kind)
    for source in receipt['sources']:
        name = source['name']
        data = (decoded / name).read_bytes()
        try:
            if name.endswith('_storylog.bytes'):
                for row in storylog(data):
                    if row['cue'] and row['text']:
                        exact[row['cue']].append(evidence(row['text'], name, row['cue'], 'storylog_exact_cue'))
            elif name.endswith('.json'):
                for row in scenario(data):
                    if re.fullmatch(r'SCENARIO_s\d{2}_\d+_\d+_\d+', row['key']):
                        keys[row['key']].append(evidence(row['text'], name, row['key'], 'scenario_exact_line_key'))
        except (ValueError, UnicodeError) as ex:
            errors.append(dict(source=name, error=str(ex)))
    texts = localize((decoded/'localizetext.bytes').read_bytes())
    voices = voice_resources((decoded/'masterdata.bytes').read_bytes(), texts['mlVoiceResource_Text'])
    for row in voices:
        if row['text']:
            item = evidence(row['text'], 'masterdata.bytes + localizetext.bytes',
                f'mlVoiceResource_Text:{row["id"]}', 'master_exact_cue')
            item['cue_sheet'] = row['sheet']
            exact[row['cue']].append(item)
    return exact, keys, errors, len(voices)


def match(name, exact, keys, bank=None):
    direct, indirect = [], []
    for alias, key in cue_keys(name):
        direct.extend(e for e in exact.get(alias, []) if 'cue_sheet' not in e
                      or (bank is not None and e['cue_sheet'].casefold() == Path(bank).stem.casefold()))
        indirect.extend(keys.get(key, []))
    # Explicit complete CueName links are stronger than scenario-number keys;
    # some shipped scenario JSONs are stale templates. Keep disagreements visible.
    candidates = direct or indirect
    texts = {training_text(e['text']) for e in candidates if training_text(e['text'])}
    if len(texts) != 1:
        return dict(status='conflict' if texts else 'unmatched', transcript=None,
                    evidence=candidates)
    text = texts.pop()
    disagreement = [e for e in indirect if training_text(e['text']) != text] if direct else []
    if ('|' in text or any(c in text for c in '<>{}') or '\ufffd' in text
            or text.lower() in ('motion', 'camera', 'coming soon')
            or not re.search(r'[\u3040-\u30ff\u3400-\u9fffA-Za-z0-9]', text)):
        return dict(status='non_speech_or_markup', transcript=text,
                    evidence=candidates, lower_priority_disagreements=disagreement)
    return dict(status='matched', transcript=text, evidence=candidates,
                lower_priority_disagreements=disagreement)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--audio', type=Path, required=True)
    p.add_argument('--sources', type=Path, required=True)
    p.add_argument('--decoded', type=Path, required=True)
    p.add_argument('--absolute-paths', action='store_true', help='显式导出当前电脑的绝对路径；默认相对每个list文件')
    args = p.parse_args()
    audio = args.audio.resolve()
    receipt = json.loads(args.sources.read_text('utf-8'))
    pin = json.loads((audio/'_state/catalog.json').read_text('utf-8'))
    if receipt.get('errors') or any(receipt[k] != pin[k] for k in ('game_version','resource_version')):
        raise ValueError('Incomplete sources or different corpus/source version')
    exact, keys, errors, voice_count = build_sources(args.decoded, receipt)
    originals = [json.loads(s) for s in (audio/'manifest.jsonl').read_text('utf-8').splitlines()]
    output = audio/'annotations'
    output.mkdir(exist_ok=True)
    groups = defaultdict(list)
    rows, used_pcm, all_lines, selected_lines = [], set(), [], []
    for original in originals:
        file = (audio/original['file']).resolve()
        if not file.is_relative_to(audio) or not file.is_file() or file.stat().st_size != original['bytes']:
            raise ValueError('Missing/changed audio: ' + str(file))
        annotation = match(original['track_name'], exact, keys, original['resource'])
        row = dict(original, **{k:v for k,v in annotation.items() if k != 'transcript'})
        row['transcript'] = annotation['transcript']
        row['language'] = 'ja'
        row['excluded_from_training'] = []
        if row['status'] != 'matched':
            row['excluded_from_training'].append(row['status'])
        if len(row['characters']) != 1:
            row['excluded_from_training'].append('unknown_or_multiple_speakers')
        if row['training_review_required']:
            row['excluded_from_training'].append('audio_review_required')
        identity = (row['characters'][0]['id'] if len(row['characters']) == 1 else None,
                    row['pcm_sha256'])
        if identity in used_pcm:
            row['excluded_from_training'].append('duplicate_pcm_within_speaker')
        if row['status'] == 'matched' and len(row['characters']) == 1:
            speaker = row['characters'][0]['id'] + '_' + row['characters'][0]['name']
            line = f'{file.as_posix()}|{speaker}|ja|{row["transcript"]}'
            all_lines.append(line)
            if not row['excluded_from_training']:
                selected_lines.append(line)
                used_pcm.add(identity)
        groups[Path(row['file']).parts[0]].append(row)
        rows.append(row)
    jsonl(output/'annotations.jsonl', rows)
    jsonl(output/'unmatched-and-review.jsonl', [r for r in rows if r['excluded_from_training']])
    for folder, group in groups.items():
        jsonl(audio/folder/'annotations.jsonl', group)
        write_lists(audio/folder, group, audio, args.absolute_paths)
    write_lists(output, rows, audio, args.absolute_paths)
    stats = dict(game_version=pin['game_version'], resource_version=pin['resource_version'],
                 total_audio=len(rows), matched=sum(r['status']=='matched' for r in rows),
                 training_list_lines=len(selected_lines), matched_known_speaker_lines=len(all_lines),
                 status_counts=dict(Counter(r['status'] for r in rows)),
                 explicit_cue_overrode_scenario=sum(bool(r.get('lower_priority_disagreements')) for r in rows),
                 source_files=len(receipt['sources']), master_voice_records=voice_count,
                 source_parse_errors=errors,
                 by_character={k:dict(total=len(g),matched=sum(r['status']=='matched' for r in g),
                     training=sum(not r['excluded_from_training'] for r in g)) for k,g in groups.items()},
                 unmatched_families=dict(Counter(r['track_name'].split('_')[0] for r in rows if r['status']=='unmatched')),
                 human_listening_verified=False, asr_used=False)
    dump(output/'summary.json', stats)
    dump(output/'text-sources.json', receipt)
    (output/'README.md').write_text(
        '# GPT-SoVITS 原始台词自动标注\n\n'
        'labels.list 为已匹配、单角色、排除已标记音频问题及同角色重复 PCM 的标准四列标注。\n'
        'labels.all-matched.list 保留全部已匹配单角色条目（含重复及需检查音频）。\n'
        '格式：音频路径|角色编号及日语名|ja|台词。UTF-8，无 BOM。默认相对于当前list所在目录；显式--absolute-paths可导出绝对路径。\n'
        '每个角色目录也有以上两个 list 和 annotations.jsonl；全局 annotations.jsonl 包含全部音频及证据。\n'
        '未匹配/冲突/未知角色不补写、不做 ASR、不按行序猜测。unmatched-and-review.jsonl 记录未纳入训练清单的原因。\n'
        '完整 CueName（StoryLog/主表）优先于剧情行号，所有较低优先级分歧保留在证据字段。\n'
        '换行与排版空白合并为空格，原文在 evidence.text 中保留。\n'
        '原 manifest 和 WAV 均保留；原 manifest 的 transcript=null 仍是导出时的原始状态，请读取 annotations.jsonl。\n'
        '尚未逐条听音核对、筛掉背景音乐或按训练时长切片；这不是人工验收后的训练集。\n'
        '默认相对路径模式下，连同WAV保持目录结构一起移动即可；训练工具需按list所在目录解析路径。\n', encoding='utf-8')
    print(json.dumps({k:v for k,v in stats.items() if k not in ('by_character','source_parse_errors')}, ensure_ascii=True))


if __name__ == '__main__':
    main()
