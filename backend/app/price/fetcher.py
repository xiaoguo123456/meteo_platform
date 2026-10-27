"""第三方小程序的现货出清电价接口；私有接口，只做低频拉取。说明见 docs/data-sources/clear-price.md。"""
import asyncio
import logging
import random
from datetime import datetime, timedelta

import httpx

from . import store

BASE = 'https://elecheck.aienertech.cn/electricCheckApi'
# 2026-10-27 实测均价排行返回的全部区域；蒙西明细为空，仍保留以便上游补上后自动有数据。
# 均价排行里出现的新区域也会自动加入（见 areas()）。
AREAS = [
    {'code': '130000000001', 'name': '河北南网'}, {'code': '140000000000', 'name': '山西'},
    {'code': '150000000000', 'name': '蒙西'}, {'code': '150000000001', 'name': '蒙东'},
    {'code': '210000000000', 'name': '辽宁'}, {'code': '220000000000', 'name': '吉林'},
    {'code': '230000000000', 'name': '黑龙江'}, {'code': '310000000000', 'name': '上海'},
    {'code': '320000000000', 'name': '江苏'}, {'code': '330000000000', 'name': '浙江'},
    {'code': '340000000000', 'name': '安徽'}, {'code': '350000000000', 'name': '福建'},
    {'code': '360000000000', 'name': '江西'}, {'code': '370000000000', 'name': '山东'},
    {'code': '410000000000', 'name': '河南'}, {'code': '420000000000', 'name': '湖北'},
    {'code': '430000000000', 'name': '湖南'}, {'code': '440000000000', 'name': '广东'},
    {'code': '450000000000', 'name': '广西'}, {'code': '460000000000', 'name': '海南'},
    {'code': '500000000000', 'name': '重庆'}, {'code': '510000000000', 'name': '四川'},
    {'code': '520000000000', 'name': '贵州'}, {'code': '530000000000', 'name': '云南'},
    {'code': '610000000000', 'name': '陕西'}, {'code': '620000000000', 'name': '甘肃'},
    {'code': '630000000000', 'name': '青海'}, {'code': '640000000000', 'name': '宁夏'},
    {'code': '650000000000', 'name': '新疆'},
]
VALIDATE_AREA = '320000000000'
# 拉取时间不固定：白天间隔 40–80 分钟，凌晨 1–6 点放宽到 90–150 分钟；
# 每天 23:25–23:55 之间随机补拉一次，让实时价尽量接近最终值；0:00–0:20 跨日附近不拉。
DAY_GAP = (40, 80)
NIGHT_GAP = (90, 150)
NIGHT_HOURS = range(1, 6)
LATE_WINDOW = ((23, 25), (23, 55))
DAWN_QUIET = 20
# 单个请求之间随机等 0.8–2.5 秒，省份和均价的请求顺序每轮打乱。
REQUEST_GAP = (0.8, 2.5)
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


def minutes_of(text):
    hour, minute = (int(x) for x in text.split(':'))
    return hour*60 + minute


def period_start(times):
    """按返回的时刻判断口径：出现 00:00 说明标的是时段开始（如广东 00:00–23:00），否则是时段结束（00:15–24:00）。"""
    return 0 in {minutes_of(t) for t in times}


def parse_curve(data):
    """点间隔可能不均匀（重庆有实时价的时段 5 分钟一个点，其余 15 分钟），按相邻时刻推算每个时段。"""
    rows = sorted((r for r in data or [] if r.get('time96')), key=lambda r: minutes_of(r['time96']))
    if not rows:
        return []
    times = [minutes_of(r['time96']) for r in rows]
    # 时段开始口径：时段结束就是下一个点的时刻，最后一个点到 24:00。
    ends = times[1:] + [1440] if period_start(r['time96'] for r in rows) else times
    return [{'slot_end': end, 'raw_time': row['time96'], 'day_ahead': number(row.get('avgDayAheadPrice')),
             'real_time': number(row.get('avgRealTimePrice'))} for end, row in zip(ends, rows)]


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
        await call(http, '/queryData/clearPrice/detail', {'dateType': 0, 'areaCode': VALIDATE_AREA}, token)


def areas():
    """固定列表加上近 7 天均价排行里出现过的新区域。"""
    known = {a['code'] for a in AREAS}
    with store.db() as c:
        extra = c.execute('''SELECT area_code,max(area_name) FROM province_average
          WHERE info_date>=date(?, '-7 day') GROUP BY area_code''', (store.today(),)).fetchall()
    return AREAS + [{'code': code, 'name': name} for code, name in extra if code not in known]


def settled_today(trade_date):
    """当天已入库且没有实时价的省份：日前价一天只发布一次，非完整轮次不再重复请求。"""
    with store.db() as c:
        rows = c.execute('''SELECT area_code FROM clear_price_curve WHERE trade_date=?
          GROUP BY area_code HAVING count(real_time)=0''', (trade_date,)).fetchall()
    empty = store.get_state('empty_curves', {}) or {}
    return {r[0] for r in rows} | set(empty.get(trade_date, []))


async def pause():
    await asyncio.sleep(random.uniform(*REQUEST_GAP))


