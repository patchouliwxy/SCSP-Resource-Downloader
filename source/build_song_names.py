"""Extract official song text and version-specific MstSong identity records."""
import json
import re
import struct
from pathlib import Path

from runtime_paths import app_root
ROOT = app_root()


def read_text_tables(data):
    position = 0

    def integer():
        nonlocal position
        value = struct.unpack_from('<i', data, position)[0]
        position += 4
        return value

    def string():
        nonlocal position
        length = integer()
        if length == -1:
            return None
        if length < 0 or position + length * 2 > len(data):
            raise ValueError('Unsupported or truncated UTF-16 text')
        value = data[position:position + length * 2].decode('utf-16-le')
        position += length * 2
        return value

    tables = {}
    for _ in range(integer()):
        name, values = string(), {}
        for _ in range(integer()):
            key = integer()
            if key in values:
                raise ValueError('Duplicate localization ID')
            values[key] = string()
        if name in tables:
            raise ValueError('Duplicate localization table')
        tables[name] = values
    if position != len(data):
        raise ValueError('Unconsumed localization bytes')
    return tables


def song_records(data):
    # 2.18.0 MstSong: 23 fields, Id then UTF-8 MvScene. This is a
    # bounded identity extraction, not a complete MasterData decoder.
    result = {}
    for match in re.finditer(rb'(?=\d{3}_[A-Za-z])', data):
        offset = match.start()
        if offset < 13 or data[offset - 13] != 23:
            continue
        identity, encoded_length, characters = struct.unpack_from('<iii', data, offset - 12)
        length = ~encoded_length
        if not 1 <= length <= 100 or characters != length:
            continue
        code = data[offset:offset + length].decode('ascii', errors='replace').lower()
        if not re.fullmatch(r'\d{3}_[a-z0-9]+', code) or identity != int(code[:3]):
            continue
        result[code] = identity
    return result


def build(index, tables, master):
    records = song_records(master)
    songs = {}
    for code, identity in records.items():
        title = tables['mlMusic_Name'].get(identity)
        if title:
            songs[code] = dict(id=identity, title=title,
                              artist=tables['mlMusic_Artist'].get(identity, ''),
                              reading=tables['mlMusic_ReadName'].get(identity, ''))
    return dict(game_version=index['game_version'], resource_version=index['resource_version'],
                source='official masterdata.bytes MstSong + localizetext.bytes mlMusic',
                identity_records=len(records), localized_songs=len(songs), songs=songs)


if __name__ == '__main__':
    index = json.loads((ROOT / 'official-current-index.json').read_text(encoding='utf-8'))
    source = ROOT / 'song-names-source/raw/root/raw'
    report = build(index, read_text_tables((source / 'localizetext.bytes').read_bytes()),
                   (source / 'masterdata.bytes').read_bytes())
    (ROOT / 'song-names.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Official names: {report["localized_songs"]} / {report["identity_records"]} song identities')
