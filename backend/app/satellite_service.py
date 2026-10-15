"""葵花真彩色、红外观测主动缓存。JMA 原生 Mercator 瓦片无损拼接，不混入模型云量。"""
import asyncio
import io
import json
import math
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import httpx
from PIL import Image

TARGET_TIMES_URL = 'https://www.jma.go.jp/bosai/himawari/data/satimg/targetTimes_fd.json'
ROOT = Path(os.getenv('METEO_DATA_DIR', str(Path(__file__).resolve().parents[2]/'data')))/'satellite/himawari'
KEEP = 36
PRODUCTS = {'truecolor': 'REP/ETC', 'infrared': 'B13/TBB'}
LOCAL_ZOOM = 5
LOCAL_CACHE_TTL = 300
_LOCAL_CACHE: dict[tuple[str, str], tuple[float, str, bytes]] = {}


def product_root(product):
    if product not in PRODUCTS: raise ValueError('卫星产品无效')
    return ROOT/product


def catalog(product='truecolor'):
    path = product_root(product)/'status.json'
    value = json.loads(path.read_text()) if path.exists() else {'source':'Himawari-9','times':[], 'error':None,'state':'syncing'}
    if value['times']:
        latest = datetime.strptime(value['times'][-1], '%Y%m%d%H%M%S').replace(tzinfo=timezone.utc)
        value['stale'] = (datetime.now(timezone.utc)-latest).total_seconds()>1800
    return value


def write_status(error=None, product='truecolor'):
    root=product_root(product);root.mkdir(parents=True,exist_ok=True)
    times=sorted(p.stem for p in root.glob('*.webp') if re.fullmatch(r'\d{14}',p.stem))
    for old in times[:-KEEP]:
        (root/f'{old}.webp').unlink(missing_ok=True)
        (root/f'{old}.display.webp').unlink(missing_ok=True)
    value={'source':'Himawari-9','product':product,'projection':'EPSG:3857','zoom':3,
           'times':times[-KEEP:],'error':error,'state':'error' if error else 'ready' if times else 'syncing',
           'checked_at':datetime.now(timezone.utc).isoformat()}
    temporary=root/'status.tmp';temporary.write_text(json.dumps(value));temporary.replace(root/'status.json')


def save_mosaic(time, tiles, product='truecolor'):
    root=product_root(product);root.mkdir(parents=True,exist_ok=True)
    image=Image.new('RGBA',(2048,2048))
    for x,y,body in tiles:
        if body is None:continue
        with Image.open(io.BytesIO(body)) as tile:
            if tile.size!=(256,256):raise ValueError('卫星瓦片尺寸发生变化')
            image.paste(tile.convert('RGBA'),(x*256,y*256))
    # 真彩色在本地夜间会返回全黑/空白帧，不发布这种帧，否则前端会看到整块黑图。
    if tiles and image.convert('RGB').getbbox() is None:
        raise ValueError('当前卫星真彩色没有可见光影像')
    temporary=root/f'{time}.part';image.save(temporary,format='WEBP',lossless=True,method=3);temporary.replace(root/f'{time}.webp')
    save_display(time,product)


def save_display(time,product):
    root=product_root(product)
    with Image.open(root/f'{time}.webp') as image:
        temporary=root/f'{time}.display.part'
        image.save(temporary,format='WEBP',quality=90,method=4)
        temporary.replace(root/f'{time}.display.webp')


def has_signal(path):
    try:
        with Image.open(path) as image:
            return image.convert('RGB').getbbox() is not None
    except Exception:
        return False


async def sync_satellite():
    ROOT.mkdir(parents=True,exist_ok=True)
    async with httpx.AsyncClient(timeout=25,follow_redirects=True) as client:
        response=await client.get(TARGET_TIMES_URL);response.raise_for_status()
        times=sorted({v['basetime'] for v in response.json() if re.fullmatch(r'\d{14}',v['basetime'])})[-KEEP:]
        for product in PRODUCTS:
            for existing in product_root(product).glob('*.webp'):
                if existing.name.endswith('.display.webp'):
                    continue
                if not has_signal(existing):
                    existing.unlink(missing_ok=True)
                    existing.with_name(f'{existing.stem}.display.webp').unlink(missing_ok=True)
        semaphore=asyncio.Semaphore(8)
        async def tile(t,x,y,product):
            async with semaphore:
                url=f'https://www.jma.go.jp/bosai/himawari/data/satimg/{t}/fd/{t}/{PRODUCTS[product]}/3/{x}/{y}.jpg'
                r=await client.get(url)
                if r.status_code==404:return x,y,None
                r.raise_for_status();return x,y,r.content
        # 每种产品先发布最新帧，再补历史；故障隔离，避免一种产品阻塞另一种。
        failed=set()
        for t in reversed(times):
            for product in PRODUCTS:
                if product in failed:continue
                existing = product_root(product)/f'{t}.webp'
                if existing.exists() and not has_signal(existing):
                    existing.unlink(missing_ok=True)
                    (product_root(product)/f'{t}.display.webp').unlink(missing_ok=True)
                if existing.exists():
                    if not (product_root(product)/f'{t}.display.webp').exists():
                        await asyncio.to_thread(save_display,t,product)
                    continue
                try:
                    tiles=await asyncio.gather(*(tile(t,x,y,product) for x in range(8) for y in range(8)))
                    if not any(body for _,_,body in tiles):raise ValueError('葵花观测瓦片尚未发布')
                    await asyncio.to_thread(save_mosaic,t,tiles,product)
                    write_status(product=product)
                except Exception as error:
                    failed.add(product);write_status(str(error) or type(error).__name__,product)
        for product in PRODUCTS:
            if product not in failed:write_status(product=product)


