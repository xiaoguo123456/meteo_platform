"""预取、断点续传、批次切换及请求不触网的回归测试。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from app import forecast_cache as cache
from app.spatial_provider import SpatialDataError

class ForecastCacheFixture(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.root=patch.object(cache,'ROOT',Path(self.directory.name));self.root.start()
        cache.STOP.clear()
        self.manifest={'reference_time':'2026-10-13T00:00Z','valid_times':['2026-10-13T00:00Z','2026-10-13T03:00Z'],'variables':[]}
    def tearDown(self):
        self.root.stop();self.directory.cleanup()
    def native(self,model,manifest,time,*args):
        a=np.full((721,1440),manifest['valid_times'].index(time)+1,dtype=np.float32)
        return {'arrays':{'u':a,'v':a},'valid_time':time,'run_time':manifest['reference_time']}


class ForecastCacheTests(ForecastCacheFixture):
    def test_prefetch_resume_and_local_only(self):
        with patch.object(cache,'latest_manifest',return_value=self.manifest),patch.object(cache,'read_native_snapshot',side_effect=self.native) as download:
            cache.sync_once(['gfs']);self.assertEqual(download.call_count,2)
            cache.sync_once(['gfs']);self.assertEqual(download.call_count,2)
        with patch.object(cache,'latest_manifest',side_effect=AssertionError('请求不能联网')),patch.object(cache,'read_native_snapshot',side_effect=AssertionError('请求不能联网')):
            first=cache.cached_field('gfs','wind',self.manifest['reference_time'],self.manifest['valid_times'][0])
            second=cache.cached_field('gfs','wind',self.manifest['reference_time'],self.manifest['valid_times'][1])
            self.assertNotEqual(first,second)
        self.assertEqual(cache.read_status('gfs')['state'],'ready')
    def test_new_batch_failure_is_visible(self):
        with patch.object(cache,'latest_manifest',return_value=self.manifest),patch.object(cache,'read_native_snapshot',side_effect=self.native):cache.sync_once(['gfs'])
        changed={**self.manifest,'reference_time':'2026-10-13T06:00Z'}
        with patch.object(cache,'latest_manifest',return_value=changed),patch.object(cache,'read_native_snapshot',side_effect=SpatialDataError('S3 断开')):cache.sync_once(['gfs'])
        status=cache.read_status('gfs')
        self.assertEqual(status['run_time'],self.manifest['reference_time'])
        self.assertEqual(status['times'],self.manifest['valid_times'])
        public=cache.read_public_status('gfs')
        self.assertEqual(public['pending_run_time'],changed['reference_time'])
        self.assertIn('S3 断开',public['pending_error'])
        self.assertIsNotNone(cache.cached_field('gfs','wind',self.manifest['reference_time'],self.manifest['valid_times'][0]))

    def test_new_batch_promotes_only_after_complete(self):
        with patch.object(cache,'latest_manifest',return_value=self.manifest),patch.object(cache,'read_native_snapshot',side_effect=self.native):
            cache.sync_once(['gfs'])
        changed={'reference_time':'2026-10-13T06:00Z','valid_times':['2026-10-13T06:00Z','2026-10-13T09:00Z']}
        def download(model,manifest,time,*args):
            if time==changed['valid_times'][1]:raise SpatialDataError('第二帧未就绪')
            return self.native(model,manifest,time,*args)
        with patch.object(cache,'CONCURRENCY',1),patch.object(cache,'latest_manifest',return_value=changed),patch.object(cache,'read_native_snapshot',side_effect=download):
            cache.sync_once(['gfs'])
        status=cache.read_status('gfs')
        self.assertEqual(status['run_time'],self.manifest['reference_time'])
        self.assertEqual(cache.read_public_status('gfs')['pending_run_time'],changed['reference_time'])
        self.assertEqual(cache.read_public_status('gfs')['pending_cached'],1)
        # 按新批次地址请求也不能绕过整批发布条件。
        with self.assertRaises(SpatialDataError):cache.cached_field('gfs','wind',changed['reference_time'])
        with patch.object(cache,'latest_manifest',return_value=changed),patch.object(cache,'read_native_snapshot',side_effect=self.native) as resumed:
            cache.sync_once(['gfs'])
        self.assertEqual(resumed.call_count,1)
        status=cache.read_status('gfs')
        self.assertEqual(status['run_time'],changed['reference_time'])
        self.assertEqual(status['state'],'ready')
        self.assertEqual(status['times'],changed['valid_times'])
        self.assertIsNone(cache.read_pending_status('gfs'))
        # 时间轴轮询尚未更新时，旧批次的在途请求仍必须返回旧数据。
        from app.tile_cache import cached_tiles
        from app.point_forecast import point_forecast
        with patch.object(cache,'latest_manifest',side_effect=AssertionError('请求不能联网')):
            stream,length=cached_tiles('gfs','wind',self.manifest['reference_time'],self.manifest['valid_times'][0],[0],4)
            self.assertEqual(len(b''.join(stream)),length)
            series=point_forecast('gfs','wind',100,30,self.manifest['reference_time'])
            self.assertEqual(series['run_time'],self.manifest['reference_time'])
            self.assertEqual([p['time'] for p in series['points']],self.manifest['valid_times'])

    def test_incomplete_time_is_not_published(self):
        def download(model,manifest,time,*args):
            if time==manifest['valid_times'][1]:raise SpatialDataError('文件未发布')
            return self.native(model,manifest,time)
        with patch.object(cache,'latest_manifest',return_value=self.manifest),patch.object(cache,'read_native_snapshot',side_effect=download):cache.sync_once(['gfs'])
        self.assertEqual(cache.read_status('gfs')['times'],[])
        self.assertIsNone(cache.read_status('gfs')['run_time'])
        self.assertEqual(cache.read_pending_status('gfs')['times'],self.manifest['valid_times'][:1])
        with self.assertRaises(SpatialDataError):cache.cached_field('gfs','wind',valid_time=self.manifest['valid_times'][1])

    def test_manifest_failure_preserves_published_batch(self):
        with patch.object(cache,'latest_manifest',return_value=self.manifest),patch.object(cache,'read_native_snapshot',side_effect=self.native):
            cache.sync_once(['gfs'])
        with patch.object(cache,'latest_manifest',side_effect=SpatialDataError('清单读取失败')):
            cache.sync_once(['gfs'])
        self.assertEqual(cache.read_status('gfs')['state'],'ready')
        self.assertEqual(cache.read_public_status('gfs')['pending_error'],'清单读取失败')
        self.assertIsNotNone(cache.cached_field('gfs','wind'))

    def test_published_batches_retained_and_expired_run_rejected(self):
        runs=['2026-10-13T00:00Z','2026-10-13T06:00Z','2026-10-13T12:00Z']
        for run in runs:
            manifest={**self.manifest,'reference_time':run}
            with patch.object(cache,'latest_manifest',return_value=manifest),patch.object(cache,'read_native_snapshot',side_effect=self.native):
                cache.sync_once(['gfs'])
        self.assertEqual(cache.read_run_status('gfs',runs[1])['run_time'],runs[1])
        for run in (runs[0],'../../status','无效日期'):
            with self.assertRaisesRegex(SpatialDataError,'起报批次已更新'):
                cache.read_run_status('gfs',run)
        self.assertFalse((cache.ROOT/'gfs'/'20261013T0000').exists())

    def test_pending_failure_uses_retry_interval(self):
        import asyncio
        cache.write_json(cache.ROOT/'gfs'/'status.json',{'state':'ready'})
        cache.write_json(cache.ROOT/'gfs'/'status.pending.json',{'state':'error'})
        delays=[]
        async def sleep(delay):
            delays.append(delay)
            cache.STOP.set()
        with patch.object(cache,'sync_once'),patch.object(cache,'MODEL_SPATIAL_NAMES',{'gfs':'gfs'}),patch.object(cache.asyncio,'sleep',side_effect=sleep):
            asyncio.run(cache.sync_loop())
        self.assertEqual(delays,[30])

class ConcurrentDownloadTests(ForecastCacheFixture):
    def test_two_times_download_concurrently(self):
        import threading
        barrier=threading.Barrier(2)
        def download(*args):
            barrier.wait(timeout=3)
            return self.native(*args)
        with patch.object(cache,'CONCURRENCY',2),patch.object(cache,'latest_manifest',return_value=self.manifest),patch.object(cache,'read_native_snapshot',side_effect=download):
            cache.sync_once(['gfs'])
        self.assertEqual(cache.read_status('gfs')['state'],'ready')
        self.assertEqual(len(cache.read_status('gfs')['times']),2)

class MultiModelTests(ForecastCacheFixture):
    def test_global_limit_and_failure_isolation(self):
        import threading
        import time
        running = 0
        peak = 0
        first = []
        lock = threading.Lock()
        barrier = threading.Barrier(4)
        def download(model, manifest, valid, *args):
            nonlocal running, peak
            with lock:
                running += 1
                peak = max(peak, running)
                first.append(model)
                initial = len(first) <= 4
            try:
                if initial:
                    barrier.wait(timeout=5)
                time.sleep(0.01)
                if model == 'ifs':
                    raise SpatialDataError('IFS 连接失败')
                return self.native(model, manifest, valid)
            finally:
                with lock:
                    running -= 1
        def prepare(folder,index,*args):
            (folder/f'{index}.wire-v4').touch()
        def stats(folder,index,*args):
            (folder/f'{index}.provinces.json').touch()
        with patch.object(cache, 'CONCURRENCY', 4), patch.object(cache, 'latest_manifest', return_value=self.manifest), patch.object(cache, 'read_native_snapshot', side_effect=download), patch.object(cache, 'encode_grid'), patch.object(cache, 'prepare_snapshot',side_effect=prepare), patch.object(cache, 'write_frame_stats',side_effect=stats):
            cache.sync_once()
        self.assertEqual(set(first[:4]), {'gfs', 'ifs', 'aifs', 'grapes'})
        self.assertEqual(peak, 4)
        self.assertIn('IFS 连接失败', cache.read_public_status('ifs')['pending_error'])
        for model in ('gfs', 'aifs', 'grapes'):
            self.assertEqual(cache.read_status(model)['state'], 'ready')

    def test_out_of_order_frames_publish_stable_prefix(self):
        folder=cache.ROOT/'ifs'/'20261013T0000';folder.mkdir(parents=True)
        for suffix in cache.FRAME_FILES:(folder/f'1.{suffix}').touch()
        (folder/'0.provinces.json').touch()
        context={'folder':folder,'status':{'model':'ifs','key':folder.name,'run_time':self.manifest['reference_time'],'expected_times':self.manifest['valid_times'],'total':2,'state':'syncing','error':None}}
        cache.publish(context)
        self.assertEqual(context['status']['times'], [])
        (folder/'0.npz').touch();cache.publish(context)
        self.assertEqual(cache.read_status('ifs')['times'],[])
        # NPZ 已写入也要等分块响应完成，避免交互请求触发压缩。
        (folder/'0.wire-v4').touch();cache.publish(context)
        self.assertEqual(context['status']['times'], self.manifest['valid_times'])
        self.assertEqual(cache.read_status('ifs')['times'],self.manifest['valid_times'])

class FieldTimelineTests(ForecastCacheFixture):
    def test_precipitation_starts_at_first_available_step(self):
        def native(*args):
            result=self.native(*args)
            if args[2] == self.manifest['valid_times'][1]:
                result['arrays']['precipitation']=result['arrays']['u']
            return result
        with patch.object(cache,'latest_manifest',return_value=self.manifest),patch.object(cache,'read_native_snapshot',side_effect=native):
            cache.sync_once(['ifs'])
        status=cache.read_status('ifs')
        self.assertEqual(status['field_times']['wind'],self.manifest['valid_times'])
        self.assertEqual(status['field_times']['precipitation'],self.manifest['valid_times'][1:])
        payload=cache.cached_field('ifs','precipitation',valid_time=self.manifest['valid_times'][1])
        size=int.from_bytes(payload[:4],'little')
        self.assertEqual(json.loads(payload[4:4+size])['interval_start'],self.manifest['valid_times'][0])
