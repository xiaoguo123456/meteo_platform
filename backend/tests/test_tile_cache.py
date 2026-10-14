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
