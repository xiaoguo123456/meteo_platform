"""第三方小程序的现货出清电价接口；私有接口，只做低频拉取。说明见 docs/data-sources/clear-price.md。"""
import asyncio
import logging
from datetime import datetime, timedelta

import httpx

from . import store

BASE = 'https://elecheck.aienertech.cn/electricCheckApi'
# basis：接口时刻是时段结束（end）还是时段开始（start）。只列实测过的省份。
AREAS = [
    {'code': '320000000000', 'name': '江苏', 'basis': 'end'},
    {'code': '140000000000', 'name': '山西', 'basis': 'end'},
    {'code': '620000000000', 'name': '甘肃', 'basis': 'end'},
    {'code': '330000000000', 'name': '浙江', 'basis': 'end'},
    {'code': '370000000000', 'name': '山东', 'basis': 'end'},
    {'code': '440000000000', 'name': '广东', 'basis': 'start'},
]
AREA_NAMES = {a['code']: a['name'] for a in AREAS}
# 每小时 10 分拉一次，当天 23:50 补拉一次，让实时价尽量接近最终值。
HOURLY_MINUTE = 10
LAST_PULL = (23, 50)
REQUEST_GAP = 0.6
LOCK = asyncio.Lock()
log = logging.getLogger(__name__)


class TokenExpired(Exception):
    pass


class UpstreamError(Exception):
    pass


def client():
    # 本机代理不可用时会直接失败，这里不读取代理环境变量。
    return httpx.AsyncClient(base_url=BASE, timeout=20, trust_env=False)


async def call(http, path, body, token):
    try:
        response = await http.post(path, json=body, headers={'Authorization': token})
    except httpx.HTTPError as error:
        raise UpstreamError(f'网络错误：{type(error).__name__}') from error
    try:
        payload = response.json()
    except ValueError as error:
        raise UpstreamError(f'HTTP {response.status_code}，返回不是 JSON') from error
    code = payload.get('code')
    if response.status_code == 401 or code == 401:
        raise TokenExpired(payload.get('msg') or payload.get('message') or 'Token 已过期')
    if code != 200:
        raise UpstreamError(payload.get('message') or payload.get('msg') or f'code {code}')
    return payload.get('data')


def number(value):
    if value in (None, ''):
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def parse_curve(data, basis):
    rows = [r for r in data or [] if r.get('time96')]
    if not rows:
        return []
    step = 1440 // len(rows)
    slots = []
    for row in rows:
        hour, minute = (int(x) for x in row['time96'].split(':'))
        minutes = hour*60 + minute
        slots.append({'slot_end': minutes + step if basis == 'start' else minutes, 'raw_time': row['time96'],
                      'day_ahead': number(row.get('avgDayAheadPrice')), 'real_time': number(row.get('avgRealTimePrice'))})
    return slots


def parse_averages(data):
    return [{'area_code': r['areaCode'], 'area_name': r.get('areaName') or r['areaCode'],
             'average_price': number(r.get('averagePrice')), 'solar_mechanism_price': number(r.get('electricityPrice')),
             'wind_mechanism_price': number(r.get('windElectricityPrice')),
             'market_reference_price': number(r.get('marketReferencePrice'))} for r in data or [] if r.get('areaCode')]


def mark_token(state, message=''):
    value = store.get_state('token', {}) or {}
    value.update({'state': state, 'checked_at': store.now(), 'message': message})
    if state == 'valid':
        value['last_success_at'] = value['checked_at']
    store.set_state('token', value)


async def validate(token):
    """用江苏当天曲线试一次，成功才算 token 可用。"""
    async with client() as http:
        await call(http, '/queryData/clearPrice/detail', {'dateType': 0, 'areaCode': AREAS[0]['code']}, token)


async def fetch_once():
    async with LOCK:
        return await _fetch_once()


async def _fetch_once():
    store.initialize()
    token = (store.read_token() or {}).get('token')
    if not token:
        mark_token('missing', '未配置 token')
        return {'ok': False, 'message': '未配置 token'}
    started = store.now()
    trade_date = store.today()
    day = datetime.fromisoformat(trade_date)
    curves = averages = 0
    errors = []
    try:
        async with client() as http:
            for area in AREAS:
                try:
                    slots = parse_curve(await call(http, '/queryData/clearPrice/detail', {'dateType': 0, 'areaCode': area['code']}, token), area['basis'])
                    if slots:
                        store.save_curve(area['code'], trade_date, slots, store.now())
                        curves += 1
                except UpstreamError as error:
                    errors.append(f"{area['name']}曲线：{error}")
                await asyncio.sleep(REQUEST_GAP)
            # 上游限制：日前价只能查 D-1～D+1，实时价只能查 D-3～D-1；实时价每次拉满三天，断档后可补回。
            plan = [(-1, 'day_ahead'), (0, 'day_ahead'), (1, 'day_ahead'), (-3, 'real_time'), (-2, 'real_time'), (-1, 'real_time')]
            for offset, price_type in plan:
                info_date = (day + timedelta(days=offset)).date().isoformat()
                try:
                    rows = parse_averages(await call(http, '/home/provinceAveragePriceBarChartData',
                                                     {'type': price_type, 'dateType': 1, 'sort': 2, 'infoDate': info_date}, token))
                    store.save_averages(info_date, price_type, rows, store.now())
                    averages += 1
                except UpstreamError as error:
                    errors.append(f'{info_date} {price_type} 均价：{error}')
                await asyncio.sleep(REQUEST_GAP)
    except TokenExpired as error:
        mark_token('expired', str(error))
        errors.append(f'token 失效：{error}')
    else:
        if curves or averages:
            mark_token('valid')
        elif errors:
            mark_token('error', errors[0])
    ok = not errors
    message = '；'.join(errors)[:1000]
    with store.db() as c:
        c.execute('INSERT INTO fetch_runs(started_at,finished_at,ok,message,curves,averages) VALUES(?,?,?,?,?,?)',
                  (started, store.now(), int(ok), message, curves, averages))
        c.execute('DELETE FROM fetch_runs WHERE id NOT IN (SELECT id FROM fetch_runs ORDER BY id DESC LIMIT 500)')
    if errors:
        log.warning('电价拉取未完全成功：%s', message)
    return {'ok': ok, 'message': message, 'curves': curves, 'averages': averages}


def next_run(after=None):
    current = after or datetime.now(store.CST)
    hourly = current.replace(minute=HOURLY_MINUTE, second=0, microsecond=0)
    if hourly <= current:
        hourly += timedelta(hours=1)
    last = current.replace(hour=LAST_PULL[0], minute=LAST_PULL[1], second=0, microsecond=0)
    return last if current < last < hourly else hourly


async def price_loop():
    store.initialize()
    await asyncio.sleep(20)
    while True:
        last = store.get_state('last_run_at')
        recent = last and datetime.now(store.CST) - datetime.fromisoformat(last) < timedelta(minutes=30)
        if not recent:
            try:
                await fetch_once()
            except Exception:
                log.exception('电价拉取异常')
            store.set_state('last_run_at', datetime.now(store.CST).isoformat(timespec='seconds'))
        target = next_run()
        store.set_state('next_run_at', target.isoformat(timespec='seconds'))
        await asyncio.sleep(max(1, (target - datetime.now(store.CST)).total_seconds()))
