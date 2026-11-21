"""Bounded network transfers for a single Web download task."""
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import threading
import time

import scsp_download as core

WORKERS = 3
IN_FLIGHT_BYTES = 64 * 1024 * 1024


def fetch_task(entries, cache, canceled, progress, accept):
    """Fetch in workers. Keep file commits and progress on the calling thread."""
    metrics = dict(cached_files=0, cached_bytes=0, network_bytes=0, downloaded_files=0, retry_count=0)
    lock = threading.Lock()
    stopping = threading.Event()
    deadline = 0.0
    serial_after_throttle = False
    activity = {}
    started = time.monotonic()
    last_report = 0.0

    def report(force=False):
        nonlocal last_report
        now = time.monotonic()
        if force or now - last_report >= .25:
            with lock:
                snapshot = {**metrics, **activity}
            snapshot['speed_bps'] = snapshot['network_bytes'] / max(.001, now - started)
            progress(**snapshot)
            last_report = now

    def gate():
        while not stopping.is_set():
            with lock:
                remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            stopping.wait(remaining)
        raise core.DownloadError('下载已停止')

    def fetch(entry):
        def observe(kind, details):
            nonlocal deadline, serial_after_throttle
            with lock:
                if kind == 'cache':
                    metrics['cached_files'] += 1
                    metrics['cached_bytes'] += details['bytes']
                elif kind == 'received':
                    metrics['network_bytes'] += details['bytes']
                elif kind == 'downloaded':
                    metrics['downloaded_files'] += 1
                elif kind == 'retry':
                    metrics['retry_count'] += 1
                    activity['current'] = f"重试 {details['attempt']}/{details['max_attempts']} · {entry['name']}"
                elif kind == 'throttled':
                    deadline = max(deadline, time.monotonic() + details['delay'])
                    serial_after_throttle = True
        with core.transfer_observer(observe, gate):
            return core.get_file(entry, cache)

    pending = iter(entries)
    next_entry = next(pending, None)
    active = {}
    in_flight = 0
    failure = None
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        try:
            while active or next_entry is not None:
                if canceled():
                    stopping.set()
                with lock:
                    limit = 1 if serial_after_throttle else WORKERS
                while not stopping.is_set() and next_entry is not None and len(active) < limit:
                    size = next_entry['size']
                    if active and in_flight + size > IN_FLIGHT_BYTES:
                        break
                    with lock:
                        if deadline <= time.monotonic():
                            activity.update(current=next_entry['name'], resource_name=next_entry['name'])
                    active[pool.submit(fetch, next_entry)] = next_entry
                    in_flight += size
                    next_entry = next(pending, None)
                if not active:
                    break
                report()
                done, _ = wait(active, timeout=.25, return_when=FIRST_COMPLETED)
                for future in done:
                    entry = active.pop(future)
                    in_flight -= entry['size']
                    try:
                        data = future.result()
                        accept(entry, data)
                    except Exception as exc:
                        if failure is None and not canceled():
                            failure = exc
                        stopping.set()
                # Release the completed futures' buffers before starting more requests.
                data = future = None
                done.clear()
        finally:
            stopping.set()
            report(force=True)
    if failure:
        raise failure