async def fetch_once(full=None):
    async with LOCK:
        return await _fetch_once(full)


async def _fetch_once(full=None):
    """完整轮次请求全部省份和全部均价；其余轮次只刷新有实时价的省份和会变化的均价。
    不指定时，当天第一次成功拉取算完整轮次，token 断档恢复后也会自动补齐。"""
    store.initialize()
    token = (store.read_token() or {}).get('token')
    if not token:
        mark_token('missing', '未配置 token')
        return {'ok': False, 'message': '未配置 token'}
    started = store.now()
    trade_date = store.today()
    day = datetime.fromisoformat(trade_date)
    if full is None:
        full = store.get_state('full_date') != trade_date
    skip = set() if full else settled_today(trade_date)
    targets = [a for a in areas() if a['code'] not in skip]
    empty = []
    curves = averages = 0
    errors = []
    try:
        async with client() as http:
            for area in random.sample(targets, len(targets)):
                try:
                    slots = parse_curve(await call(http, '/queryData/clearPrice/detail', {'dateType': 0, 'areaCode': area['code']}, token))
                    if slots:
                        store.save_curve(area['code'], trade_date, slots, store.now())
                        curves += 1
                    else:
                        empty.append(area['code'])
                except UpstreamError as error:
                    errors.append(f"{area['name']}曲线：{error}")
                await pause()
            # 上游限制：日前价只能查 D-1～D+1，实时价只能查 D-3～D-1。
            # 完整轮次拉满，断档后可补回；其余轮次只拉当天、次日日前价和前一天实时价。
            plan = [(0, 'day_ahead'), (1, 'day_ahead'), (-1, 'real_time')]
            if full:
                plan += [(-1, 'day_ahead'), (-3, 'real_time'), (-2, 'real_time')]
            for offset, price_type in random.sample(plan, len(plan)):
                info_date = (day + timedelta(days=offset)).date().isoformat()
                try:
                    rows = parse_averages(await call(http, '/home/provinceAveragePriceBarChartData',
                                                     {'type': price_type, 'dateType': 1, 'sort': 2, 'infoDate': info_date}, token))
                    store.save_averages(info_date, price_type, rows, store.now())
                    averages += 1
                except UpstreamError as error:
                    errors.append(f'{info_date} {price_type} 均价：{error}')
                await pause()
    except TokenExpired as error:
        mark_token('expired', str(error))
        errors.append(f'token 失效：{error}')
    else:
        if curves or averages:
            mark_token('valid')
            if full and not errors:
                store.set_state('full_date', trade_date)
        elif errors:
            mark_token('error', errors[0])
        if full:
            store.set_state('empty_curves', {trade_date: empty})
    ok = not errors
    message = '；'.join(errors)[:1000]
    with store.db() as c:
        c.execute('INSERT INTO fetch_runs(started_at,finished_at,ok,message,curves,averages) VALUES(?,?,?,?,?,?)',
                  (started, store.now(), int(ok), message, curves, averages))
        c.execute('DELETE FROM fetch_runs WHERE id NOT IN (SELECT id FROM fetch_runs ORDER BY id DESC LIMIT 500)')
    if errors:
        log.warning('电价拉取未完全成功：%s', message)
    return {'ok': ok, 'message': message, 'full': full, 'requested': len(targets), 'curves': curves, 'averages': averages}


def next_run(after=None, rng=random):
    current = after or datetime.now(store.CST)
    gap = NIGHT_GAP if current.hour in NIGHT_HOURS else DAY_GAP
    target = current + timedelta(minutes=rng.uniform(*gap))
    (lh, lm), (eh, em) = LATE_WINDOW
    late_start = current.replace(hour=lh, minute=lm, second=0, microsecond=0)
    late_end = current.replace(hour=eh, minute=em, second=0, microsecond=0)
    # 每天必须在晚间窗口内拉一次，下一次若会跳过窗口就落进窗口里。
    if current < late_start and target > late_start:
        target = late_start + (late_end - late_start)*rng.random()
    # 跨日附近上游“当天”的切换时间不确定，推到 0:20 之后。
    quiet_end = target.replace(hour=0, minute=DAWN_QUIET, second=0, microsecond=0)
    if target < quiet_end:
        target = quiet_end + timedelta(minutes=rng.uniform(0, 30))
    return target.replace(microsecond=0)


def in_late_window(at=None):
    current = at or datetime.now(store.CST)
    (lh, lm), (eh, em) = LATE_WINDOW
    return (lh, lm) <= (current.hour, current.minute) <= (eh, em)


async def price_loop():
    store.initialize()
    await asyncio.sleep(20)
    while True:
        last = store.get_state('last_run_at')
        recent = last and datetime.now(store.CST) - datetime.fromisoformat(last) < timedelta(minutes=30)
        if not recent:
            try:
                await fetch_once(True if in_late_window() else None)
            except Exception:
                log.exception('电价拉取异常')
            store.set_state('last_run_at', datetime.now(store.CST).isoformat(timespec='seconds'))
        target = next_run()
        store.set_state('next_run_at', target.isoformat(timespec='seconds'))
        await asyncio.sleep(max(1, (target - datetime.now(store.CST)).total_seconds()))
