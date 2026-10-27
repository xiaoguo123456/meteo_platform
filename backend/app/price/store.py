"""现货出清电价存储：曲线和各省均价按日沉淀到 SQLite，token 单独存文件，不进数据库和接口。"""
import base64
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(os.getenv('PRICE_DATA_DIR', str(Path(__file__).resolve().parents[3]/'data/price')))
CST = timezone(timedelta(hours=8))
# 实测 9:31 签发、20:31 已失效，按 11 小时估算；服务端实际判定以 401 为准。
TOKEN_LIFETIME = timedelta(hours=11)


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def today():
    return datetime.now(CST).date().isoformat()


@contextmanager
def db():
    ROOT.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(ROOT/'price.sqlite', timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA journal_mode=WAL')
    connection.execute('PRAGMA busy_timeout=15000')
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def initialize():
    with db() as c:
        c.executescript('''
        -- 单省单日曲线。slot_end 为时段结束时刻距当日 0 点的分钟数（15..1440），广东已从时段开始换算。
        CREATE TABLE IF NOT EXISTS clear_price_curve(
          area_code TEXT NOT NULL,trade_date TEXT NOT NULL,slot_end INTEGER NOT NULL,
          raw_time TEXT NOT NULL,day_ahead REAL,real_time REAL,fetched_at TEXT NOT NULL,
          PRIMARY KEY(area_code,trade_date,slot_end));
        CREATE INDEX IF NOT EXISTS clear_price_curve_date ON clear_price_curve(trade_date);
        -- 各省日均价；price_type 为 day_ahead / real_time。
        CREATE TABLE IF NOT EXISTS province_average(
          info_date TEXT NOT NULL,price_type TEXT NOT NULL,area_code TEXT NOT NULL,area_name TEXT NOT NULL,
          average_price REAL,solar_mechanism_price REAL,wind_mechanism_price REAL,market_reference_price REAL,
          fetched_at TEXT NOT NULL,PRIMARY KEY(info_date,price_type,area_code));
        CREATE TABLE IF NOT EXISTS fetch_runs(
          id INTEGER PRIMARY KEY,started_at TEXT NOT NULL,finished_at TEXT,ok INTEGER NOT NULL DEFAULT 0,
          message TEXT NOT NULL DEFAULT '',curves INTEGER NOT NULL DEFAULT 0,averages INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY,value TEXT);
        ''')


def get_state(key, default=None):
    with db() as c:
        row = c.execute('SELECT value FROM state WHERE key=?', (key,)).fetchone()
    return json.loads(row[0]) if row else default


def set_state(key, value):
    with db() as c:
        c.execute('INSERT OR REPLACE INTO state VALUES(?,?)', (key, json.dumps(value, ensure_ascii=False)))


def token_path():
    return ROOT/'token.json'


def read_token():
    """优先读接口写入的 token，没有时回退到环境变量 PRICE_TOKEN。"""
    path = token_path()
    if path.exists():
        value = json.loads(path.read_text())
        if value.get('token'):
            return value
    token = os.getenv('PRICE_TOKEN', '').strip()
    return {'token': token, 'updated_at': None, 'source': 'env'} if token else None


def write_token(token):
    ROOT.mkdir(parents=True, exist_ok=True)
    path = token_path()
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps({'token': token, 'updated_at': now()}))
    os.chmod(temp, 0o600)
    temp.replace(path)


def issued_at(token):
    """JWT 没有 exp，只尝试读 iat；读不到时由调用方用更新时间代替。"""
    try:
        payload = token.split('.')[1]
        value = json.loads(base64.urlsafe_b64decode(payload + '='*(-len(payload) % 4)))
        iat = value.get('iat')
        return datetime.fromtimestamp(int(iat), timezone.utc).isoformat(timespec='seconds') if iat else None
    except (IndexError, ValueError, TypeError):
        return None


def save_curve(area_code, trade_date, slots, fetched_at):
    """整日替换：最新一次拉取就是这一天的最好版本，避免旧的预出清值残留在后面的时段。"""
    with db() as c:
        c.execute('DELETE FROM clear_price_curve WHERE area_code=? AND trade_date=?', (area_code, trade_date))
        c.executemany('INSERT INTO clear_price_curve VALUES(?,?,?,?,?,?,?)',
                      [(area_code, trade_date, s['slot_end'], s['raw_time'], s['day_ahead'], s['real_time'], fetched_at) for s in slots])


def save_averages(info_date, price_type, rows, fetched_at):
    with db() as c:
        c.executemany('''INSERT INTO province_average VALUES(?,?,?,?,?,?,?,?,?)
          ON CONFLICT(info_date,price_type,area_code) DO UPDATE SET area_name=excluded.area_name,
          average_price=coalesce(excluded.average_price,province_average.average_price),
          solar_mechanism_price=excluded.solar_mechanism_price,wind_mechanism_price=excluded.wind_mechanism_price,
          market_reference_price=excluded.market_reference_price,fetched_at=excluded.fetched_at''',
                      [(info_date, price_type, r['area_code'], r['area_name'], r['average_price'], r['solar_mechanism_price'],
                        r['wind_mechanism_price'], r['market_reference_price'], fetched_at) for r in rows])
