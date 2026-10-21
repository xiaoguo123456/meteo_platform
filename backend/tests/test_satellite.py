import asyncio
import unittest
import tempfile
import io
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from app import satellite_service as sat

def tile_bytes():
    body=io.BytesIO();Image.new('RGB',(256,256),(70,80,90)).save(body,format='JPEG');return body.getvalue()

class FakeResponse:
    def __init__(self,status_code=200,content=b'',payload=None):self.status_code,self.content,self.payload=status_code,content,payload
    def json(self):return self.payload
    def raise_for_status(self):
        if self.status_code>=400:raise RuntimeError(f'HTTP {self.status_code}')

class FakeJma:
    """按时刻指定可用图块数，模拟 JMA 仍在上传的最新帧。"""
    def __init__(self,times,ready):self.times,self.ready,self.requests=times,ready,[]
    def __call__(self,*args,**kwargs):return self
    async def __aenter__(self):return self
    async def __aexit__(self,*args):return False
    async def get(self,url):
        self.requests.append(url)
        if url==sat.TARGET_TIMES_URL:return FakeResponse(payload=[{'basetime':t,'validtime':t} for t in self.times])
        parts=url.split('/');x,y=int(parts[-2]),int(parts[-1].split('.')[0])
        t=next(v for v in self.times if f'/{v}/fd/' in url)
        return FakeResponse(content=tile_bytes()) if x*8+y<self.ready[t] else FakeResponse(404)

class SatelliteTests(unittest.TestCase):
    def test_mosaic_location_transparency_and_catalog(self):
        image=Image.new('RGB',(256,256),(70,80,90));body=io.BytesIO();image.save(body,format='PNG')
        with tempfile.TemporaryDirectory() as root,patch.object(sat,'ROOT',Path(root)):
            sat.save_mosaic('20261013150000',[(7,3,body.getvalue()),(0,0,None)])
            with Image.open(sat.image_path('20261013150000')) as result:
                self.assertEqual(result.size,(2048,2048))
                self.assertEqual(result.getpixel((1792,768)),(70,80,90,255))
                self.assertEqual(result.getpixel((0,0)),(0,0,0,0))
            sat.write_status()
            self.assertEqual(sat.catalog()['times'],['20261013150000'])
            with self.assertRaises(ValueError):sat.image_path('../status')
            with self.assertRaises(FileNotFoundError):sat.image_path('20261013151000')
    def test_retention_and_error_visible(self):
        with tempfile.TemporaryDirectory() as root,patch.object(sat,'ROOT',Path(root)),patch.object(sat,'KEEP',2),patch.object(sat,'RETAIN_EXTRA',1):
            (Path(root)/'truecolor').mkdir()
            times=['20261013150000','20261013151000','20261013152000','20261013153000']
            for t in times:(Path(root)/'truecolor'/f'{t}.webp').touch()
            sat.write_status('上游连接失败')
            self.assertEqual(sat.catalog()['times'],times[-2:])
            self.assertEqual(sat.catalog()['error'],'上游连接失败')
            self.assertFalse((Path(root)/'truecolor'/f'{times[0]}.webp').exists())
            # 刚移出清单的一帧仍保留在磁盘，前端旧清单还能读到。
            self.assertTrue(sat.image_path(times[1]).exists())

    def test_products_are_isolated(self):
        with tempfile.TemporaryDirectory() as root,patch.object(sat,'ROOT',Path(root)):
            sat.save_mosaic('20261013150000',[], 'infrared')
            sat.write_status(product='infrared')
            self.assertEqual(sat.catalog()['times'],[])
            self.assertEqual(sat.catalog('infrared')['times'],['20261013150000'])
            with self.assertRaises(ValueError):sat.image_path('20261013150000','../infrared')

    def test_display_preserves_dimensions_and_transparency(self):
        with tempfile.TemporaryDirectory() as root,patch.object(sat,'ROOT',Path(root)):
            sat.save_mosaic('20261013150000',[])
            with Image.open(sat.display_path('20261013150000','truecolor')) as image:
                self.assertEqual(image.size,(2048,2048))
                self.assertEqual(image.getpixel((0,0))[3],0)

class SyncTests(unittest.TestCase):
    def run_sync(self,root,times,ready):
        fake=FakeJma(times,ready)
        with patch.object(sat,'ROOT',Path(root)),patch.object(sat.httpx,'AsyncClient',fake),patch.object(sat,'PRODUCTS',{'infrared':'B13/TBB'}):
            asyncio.run(sat.sync_satellite())
            return sat.catalog('infrared'),fake

    def test_incomplete_latest_is_skipped_without_error(self):
        times=['20261013150000','20261013151000']
        with tempfile.TemporaryDirectory() as root:
            status,_=self.run_sync(root,times,{times[0]:48,times[1]:20})
            # 最新帧仍在上传：不发布缺块帧，旧帧照常补齐，也不提示错误。
            self.assertEqual(status['times'],[times[0]])
            self.assertIsNone(status['error'])
            self.assertEqual(status['state'],'ready')
            status,_=self.run_sync(root,times,{times[0]:48,times[1]:48})
            self.assertEqual(status['times'],times)

    def test_nothing_complete_reports_reason(self):
        times=['20261013150000']
        with tempfile.TemporaryDirectory() as root:
            status,_=self.run_sync(root,times,{times[0]:10})
        self.assertEqual(status['times'],[])
        self.assertIn('尚未上传完整',status['error'])

class StationImageTests(unittest.TestCase):
    def setUp(self):
        sat._LOCAL_CACHE.clear()
    def tearDown(self):
        sat._LOCAL_CACHE.clear()

    def write_catalog(self,root,times):
        folder=Path(root)/'truecolor';folder.mkdir(parents=True)
        for t in times:(folder/f'{t}.webp').touch()
        sat.write_status()

    def test_uses_published_time_and_falls_back_when_incomplete(self):
        times=['20261013150000','20261013151000','20261013152000']
        with tempfile.TemporaryDirectory() as root,patch.object(sat,'ROOT',Path(root)):
            self.write_catalog(root,times[:2])
            # JMA 已列出 15:20，但全球缓存只确认到 15:10，且 15:10 的局部瓦片还缺块。
            fake=FakeJma(times,{times[0]:64*64,times[1]:1,times[2]:64*64})
            with patch.object(sat.httpx,'AsyncClient',fake):
                observed,image=asyncio.run(sat.station_image('s1',40,115))
            self.assertEqual(observed,times[0])
            self.assertTrue(image)
            self.assertNotIn(sat.TARGET_TIMES_URL,fake.requests)
            self.assertFalse(any(f'/{times[2]}/' in url for url in fake.requests))

    def test_cache_reused_for_latest_and_bounded(self):
        times=['20261013150000']
        with tempfile.TemporaryDirectory() as root,patch.object(sat,'ROOT',Path(root)),patch.object(sat,'LOCAL_CACHE_SIZE',2):
            self.write_catalog(root,times)
            fake=FakeJma(times,{times[0]:64*64})
            with patch.object(sat.httpx,'AsyncClient',fake):
                for key in ('a','b','a','c'):asyncio.run(sat.station_image(key,40,115))
                count=len(fake.requests)
                asyncio.run(sat.station_image('c',40,115))
            self.assertEqual(len(fake.requests),count,'最新完整时刻的结果应直接复用')
            self.assertEqual(list(sat._LOCAL_CACHE),[('a','truecolor'),('c','truecolor')])
