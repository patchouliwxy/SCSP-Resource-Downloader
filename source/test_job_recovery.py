import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import zipfile

import scsp_web as web
import scsp_download as core
from test_scsp_web import resource,catalog
import test_scsp_web as fixtures


class RecoveryTests(unittest.TestCase):
    setUp=fixtures.DownloadTests.setUp
    tearDown=fixtures.DownloadTests.tearDown
    wait=fixtures.DownloadTests.wait

    def submit(self):
        return self.manager.submit(dict(ids=[self.a['id']],allow_unresolved=True))

    def test_network_failure_same_id_resumes_only_missing_file(self):
        with patch.object(core,'get_file',side_effect=[b'1234UnityFS\0',OSError('network')]):
            job=self.submit();self.assertEqual('failed',self.wait(job['id'])['status'])
        with patch.object(core,'get_file',return_value=b'1234UnityFS\0') as get:
            resumed=self.manager.retry(job['id']);done=self.wait(job['id'])
            self.assertEqual(job['id'],resumed['id']);self.assertEqual('completed',done['status'])
            self.assertEqual(1,get.call_count);self.assertEqual(1,done['reused_files'])
            self.assertEqual(24,done['completed_bytes'])

    def test_service_reopen_keeps_snapshot_without_current_catalog(self):
        with patch.object(core,'get_file',side_effect=[b'1234UnityFS\0',OSError('network')]):
            job=self.submit();self.wait(job['id'])
        self.manager.pool.shutdown(wait=True)
        self.manager=web.Downloads(catalog([]),self.root/'out',self.root/'cache')
        with patch.object(core,'get_file',return_value=b'1234UnityFS\0') as get:
            self.manager.retry(job['id']);self.assertEqual('completed',self.wait(job['id'])['status'])
            self.assertEqual(1,get.call_count)

    def clip(self,output,progress):
        folder=output/'animations';folder.mkdir()
        (folder/'clip.anim').write_text('correct')
        report={'clips':[{'file':'animations/clip.anim'}],'sources':[]}
        (folder/'export-report.json').write_text(json.dumps(report))
        return report

    def failed_package(self):
        with patch.object(core,'get_file',return_value=b'1234UnityFS\0'),patch.object(web,'export_animations',side_effect=self.clip),patch.object(self.manager,'package',side_effect=OSError('zip failed')):
            job=self.submit();self.assertEqual('failed',self.wait(job['id'])['status'])
        return job

    def test_packaging_failure_reuses_all_export_checkpoints(self):
        job=self.failed_package()
        with patch.object(core,'get_file') as get,patch.object(web,'export_animations') as anim:
            self.manager.retry(job['id']);done=self.wait(job['id'])
            self.assertEqual('completed',done['status']);get.assert_not_called();anim.assert_not_called()
            self.assertEqual(5,done['reused_stages'])
        with zipfile.ZipFile(self.root/'out'/(job['id']+'.zip')) as z:
            self.assertEqual(b'correct',z.read('animations/clip.anim'))

    def test_changed_export_is_preserved_and_regenerated(self):
        job=self.failed_package();output=self.root/'out'/job['id']
        (output/'animations/clip.anim').write_text('user-edited')
        with patch.object(core,'get_file') as get,patch.object(web,'export_animations',side_effect=self.clip) as anim:
            self.manager.retry(job['id']);self.assertEqual('completed',self.wait(job['id'])['status'])
            get.assert_not_called();self.assertEqual(1,anim.call_count)
        self.assertEqual('correct',(output/'animations/clip.anim').read_text())
        self.assertTrue(any(p.read_text()=='user-edited' for p in (output/'history').rglob('clip.anim')))

    def test_export_only_never_downloads_and_preserves_previous_zip(self):
        with patch.object(core,'get_file',return_value=b'1234UnityFS\0'),patch.object(web,'export_animations',side_effect=self.clip):
            job=self.submit();self.assertEqual('completed',self.wait(job['id'])['status'])
        output=self.root/'out'/job['id']
        previous=(self.root/'out'/(job['id']+'.zip')).read_bytes()
        with patch.object(core,'get_file') as get,patch.object(web,'export_animations',side_effect=self.clip):
            self.manager.retry(job['id'],'export');done=self.wait(job['id'])
            self.assertEqual('completed',done['status']);get.assert_not_called()
        self.assertTrue(any(p.read_bytes()==previous for p in (output/'history').rglob('previous.zip')))

    def test_export_only_rejects_missing_or_modified_original_input(self):
        job=self.failed_package();output=self.root/'out'/job['id']
        p=next((output/'bundles').iterdir());p.write_bytes(b'changed')
        with self.assertRaisesRegex(core.DownloadError,'原始输入'):
            self.manager.retry(job['id'],'export')
        self.assertEqual('failed',self.manager.jobs[job['id']]['status'])

    def test_duplicate_retry_rejected_before_worker_starts(self):
        job=self.failed_package()
        with patch.object(self.manager.pool,'submit') as submit:
            self.manager.retry(job['id'])
            with self.assertRaisesRegex(core.DownloadError,'正在处理'):self.manager.retry(job['id'])
            self.assertEqual(1,submit.call_count)
        self.manager.jobs[job['id']]['status']='failed'

    def test_cache_hit_statistics_without_network(self):
        entry=resource('cache.asset');payload=b'1234UnityFS\0'
        self.assertEqual(entry['size'],len(payload))
        entry['sha256']=hashlib.sha256(payload).hexdigest()
        self.manager.catalog=catalog([entry]);self.manager.cache.mkdir()
        (self.manager.cache/core.real_name(entry)).write_bytes(payload)
        with patch.object(core.urllib.request,'urlopen') as network:
            job=self.manager.submit({'ids':[entry['id']]});done=self.wait(job['id'])
            self.assertEqual('completed',done['status']);network.assert_not_called()
            self.assertEqual(1,done['cached_files']);self.assertEqual(0,done['network_bytes'])

    def test_office_alias_requires_verified_model_dependencies(self):
        e=resource('dioramabackground_0001_0101.unity', ['7dae3oq/office_living.fbx','7dae3oq/office_kitchen.fbx','7dae3oq/office_pdesk.fbx'])
        # Alias is metadata only, not dependency resolution or an invented official title.
        c=catalog([e]);r=c.search(query='283事务所',scope='scene')['items'][0]
        self.assertEqual('verified_resource_alias',r['scene_title_kind'])
        e['dependencies']=[];self.assertEqual(0,catalog([e]).search(query='283事务所')['total'])


if __name__=='__main__':unittest.main()
