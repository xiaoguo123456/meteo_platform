import asyncio
import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi import HTTPException

from app.price import api, fetcher, store


def upstream(token='good', detail=None):
    """模拟上游：token 不对时按真实接口返回 code 401。"""
    detail = detail or [{'time96': '00:15', 'avgDayAheadPrice': '423.5', 'avgRealTimePrice': 430.3},
                        {'time96': '24:00', 'avgDayAheadPrice': '-60', 'avgRealTimePrice': None}]
    def handle(request):
        if request.headers.get('Authorization') != token:
            return httpx.Response(200, json={'code': 401, 'msg': 'Token已过期，请重新登录'})
        body = json.loads(request.content)
        if request.url.path.endswith('/detail'):
            return httpx.Response(200, json={'code': 200, 'message': 'OK', 'data': detail})
        price = None if body['type'] == 'real_time' and body['infoDate'] > '2026-10-26' else 448.2189583333333
        return httpx.Response(200, json={'code': 200, 'message': 'OK', 'data': [
            {'areaCode': '370000000000', 'areaName': '山东', 'averagePrice': price, 'electricityPrice': 224.99999403953552,
             'windElectricityPrice': 319.0, 'marketReferencePrice': 389.19}]})
    return lambda: httpx.AsyncClient(base_url=fetcher.BASE, transport=httpx.MockTransport(handle))


class PriceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patches = [patch.object(store, 'ROOT', Path(self.temp.name)), patch.object(fetcher, 'REQUEST_GAP', 0),
                        patch.object(store, 'today', lambda: '2026-10-27'), patch.dict(os.environ, {'PRICE_TOKEN': '', 'PRICE_ADMIN_KEY': ''})]
        for p in self.patches:
            p.start()
        api._last_attempt = None
        store.initialize()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.temp.cleanup()

    def test_guangdong_start_time_becomes_period_end(self):
        rows = [{'time96': f'{h:02d}:00', 'avgDayAheadPrice': '1', 'avgRealTimePrice': None} for h in range(24)]
        self.assertEqual([s['slot_end'] for s in fetcher.parse_curve(rows, 'start')][:2], [60, 120])
        self.assertEqual(fetcher.parse_curve(rows, 'start')[-1]['slot_end'], 1440)
        self.assertEqual(fetcher.parse_curve([{'time96': '24:00', 'avgDayAheadPrice': '-60'}], 'end')[0]['day_ahead'], -60)

    def test_fetch_stores_curves_and_averages(self):
        store.write_token('good')
        with patch.object(fetcher, 'client', upstream()):
            result = asyncio.run(fetcher.fetch_once())
        self.assertTrue(result['ok'], result['message'])
        day = api.day('2026-10-27')
        self.assertEqual(len(day['provinces']), len(fetcher.AREAS))
        self.assertEqual(day['provinces'][0]['slots'][-1], {'end': 1440, 'label': '24:00', 'day_ahead': -60.0, 'real_time': None})
        self.assertEqual(day['averages'][0]['day_ahead'], 448.22)
        self.assertEqual(day['averages'][0]['solar_mechanism_price'], 225.0)
        self.assertIsNone(day['averages'][0]['real_time'])
        self.assertEqual(api.day('2026-10-26')['averages'][0]['real_time'], 448.22)
        self.assertEqual(api.status()['state'], 'valid')
        self.assertIn('2026-10-28', [d['date'] for d in api.dates()['items']])

    def test_later_pull_replaces_whole_day(self):
        store.save_curve('320000000000', '2026-10-27', [{'slot_end': m, 'raw_time': '', 'day_ahead': 1, 'real_time': 2} for m in (15, 30)], store.now())
        store.save_curve('320000000000', '2026-10-27', [{'slot_end': 15, 'raw_time': '', 'day_ahead': 3, 'real_time': None}], store.now())
        self.assertEqual(api.day('2026-10-27')['provinces'][0]['slots'], [{'end': 15, 'label': '00:15', 'day_ahead': 3, 'real_time': None}])

    def test_expired_token_is_reported(self):
        store.write_token('old')
        with patch.object(fetcher, 'client', upstream()):
            result = asyncio.run(fetcher.fetch_once())
        self.assertFalse(result['ok'])
        status = api.status()
        self.assertEqual(status['state'], 'expired')
        self.assertNotIn('old', json.dumps(status))

    def test_missing_token(self):
        self.assertEqual(api.status()['state'], 'missing')

    def test_update_token_validates_before_saving(self):
        async def run(token):
            return await api.update_token(api.TokenUpdate(token=token), x_admin_key='')
        with patch.object(fetcher, 'client', upstream('Bearer-less-good-token')):
            api._last_attempt = None
            self.assertFalse(asyncio.run(run('wrong-token-value'))['ok'])
            self.assertIsNone(store.read_token())
            api._last_attempt = None
            self.assertTrue(asyncio.run(run('Bearer Bearer-less-good-token'))['ok'])
        self.assertEqual(store.read_token()['token'], 'Bearer-less-good-token')
        self.assertEqual(oct(os.stat(store.token_path()).st_mode & 0o777), '0o600')

    def test_update_token_requires_admin_key_when_configured(self):
        with patch.dict(os.environ, {'PRICE_ADMIN_KEY': 'secret'}):
            with self.assertRaises(HTTPException) as caught:
                asyncio.run(api.update_token(api.TokenUpdate(token='x'*20), x_admin_key='nope'))
        self.assertEqual(caught.exception.status_code, 403)
        (store.ROOT/'admin_key').write_text('from-file\n')
        with self.assertRaises(HTTPException):
            asyncio.run(api.update_token(api.TokenUpdate(token='x'*20), x_admin_key='nope'))

    def test_next_run_includes_late_pull(self):
        self.assertEqual(fetcher.next_run(datetime(2026, 10, 27, 23, 20, tzinfo=store.CST)).strftime('%H:%M'), '23:50')
        self.assertEqual(fetcher.next_run(datetime(2026, 10, 27, 23, 55, tzinfo=store.CST)).strftime('%d %H:%M'), '28 00:10')
        self.assertEqual(fetcher.next_run(datetime(2026, 10, 27, 9, 5, tzinfo=store.CST)).strftime('%H:%M'), '09:10')


if __name__ == '__main__':
    unittest.main()
