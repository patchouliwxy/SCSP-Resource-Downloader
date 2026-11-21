import threading
import time
import unittest
from unittest.mock import patch

import scsp_download as core
from scsp_task_transfer import fetch_task


def entries(count):
    return [dict(name=str(index), size=1) for index in range(count)]


class ParallelTransferTests(unittest.TestCase):
    def test_three_requests_overlap_but_commits_use_the_task_thread(self):
        caller = threading.get_ident()
        barrier = threading.Barrier(3, timeout=5)
        committed = []
        progress = {}

        def fetch(entry, cache):
            barrier.wait()
            core.transfer_event('received', bytes=1)
            core.transfer_event('downloaded', bytes=1)
            return entry['name'].encode()

        def accept(entry, data):
            self.assertEqual(threading.get_ident(), caller)
            self.assertEqual(entry['name'].encode(), data)
            committed.append(entry['name'])

        with patch.object(core, 'get_file', side_effect=fetch):
            fetch_task(entries(6), None, lambda: False, lambda **fields: progress.update(fields), accept)
        self.assertCountEqual(committed, map(str, range(6)))
        self.assertEqual((progress['network_bytes'], progress['downloaded_files']), (6, 6))

    def test_throttle_delays_later_requests_and_reduces_parallelism(self):
        launch = threading.Barrier(3, timeout=5)
        throttled = threading.Event()
        timings = {}
        remaining = []
        lock = threading.Lock()

        def fetch(entry, cache):
            index = int(entry['name'])
            if index < 3:
                launch.wait()
                if index == 0:
                    timings['retry_at'] = time.monotonic() + .075
                    core.transfer_event('throttled', delay=.075)
                    throttled.set()
                elif not throttled.wait(5):
                    raise TimeoutError('Expected throttling signal')
            else:
                # Production get_file calls this gate immediately before an HTTP request.
                core._transfer_local.before_request()
                with lock:
                    remaining.append(index)
                    self.assertEqual(len(remaining), 1)
                self.assertGreaterEqual(time.monotonic(), timings['retry_at'])
                time.sleep(.02)
                with lock:
                    remaining.remove(index)
            return b'x'

        with patch.object(core, 'get_file', side_effect=fetch):
            fetch_task(entries(6), None, lambda: False, lambda **fields: None, lambda *_: None)

    def test_cancel_stops_dispatch_and_leaves_completed_inputs_available(self):
        stop = threading.Event()
        barrier = threading.Barrier(3, timeout=5)
        committed = []

        def fetch(entry, cache):
            barrier.wait()
            stop.set()
            return b'x'

        with patch.object(core, 'get_file', side_effect=fetch) as get:
            fetch_task(entries(6), None, stop.is_set, lambda **fields: None,
                       lambda entry, data: committed.append(entry['name']))
        self.assertEqual(get.call_count, 3)
        self.assertCountEqual(committed, ['0', '1', '2'])
