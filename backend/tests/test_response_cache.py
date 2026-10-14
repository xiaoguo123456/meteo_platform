"""无损传输格式与压缩文件复用。"""
import gzip,json,struct,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from app.response_cache import pack_grid,prepare_field

class ResponseTests(unittest.TestCase):
 def setUp(self):
  a=np.resize(np.array([-12.15,0,1.1,np.nan],dtype=np.float32),(721,1440))
  self.native={'arrays':{'u':a,'v':a,'temperature':a},'valid_time':'2026-10-13T00:00Z'}
 def test_round_trip_exact_values_and_missing(self):
  for field in ('wind','temperature'):
   data=pack_grid(self.native,'ifs',field);n=struct.unpack('<I',data[:4])[0];meta=json.loads(data[4:4+n]);start=4+n
   palette=np.frombuffer(data,dtype='<f4',count=meta['palette_size'],offset=start)
   values=palette[np.frombuffer(data,dtype='<u2',offset=start+meta['palette_size']*4)]
   expected=self.native['arrays']['u'].ravel()
   if field=='wind':expected=np.concatenate([expected,expected])
   np.testing.assert_array_equal(values,expected)
   self.assertEqual(meta['channels'],2 if field=='wind' else 1)
 def test_reuse_avoids_read_and_compression(self):
  with tempfile.TemporaryDirectory() as d:
   path=prepare_field(Path(d),0,'ifs','temperature',lambda:self.native)
   with patch('app.response_cache.gzip.compress',side_effect=AssertionError('不可重复压缩')):
    again=prepare_field(Path(d),0,'ifs','temperature',lambda:(_ for _ in ()).throw(AssertionError('不可重复读取')))
   self.assertEqual(again,path)
   self.assertTrue(gzip.decompress(path.read_bytes()))
