import hashlib
import http.client
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

import scsp_download as core


class RetryTests(unittest.TestCase):
    def info(self):
        return dict(name='fixture.bundle',file='unused',label='fixture',size=4,
            checksum=1,seed=0,label_crc=1,resource_type=64,sha256=hashlib.sha256(b'data').hexdigest())

    def test_remote_disconnect_retries_and_completed_cache_is_reused(self):
        with tempfile.TemporaryDirectory() as t, patch.object(core.urllib.request,'urlopen',side_effect=[http.client.RemoteDisconnected('closed'),io.BytesIO(b'data')]) as get,patch.object(core.time,'sleep') as sleep:
            self.assertEqual(b'data',core.get_file(self.info(),Path(t)))
            self.assertEqual(b'data',core.get_file(self.info(),Path(t)))
            self.assertEqual(2,get.call_count);sleep.assert_called_once_with(.5)

    def test_short_read_retries_and_partial_is_never_cached(self):
        with tempfile.TemporaryDirectory() as t,patch.object(core.urllib.request,'urlopen',side_effect=[io.BytesIO(b'x'),io.BytesIO(b'data')]),patch.object(core.time,'sleep'):
            self.assertEqual(b'data',core.get_file(self.info(),Path(t)))
            self.assertEqual([b'data'],[f.read_bytes() for f in Path(t).iterdir()])

    def test_404_is_not_retried(self):
        error=urllib.error.HTTPError('https://fixture',404,'missing',{},None)
        with tempfile.TemporaryDirectory() as t,patch.object(core.urllib.request,'urlopen',side_effect=error) as get,patch.object(core.time,'sleep') as sleep:
            with self.assertRaisesRegex(core.DownloadError,'HTTP 404'):core.get_file(self.info(),Path(t))
            self.assertEqual(1,get.call_count);sleep.assert_not_called()

    def test_rate_limit_respects_bounded_retry_after(self):
        error=urllib.error.HTTPError('https://fixture',429,'slow',{'Retry-After':'3'},None)
        with tempfile.TemporaryDirectory() as t,patch.object(core.urllib.request,'urlopen',side_effect=[error,io.BytesIO(b'data')]),patch.object(core.time,'sleep') as sleep:
            core.get_file(self.info(),Path(t));sleep.assert_called_once_with(3)

    def test_exhaustion_is_bounded_and_identifies_resource(self):
        with tempfile.TemporaryDirectory() as t,patch.object(core.urllib.request,'urlopen',side_effect=http.client.RemoteDisconnected('closed')) as get,patch.object(core.time,'sleep'):
            with self.assertRaisesRegex(core.DownloadError,'fixture.bundle.*5'):core.get_file(self.info(),Path(t))
            self.assertEqual(5,get.call_count);self.assertEqual([],list(Path(t).iterdir()))

    def test_hash_mismatch_is_not_cached_or_silently_accepted(self):
        with tempfile.TemporaryDirectory() as t,patch.object(core.urllib.request,'urlopen',return_value=io.BytesIO(b'fake')) as get:
            with self.assertRaisesRegex(core.DownloadError,'SHA-256 mismatch'):core.get_file(self.info(),Path(t))
            self.assertEqual(1,get.call_count);self.assertEqual([],list(Path(t).iterdir()))
