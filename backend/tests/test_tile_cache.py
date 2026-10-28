"""分块保持原始浮点值，边缘块尺寸正确。"""
import gzip,json,struct,tempfile,unittest
from pathlib import Path
import numpy as np
from app.tile_cache import prepare_tiles

class TilesTests(unittest.TestCase):
 def test_reconstruct_exact_grid(self):
  a=(np.arange(721*1440,dtype=np.float32).reshape(721,1440)%137)/10
  a[127,127]=np.nan
  native={'arrays':{'u':a,'v':-a,'temperature':a},'valid_time':'2026-10-13T00:00Z'}
  with tempfile.TemporaryDirectory() as d:
   path,entries=prepare_tiles(Path(d),0,'ifs','temperature',native)
   rebuilt=np.full_like(a,np.nan)
   with path.open('rb') as stream:
    for offset,length in entries.values():
     stream.seek(offset);b=gzip.decompress(stream.read(length));n=struct.unpack('<I',b[:4])[0];m=json.loads(b[4:4+n]);start=4+n
     palette=np.frombuffer(b,dtype='<f4',offset=start,count=m['palette_size'])
     indices=np.frombuffer(b,dtype='<u2',offset=start+4*m['palette_size']).reshape(m['height'],m['width'])
     self.assertEqual(m['encoding'],'palette-delta-u16-le')
     indices=np.cumsum(indices,axis=1,dtype=np.uint16)
     values=palette[indices]
     rebuilt[m['tile_y']:m['tile_y']+m['height'],m['tile_x']:m['tile_x']+m['width']]=values
   np.testing.assert_array_equal(rebuilt,a)
   self.assertEqual(len(entries),72)

 def test_upgrade_reads_existing_snapshot_without_reencoding(self):
  from unittest.mock import patch
  from app.tile_cache import cached_tiles
  a=np.ones((721,1440),dtype=np.float32)
  with tempfile.TemporaryDirectory() as d:
   folder=Path(d)/'gfs'/'test';folder.mkdir(parents=True)
   prepare_tiles(folder,0,'gfs','temperature',{'arrays':{'u':a,'v':a,'temperature':a},'valid_time':'2026-10-13T00:00Z'},version=3)
   with patch('app.forecast_cache.ROOT',Path(d)),patch('app.forecast_cache.locate_field',return_value=({'key':'test'},'2026-10-13T00:00Z',0)),patch('app.forecast_cache.read_cached_native',side_effect=AssertionError('不应现场重新编码')):
    stream,length=cached_tiles('gfs','temperature','run','time',[0],4)
    payload=b''.join(stream);self.assertEqual(len(payload),length)
    from app.point_forecast import decode_values
    meta,values=decode_values(gzip.decompress(payload[4:]))
    self.assertEqual(meta['encoding'],'palette-u16-le')
    np.testing.assert_array_equal(values[0],a[:128,:128])

 def test_half_resolution_grid(self):
  a=np.full((721,1440),3.2,dtype=np.float32)
  a[100,200]=np.nan;a[300,401]=np.nan
  native={'arrays':{'u':a,'v':-a,'temperature':a},'valid_time':'2026-10-13T00:00Z'}
  with tempfile.TemporaryDirectory() as d:
   path,entries=prepare_tiles(Path(d),0,'ifs','temperature',native,scale=2)
   self.assertTrue(path.name.endswith('.v4.s2.blocks'))
   self.assertEqual(len(entries),18)
   rebuilt=np.full((361,720),-1,dtype=np.float32)
   with path.open('rb') as stream:
    for offset,length in entries.values():
     stream.seek(offset)
     from app.point_forecast import decode_values
     m,values=decode_values(gzip.decompress(stream.read(length)))
     self.assertEqual((m['full_width'],m['full_height'],m['dx'],m['dy'],m['lon0'],m['lat0']),(720,361,.5,.5,-180,-90))
     rebuilt[m['tile_y']:m['tile_y']+m['height'],m['tile_x']:m['tile_x']+m['width']]=values[0]
  # 原缺测格点保持缺测；邻点缺测不污染平滑结果，常值场保持不变。
  self.assertTrue(np.isnan(rebuilt[50,100]))
  self.assertAlmostEqual(float(rebuilt[150,200]),3.2,places=5)
  self.assertEqual(int(np.isnan(rebuilt).sum()),1)
  np.testing.assert_allclose(rebuilt[~np.isnan(rebuilt)],3.2,rtol=1e-6)

 def test_half_resolution_wraps_longitude(self):
  from app.tile_cache import half_resolution
  lon=np.arange(1440)*.25-180
  a=np.tile(np.cos(np.radians(lon))*10,(721,1)).astype(np.float32)[None]
  reduced,meta=half_resolution(a,{'width':1440,'height':721,'dx':.25,'dy':.25,'lon0':-180,'lat0':-90})
  self.assertEqual(reduced.shape,(1,361,720))
  # 平滑后仍贴近原值；首尾经度相接，不出现边缘异常。
  np.testing.assert_allclose(reduced[0,180],a[0,360,::2],atol=.1)
  self.assertAlmostEqual(float(reduced[0,180,0]),-10.0,places=1)

 def test_cached_half_resolution_on_demand(self):
  from unittest.mock import patch
  from app.tile_cache import cached_tiles
  from app.spatial_provider import SpatialDataError
  a=np.ones((721,1440),dtype=np.float32)
  native={'arrays':{'u':a,'v':a,'temperature':a},'valid_time':'2026-10-13T00:00Z'}
  with tempfile.TemporaryDirectory() as d:
   folder=Path(d)/'gfs'/'test';folder.mkdir(parents=True)
   with patch('app.forecast_cache.ROOT',Path(d)),patch('app.forecast_cache.locate_field',return_value=({'key':'test'},'2026-10-13T00:00Z',0)),patch('app.forecast_cache.read_cached_native',return_value=native):
    stream,length=cached_tiles('gfs','temperature','run','time',[0,17],4,2)
    payload=b''.join(stream);self.assertEqual(len(payload),length)
    self.assertTrue((folder/'0.temperature.v4.s2.json').exists())
    with self.assertRaises(SpatialDataError):cached_tiles('gfs','temperature','run','time',[18],4,2)
    with self.assertRaises(SpatialDataError):cached_tiles('gfs','temperature','run','time',[0],3,2)
