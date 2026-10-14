import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch
import numpy as np
from app.tile_cache import prepare_tiles
from app.point_forecast import point_forecast, _series

class PointTests(unittest.TestCase):
    def test_original_grid_series_and_direction(self):
        with tempfile.TemporaryDirectory() as root:
            folder=Path(root)/'gfs'/'test';folder.mkdir(parents=True)
            status={'run_time':'2026-10-13T00:00:00Z','key':'test','expected_times':['2026-10-13T03:00:00Z'], 'field_times':{'wind':['2026-10-13T03:00:00Z']}}
            a=np.ones((721,1440),dtype=np.float32)
            prepare_tiles(folder,0,'gfs','wind',{'arrays':{'u':a*3,'v':a*4},'valid_time':status['expected_times'][0],'run_time':status['run_time']})
            with patch('app.forecast_cache.ROOT',Path(root)),patch('app.forecast_cache.read_status',return_value=status):
                data=point_forecast('gfs','wind',180,90)
                self.assertEqual(data['points'][0]['value'],5)
                self.assertAlmostEqual(data['points'][0]['direction'],216.8698976)
                self.assertEqual(data['grid_longitude'],-180)
                self.assertEqual(data['grid_latitude'],90)
                with self.assertRaises(ValueError):point_forecast('gfs','wind',0,float('nan'))
                with self.assertRaises(Exception):point_forecast('gfs','precipitation',0,0)
                with self.assertRaises(Exception):point_forecast('gfs','wind',0,0,'stale')
        _series.cache_clear()
