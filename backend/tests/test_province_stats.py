import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient

from app import forecast_cache as cache
from app import province_stats as ps
from app.main import app
from app.spatial_provider import SpatialDataError
from test_forecast_cache import ForecastCacheFixture


def square(west, south, size):
    return [[west, south], [west+size, south], [west+size, south+size], [west, south+size], [west, south]]


class SyntheticRegions(unittest.TestCase):
    """用规则方块核对面积比例与加权平均，避免依赖真实省界形状。"""
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        path = Path(self.directory.name)/'regions.json'
        features = [
            {'type': 'Feature', 'properties': {'code': '1', 'name': '方块省'},
             'geometry': {'type': 'MultiPolygon', 'coordinates': [[square(100, 30, 1)]]}},
            {'type': 'Feature', 'properties': {'code': '2', 'name': '回字省'},
             'geometry': {'type': 'MultiPolygon', 'coordinates': [[square(110, 30, 1), square(110.25, 30.25, 0.5)]]}},
            {'type': 'Feature', 'properties': {'code': '3', 'name': '微小省'},
             'geometry': {'type': 'MultiPolygon', 'coordinates': [[square(120.01, 30.01, 0.02)]]}},
        ]
        path.write_text(json.dumps({'type': 'FeatureCollection', 'features': features}))
        self.patch = patch.object(ps, 'REGIONS_PATH', path)
        self.patch.start()
        ps.regions.cache_clear(); ps.weights.cache_clear()

    def tearDown(self):
        self.patch.stop()
        ps.regions.cache_clear(); ps.weights.cache_clear()
        self.directory.cleanup()

    def test_coverage_share_and_hole(self):
        w = ps.weights('gfs')
        latitude = np.cos(np.radians(30.5))
        # 1°×1° 在 0.25° 网格上为 16 个格点面积；洞挖去中间 0.5°×0.5° 即 4 个格点。
        self.assertAlmostEqual(w['1']['weight'].sum()/latitude, 16, delta=0.1)
        self.assertAlmostEqual(w['2']['weight'].sum()/latitude, 12, delta=0.1)
        self.assertEqual((w['3']['cells'], w['3']['nearest']), (1, True))
        self.assertEqual(ps.locate(100.5, 30.5)['name'], '方块省')
        self.assertIsNone(ps.locate(110.5, 30.5), '洞内不属于该省')
        self.assertEqual(ps.locate(110.1, 30.1)['code'], '2')
        self.assertIsNone(ps.locate(0, 0))

    def test_weighted_mean_min_max(self):
        g = ps.MODEL_GRIDS['gfs']
        latitudes = g['lat0']+np.arange(g['height'])*g['dy']
        field = np.broadcast_to(latitudes[:, None], (g['height'], g['width'])).astype(np.float32).copy()
        field[np.isclose(latitudes, 30.5)] = np.nan
        u = np.full_like(field, 3); v = np.full_like(field, -4)
        stats = ps.frame_stats('gfs', {'u': u, 'v': v, 'temperature': field})
        mean, low, high = stats['1']['temperature']
        # 方块内纬度对称分布，缺测行不计入；边界格点按一半面积计入。
        self.assertAlmostEqual(mean, 30.5, delta=0.01)
        self.assertEqual((low, high), (30.0, 31.0))
        self.assertEqual(stats['1']['wind'][:3], [5.0, 5.0, 5.0])
        self.assertEqual(stats['3']['temperature'][1], 30.0)


class RealRegionTests(unittest.TestCase):
    def test_real_province_area_matches_source(self):
        ps.regions.cache_clear(); ps.weights.cache_clear()
        w = ps.weights('gfs')
        beijing = w['110000']
        self.assertEqual(len(ps.province_list()), 34)
        # 北京面积约 1.7348 平方度，即 0.25° 网格约 27.7 个格点面积。
        self.assertAlmostEqual(float((beijing['weight']/np.cos(np.radians(40))).sum()), 27.7, delta=1.0)
        self.assertTrue(w['820000']['nearest'])
        self.assertEqual(ps.locate(116.4, 39.9)['name'], '北京市')
        self.assertIsNone(ps.locate(139.7, 35.7))


class ProvinceForecastTests(ForecastCacheFixture):
    def test_series_backfill_and_api(self):
        with patch.object(cache, 'latest_manifest', return_value=self.manifest), patch.object(cache, 'read_native_snapshot', side_effect=self.native):
            cache.sync_once(['gfs'])
        run = self.manifest['reference_time']
        series = ps.province_forecast('gfs', 'wind', '110000', run)
        self.assertEqual(series['name'], '北京市')
        self.assertEqual([p['time'] for p in series['points']], self.manifest['valid_times'])
        # 夹具中第 i 帧 u=v=i+1，风速为 √2·(i+1)，风向来自西南。
        self.assertAlmostEqual(series['points'][1]['mean'], 2*2**0.5, places=2)
        self.assertAlmostEqual(series['points'][1]['direction'], 225, places=1)
        self.assertEqual(series['unit'], 'm/s')

        # 升级前缓存的批次缺省平均文件：接口提示正在计算，后台只补算、不重新下载。
        folder = cache.ROOT/'gfs'/cache.read_status('gfs')['key']
        (folder/'1.provinces.json').unlink()
        ps._series.cache_clear()
        with self.assertRaisesRegex(SpatialDataError, '省平均正在后台计算（1/2）'):
            ps.province_forecast('gfs', 'wind', '110000', run)
        with patch.object(cache, 'latest_manifest', return_value=self.manifest), patch.object(cache, 'read_native_snapshot', side_effect=AssertionError('不应重新下载')):
            cache.sync_once(['gfs'])
        self.assertTrue((folder/'1.provinces.json').exists())
        self.assertEqual(cache.read_status('gfs')['state'], 'ready')

        client = TestClient(app)
        response = client.get('/api/province-forecast/gfs', params={'code': '110000', 'field': 'wind', 'run_time': run})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['points']), 2)
        self.assertEqual(client.get('/api/province-forecast/gfs', params={'code': '000000'}).status_code, 503)
        self.assertEqual(client.get('/api/provinces/locate', params={'longitude': 116.4, 'latitude': 39.9}).json()['code'], '110000')
        self.assertIsNone(client.get('/api/provinces/locate', params={'longitude': 150, 'latitude': 0}).json())
        outline = client.get('/api/provinces/110000/outline')
        self.assertEqual(outline.json()['geometry']['type'], 'MultiPolygon')
        self.assertEqual(client.get('/api/provinces/999999/outline').status_code, 404)
        self.assertEqual(len(client.get('/api/provinces').json()), 34)
