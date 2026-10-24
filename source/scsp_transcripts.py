"""Strict original-text readers; never align dialogue by row position."""
import json
import re
import struct


class MemoryReader:
    def __init__(self, data):
        self.data, self.pos = data, 0

    def take(self, n):
        if n < 0 or self.pos + n > len(self.data):
            raise ValueError('Truncated MemoryPack')
        b = self.data[self.pos:self.pos+n]
        self.pos += n
        return b

    def integer(self):
        return struct.unpack('<i', self.take(4))[0]

    def count(self):
        n = self.integer()
        if not 0 <= n <= 2000000:
            raise ValueError('Invalid collection count')
        return n

    def string(self):
        n = self.integer()
        if n == -1:
            return None
        if n >= 0:
            return self.take(n * 2).decode('utf-16-le')
        utf16_length = self.integer()
        result = self.take(~n).decode('utf-8')
        if len(result.encode('utf-16-le')) // 2 != utf16_length:
            raise ValueError('String length mismatch')
        return result

    def end(self):
        if self.pos != len(self.data):
            raise ValueError(f'Unconsumed bytes: {len(self.data)-self.pos}')


def localize(data):
    r = MemoryReader(data)
    result = {}
    for _ in range(r.count()):
        name = r.string()
        if name in result:
            raise ValueError('Duplicate localization table')
        values = {}
        for _ in range(r.count()):
            key = r.integer()
            if key in values:
                raise ValueError('Duplicate localization key')
            values[key] = r.string()
        result[name] = values
    r.end()
    return result


def storylog(data):
    r = MemoryReader(data)
    if r.take(1) != b'\x01':
        raise ValueError('Unknown StoryLog root member count')
    result = []
    for _ in range(r.count()):
        if r.take(1) != b'\x06':
            raise ValueError('Unknown StoryLog entry member count')
        text, speaker, cue = r.string(), r.string(), r.string()
        number = r.integer()
        time = struct.unpack('<d', r.take(8))[0]
        flag = r.take(1)
        if flag not in (b'\x00', b'\x01'):
            raise ValueError('Invalid StoryLog boolean')
        result.append(dict(text=text, speaker=speaker, cue=cue,
                           number=number, time=time, flag=bool(flag[0])))
    r.end()
    return result


def voice_resources(data, texts):
    """Locate a complete MstVoiceResource table, validate every localized ID.

    Schema is Id, CueSheetName, CueName (3 MemoryPack members), also declared
    in the pinned PrismCatalogDownloader reference's PrismDefinitions.cs.
    No substring-to-text pairing is accepted: the entire table must validate.
    """
    ids = set(texts)
    signature = struct.pack('<iBi', len(ids), 3, min(ids))
    valid = []
    for match in re.finditer(re.escape(signature), data):
        r = MemoryReader(data)
        r.pos = match.start() + 4
        rows = {}
        try:
            for _ in range(len(ids)):
                if r.take(1) != b'\x03':
                    raise ValueError('VoiceResource layout changed')
                identity = r.integer()
                sheet, cue = r.string(), r.string()
                if identity not in ids or identity in rows or not sheet or not cue:
                    raise ValueError('VoiceResource identity mismatch')
                rows[identity] = dict(id=identity, sheet=sheet, cue=cue,
                                      text=texts[identity])
            if set(rows) == ids:
                valid.append(list(rows.values()))
        except (ValueError, UnicodeError, struct.error):
            continue
    if len(valid) != 1:
        raise ValueError('Cannot uniquely validate complete VoiceResource table')
    return valid[0]


def scenario(data):
    # Game-generated text arrays may contain a trailing comma before final ].
    s = data.decode('utf-8-sig').strip()
    # Some official strings contain literal newlines/tabs instead of escapes.
    rows = json.loads(re.sub(r',\s*]$', ']', s), strict=False)
    if not isinstance(rows, list) or not all(
            isinstance(row, dict) and isinstance(row.get('key'), str)
            and isinstance(row.get('text'), str) for row in rows):
        raise ValueError('Not a scenario text array')
    return rows


def cue_keys(name):
    aliases = [re.sub(r' \[pre\]$', '', a.strip()) for a in name.split('; ')]
    return [(alias, 'SCENARIO_' + re.sub(r'_\d{2}[a-z][a-z0-9]*$', '', alias))
            for alias in aliases]


def training_text(text):
    # Preserve spoken characters; replace layout line breaks with spaces.
    return re.sub(r'\s+', ' ', text).strip()
