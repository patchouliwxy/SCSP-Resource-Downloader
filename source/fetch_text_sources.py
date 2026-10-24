import concurrent.futures
import argparse
import hashlib
import http.client
import json
from pathlib import Path
import re
import sys
import threading
import time
from urllib.parse import urlsplit

import scsp_download as core

SOURCE = Path(__file__).resolve().parent
ROOT = SOURCE / 'text-sources'
CATALOG = SOURCE / 'official-current-index.json'
SHARED = SOURCE / '.scsp-cache'
LOCAL = threading.local()


def fetch(e):
    name = core.real_name(e)
    target = ROOT / 'cache' / name
    raw = None
    for p in (target, SHARED / name):
        if p.is_file() and p.stat().st_size == e['size']:
            candidate = p.read_bytes()
            if not e.get('sha256') or hashlib.sha256(candidate).hexdigest() == e['sha256']:
                raw = candidate
                break
    if raw is None:
        u = urlsplit(core.CDN)
        for attempt in range(6):
            conn = getattr(LOCAL, 'conn', None)
            if conn is None:
                conn = http.client.HTTPSConnection(u.hostname, timeout=40)
                LOCAL.conn = conn
            try:
                conn.request('GET', f'{u.path}/{name[:2]}/{name}', headers={'Accept-Encoding':'identity'})
                response = conn.getresponse()
                if response.status != 200:
                    raise OSError(f'HTTP {response.status}')
                raw = response.read(e['size'] + 1)
                if len(raw) != e['size']:
                    raise OSError('Wrong file size')
                if e.get('sha256') and hashlib.sha256(raw).hexdigest() != e['sha256']:
                    raise ValueError('Authoritative SHA mismatch')
                target.write_bytes(raw)
                break
            except (OSError, http.client.HTTPException):
                conn.close()
                LOCAL.conn = None
                if attempt == 5:
                    raise
                time.sleep(min(30, 2 ** attempt))
    data = core.decode_asset(e, raw)
    (ROOT / 'decoded' / e['name']).write_bytes(data)
    return dict(name=e['name'], id=e['id'], file=name, bytes=len(raw),
                sha256=hashlib.sha256(raw).hexdigest(),
                decoded_sha256=hashlib.sha256(data).hexdigest(),
                authoritative_sha256_verified=bool(e.get('sha256')))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Fetch only version-matched original dialogue text sources')
    parser.add_argument('--index', type=Path, default=CATALOG)
    parser.add_argument('--audio', type=Path, default=SOURCE.parent/'audio')
    parser.add_argument('--work', type=Path, default=ROOT)
    parser.add_argument('--shared-cache', type=Path, default=SHARED)
    args = parser.parse_args()
    ROOT, CATALOG, SHARED = args.work.resolve(), args.index.resolve(), args.shared_cache.resolve()
    ROOT.mkdir(parents=True, exist_ok=True)
    c = json.loads(CATALOG.read_text('utf-8'))
    pin = json.loads((args.audio/'_state/catalog.json').read_text('utf-8'))
    if any(c[k] != pin[k] for k in ('game_version', 'resource_version')):
        raise ValueError('Audio corpus and text catalog versions differ')
    entries = [e for e in c['entries'] if re.fullmatch(r's\d{2}_\d+_\d+\.json', e['name'])
               or e['name'].endswith('_storylog.bytes')
               or e['name'] in ('localizetext.bytes', 'masterdata.bytes')]
    if sum(e['size'] for e in entries) >= 20*1024*1024:
        raise ValueError('Unexpected text-source size, review selection before fetching')
    for d in ('cache', 'decoded'):
        (ROOT/d).mkdir(exist_ok=True)
    print(f'SOURCES {len(entries)} BYTES {sum(e["size"] for e in entries)}', flush=True)
    results, errors = [], []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        jobs = {pool.submit(fetch,e):e for e in entries}
        for f in concurrent.futures.as_completed(jobs):
            e = jobs[f]
            try:
                results.append(f.result())
            except Exception as ex:
                errors.append(dict(name=e['name'], error=str(ex)))
            if (len(results)+len(errors)) % 250 == 0:
                print(f'PROGRESS {len(results)} OK {len(errors)} FAILED', flush=True)
    (ROOT/'sources.json').write_text(json.dumps(dict(
        game_version=c['game_version'], resource_version=c['resource_version'],
        sources=results, errors=errors), ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'COMPLETE {len(results)} OK {len(errors)} FAILED', flush=True)
    if errors:
        sys.exit(1)
