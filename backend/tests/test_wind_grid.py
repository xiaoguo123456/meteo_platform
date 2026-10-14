"""验证传输格式和 S3 错误不会被替换成合成数据。"""
import asyncio
import json
import struct
import unittest
from unittest.mock import patch
import numpy as np
from app.wind_grid import encode_grid, wind_grid, _cache
from app.spatial_provider import SpatialDataError

class WindGridTests(unittest.TestCase):
    def test_encoding(self):
        a=np.full((721,1440),3,dtype=np.float32)
        b=encode_grid({'arrays':{'u':a,'v':a*2},'valid_time':'2026-10-13T00:00Z'},'gfs')
        n=struct.unpack('<I',b[:4])[0]
        self.assertEqual(json.loads(b[4:4+n])['level'],'80m')
        data=np.frombuffer(b[4+n:],dtype='<f4').reshape(2,721,1440)
        self.assertEqual(data[0,0,0],3)
        self.assertEqual(data[1,-1,-1],6)
    def test_bad_shape(self):
        with self.assertRaises(SpatialDataError):
            encode_grid({'arrays':{'u':np.ones((2,2)),'v':np.ones((2,2))}},'gfs')
    def test_failure_propagates(self):
        _cache.clear()
        with patch('app.wind_grid.read_native_snapshot',side_effect=SpatialDataError('S3 不可达')):
            with self.assertRaisesRegex(SpatialDataError,'S3 不可达'):
                asyncio.run(wind_grid('gfs'))
        self.assertFalse(_cache)



class ScalarTests(unittest.TestCase):
    def test_scalar_preserves_negative_values(self):
        a=np.full((721,1440),-12.5,dtype=np.float32)
        native={'arrays':{'u':a,'v':a,'temperature':a},'valid_time':'2026-10-13T00:00Z'}
        b=encode_grid(native,'gfs','temperature');n=struct.unpack('<I',b[:4])[0]
        m=json.loads(b[4:4+n]);self.assertEqual(m['units'],'°C');self.assertEqual(m['field'],'temperature')
        self.assertEqual(np.frombuffer(b[4+n:],dtype='<f4')[0],-12.5)
    def test_missing_precipitation_errors(self):
        a=np.zeros((721,1440),dtype=np.float32)
        with self.assertRaisesRegex(SpatialDataError,'降水'):
            encode_grid({'arrays':{'u':a,'v':a},'valid_time':'2026-10-13T00:00Z'},'gfs','precipitation')

if __name__=='__main__':unittest.main()

class MultiModelGridTests(unittest.TestCase):
    def test_native_grids_and_surface_levels(self):
        from app.spatial_provider import MODEL_GRIDS
        for model in ('ifs','aifs','grapes'):
            grid=MODEL_GRIDS[model]
            a=np.ones((grid['height'],grid['width']),dtype=np.float32)
            native={'arrays':{'u':a,'v':a,'temperature':a,'humidity':a,'pressure':a,'precipitation':a},'valid_time':'2026-10-13T06:00Z'}
            for field,level in [('wind','10m'),('temperature','2m'),('humidity','2m'),('pressure','海平面'),('precipitation','地面 · 时段降水')]:
                with self.subTest(model=model,field=field):
                    encoded=encode_grid(native,model,field)
                    size=struct.unpack('<I',encoded[:4])[0];meta=json.loads(encoded[4:4+size])
                    self.assertEqual(meta['level'],level)
                    self.assertEqual(meta['lat0'],grid['lat0'])
                    self.assertEqual(len(encoded),4+size+grid['width']*grid['height']*8)
