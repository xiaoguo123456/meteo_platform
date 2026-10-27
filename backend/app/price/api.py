import asyncio
import hmac
import os
import time
from datetime import datetime

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from . import store
from .fetcher import AREAS, TokenExpired, UpstreamError, fetch_once, mark_token, validate

router = APIRouter(prefix='/api/price')
DATE = r'^\d{4}-\d{2}-\d{2}$'
# 更新 token 会真实请求一次上游，限制尝试频率。
TOKEN_ATTEMPT_GAP = 5
_last_attempt = None
_background = set()


class TokenUpdate(BaseModel):
    token: str = Field(min_length=10, max_length=4096)


def clock(minutes):
    return f'{minutes//60:02d}:{minutes % 60:02d}'


def admin_key():
    """管理密钥：环境变量 PRICE_ADMIN_KEY 或数据目录下的 admin_key 文件；都没有时不校验。"""
    path = store.ROOT/'admin_key'
    return os.getenv('PRICE_ADMIN_KEY', '').strip() or (path.read_text().strip() if path.exists() else '')


@router.get('/status')
def status():
    """只返回 token 状态，不返回 token 本身。"""
    store.initialize()
    saved = store.read_token()
    value = store.get_state('token', {}) or {}
    issued = None
    if saved:
        issued = store.issued_at(saved['token']) or saved.get('updated_at')
    with store.db() as c:
        run = c.execute('SELECT started_at,finished_at,ok,message,curves,averages FROM fetch_runs ORDER BY id DESC LIMIT 1').fetchone()
        success = c.execute('SELECT max(fetched_at) FROM clear_price_curve').fetchone()[0]
    return {
        'state': value.get('state', 'unchecked') if saved else 'missing',
        'message': value.get('message', ''),
        'checked_at': value.get('checked_at'),
        'token_updated_at': saved.get('updated_at') if saved else None,
        'issued_at': issued,
        'estimated_expire_at': (datetime.fromisoformat(issued) + store.TOKEN_LIFETIME).isoformat() if issued else None,
        'last_data_at': success,
        'next_run_at': store.get_state('next_run_at'),
        'last_run': dict(run) if run else None,
    }


@router.post('/token')
async def update_token(payload: TokenUpdate, x_admin_key: str = Header(default='')):
    """先用新 token 真实请求一次，成功才保存；返回 ok 表示是否已更新。"""
    global _last_attempt
    key = admin_key()
    if key and not hmac.compare_digest(x_admin_key, key):
        raise HTTPException(403, '管理密钥不正确')
    if _last_attempt is not None and time.monotonic() - _last_attempt < TOKEN_ATTEMPT_GAP:
        raise HTTPException(429, '操作太频繁，请稍后再试')
    _last_attempt = time.monotonic()
    token = payload.token.strip().removeprefix('Bearer ').strip()
    try:
        await validate(token)
    except TokenExpired as error:
        return {'ok': False, 'message': f'token 无效或已过期：{error}'}
    except UpstreamError as error:
        return {'ok': False, 'message': f'上游接口请求失败，未保存：{error}'}
    store.initialize()
    store.write_token(token)
    mark_token('valid')
    task = asyncio.create_task(fetch_once())
    _background.add(task)
    task.add_done_callback(_background.discard)
    return {'ok': True, 'message': 'token 已更新，正在后台拉取最新数据'}


@router.get('/dates')
def dates():
    store.initialize()
    with store.db() as c:
        curve = {r[0] for r in c.execute('SELECT DISTINCT trade_date FROM clear_price_curve')}
        average = {r[0] for r in c.execute('SELECT DISTINCT info_date FROM province_average WHERE average_price IS NOT NULL')}
    return {'items': [{'date': d, 'has_curve': d in curve, 'has_average': d in average} for d in sorted(curve | average, reverse=True)]}


@router.get('/day')
def day(date: str = Query('', pattern=r'^$|' + DATE)):
    store.initialize()
    with store.db() as c:
        if not date:
            date = c.execute('SELECT max(trade_date) FROM clear_price_curve').fetchone()[0] or store.today()
        rows = c.execute('SELECT * FROM clear_price_curve WHERE trade_date=? ORDER BY area_code,slot_end', (date,)).fetchall()
        average_rows = c.execute('SELECT * FROM province_average WHERE info_date=?', (date,)).fetchall()
    curves = {}
    for r in rows:
        curves.setdefault(r['area_code'], []).append(r)
    provinces = []
    for area in AREAS:
        slots = curves.get(area['code'])
        if not slots:
            continue
        provinces.append({'area_code': area['code'], 'name': area['name'], 'basis': area['basis'], 'points': len(slots),
                          'fetched_at': max(s['fetched_at'] for s in slots),
                          'slots': [{'end': s['slot_end'], 'label': clock(s['slot_end']), 'day_ahead': s['day_ahead'], 'real_time': s['real_time']} for s in slots]})
    merged = {}
    for r in average_rows:
        item = merged.setdefault(r['area_code'], {'area_code': r['area_code'], 'area_name': r['area_name'], 'day_ahead': None, 'real_time': None,
                                                  'solar_mechanism_price': r['solar_mechanism_price'], 'wind_mechanism_price': r['wind_mechanism_price']})
        item[r['price_type']] = None if r['average_price'] is None else round(r['average_price'], 2)
    averages = sorted(merged.values(), key=lambda v: (v['day_ahead'] is None, -(v['day_ahead'] or 0)))
    return {'date': date, 'is_today': date == store.today(), 'provinces': provinces, 'averages': averages}