async def satellite_loop():
    while True:
        try:await sync_satellite()
        except asyncio.CancelledError:raise
        except Exception as error:
            for product in PRODUCTS:write_status(str(error) or type(error).__name__,product)
        await asyncio.sleep(300)


async def latest_himawari(product='truecolor'):
    return catalog(product)


def _lonlat_to_tile(lon: float, lat: float, zoom: int) -> tuple[float, float]:
    n = 2 ** zoom
    x = (lon + 180.0) / 360.0 * n
    lat_r = math.radians(max(-85.05, min(85.05, lat)))
    y = (1.0 - math.log(math.tan(lat_r) + 1.0 / math.cos(lat_r)) / math.pi) / 2.0 * n
    return x, y


def _local_tile_range(lon: float, lat: float, zoom: int = LOCAL_ZOOM) -> tuple[int, int, int, int]:
    # 与小程序相同：按站点周边约 16°×12° 的局部 bbox 取瓦片，不加载全球影像。
    west, east = lon - 8.0, lon + 8.0
    south, north = max(-80.0, lat - 6.0), min(80.0, lat + 6.0)
    x0, y0 = (int(v) for v in _lonlat_to_tile(west, north, zoom))
    x1, y1 = (int(v) for v in _lonlat_to_tile(east, south, zoom))
    limit = 2 ** zoom - 1
    return max(0, x0), max(0, y0), min(limit, x1), min(limit, y1)


def local_image_bounds(longitude: float, latitude: float, zoom: int = LOCAL_ZOOM) -> tuple[float, float, float, float]:
    """返回局部拼图的 Web Mercator 地理范围（west, south, east, north）。"""
    x0, y0, x1, y1 = _local_tile_range(longitude, latitude, zoom)
    n = 2 ** zoom

    def lon(x: int) -> float:
        return x / n * 360.0 - 180.0

    def lat(y: int) -> float:
        return math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * y / n))))

    return lon(x0), lat(y1 + 1), lon(x1 + 1), lat(y0)


async def station_image(station_key: str, latitude: float, longitude: float, product: str = 'truecolor') -> tuple[str, bytes]:
    """按站点 bbox 获取葵花 Web Mercator 局部瓦片并拼图，避免裁剪全球空白图。"""
    if product not in PRODUCTS:
        raise ValueError('卫星产品无效')
    cache_key = (station_key, product)
    cached = _LOCAL_CACHE.get(cache_key)
    if cached and time.monotonic() - cached[0] < LOCAL_CACHE_TTL:
        return cached[1], cached[2]
    async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
        response = await client.get(TARGET_TIMES_URL)
        response.raise_for_status()
        times = sorted({item.get('basetime') or item.get('validtime') for item in response.json() if re.fullmatch(r'\d{14}', item.get('basetime', '') or item.get('validtime', ''))})
        if not times:
            raise RuntimeError('葵花观测暂无可用时刻')
        observed = times[-1]
        x0, y0, x1, y1 = _local_tile_range(longitude, latitude)
        semaphore = asyncio.Semaphore(8)

        async def fetch_tile(x: int, y: int) -> tuple[int, int, Optional[bytes]]:
            url = f'https://www.jma.go.jp/bosai/himawari/data/satimg/{observed}/fd/{observed}/{PRODUCTS[product]}/{LOCAL_ZOOM}/{x}/{y}.jpg'
            async with semaphore:
                tile_response = await client.get(url)
            if tile_response.status_code == 404:
                return x, y, None
            tile_response.raise_for_status()
            return x, y, tile_response.content

        tiles = await asyncio.gather(*(fetch_tile(x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)))
    if not any(body for _, _, body in tiles):
        raise RuntimeError('葵花局部瓦片尚未发布')
    cols, rows = x1 - x0 + 1, y1 - y0 + 1
    image = Image.new('RGBA', (cols * 256, rows * 256), (235, 243, 243, 255))
    for x, y, body in tiles:
        if body:
            with Image.open(io.BytesIO(body)) as tile:
                tile_image = tile.convert('RGBA')
                # JMA 真彩色全圆盘边缘的无效区域是纯黑色，透明化后由卡片底色承接，避免出现突兀黑三角。
                if product == 'truecolor':
                    luminance = tile_image.convert('RGB').convert('L')
                    tile_image.putalpha(luminance.point(lambda value: 0 if value < 8 else 255))
                image.alpha_composite(tile_image, ((x - x0) * 256, (y - y0) * 256))
    output = io.BytesIO()
    image.save(output, format='WEBP', quality=88, method=4)
    result = output.getvalue()
    _LOCAL_CACHE[cache_key] = (time.monotonic(), observed, result)
    return observed, result


def image_path(time, product='truecolor'):
    if not re.fullmatch(r'\d{14}',time):raise ValueError('卫星观测时间无效')
    path=product_root(product)/f'{time}.webp'
    if not path.exists():raise FileNotFoundError('该卫星观测尚未缓存或已过期')
    return path


def display_path(time,product):
    path=image_path(time,product).with_suffix('.display.webp')
    if not path.exists():raise FileNotFoundError('卫星显示图正在准备')
    return path
