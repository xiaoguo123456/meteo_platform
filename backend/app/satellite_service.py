"""葵花真彩色、红外观测主动缓存。JMA 原生 Mercator 瓦片无损拼接，不混入模型云量。"""
import asyncio
import io
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
import httpx
from PIL import Image

TARGET_TIMES_URL = 'https://www.jma.go.jp/bosai/himawari/data/satimg/targetTimes_fd.json'
ROOT = Path(os.getenv('METEO_DATA_DIR', str(Path(__file__).resolve().parents[2]/'data')))/'satellite/himawari'
KEEP = 36
PRODUCTS = {'truecolor': 'REP/ETC', 'infrared': 'B13/TBB'}


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


def image_path(time, product='truecolor'):
    if not re.fullmatch(r'\d{14}',time):raise ValueError('卫星观测时间无效')
    path=product_root(product)/f'{time}.webp'
    if not path.exists():raise FileNotFoundError('该卫星观测尚未缓存或已过期')
    return path


def display_path(time,product):
    path=image_path(time,product).with_suffix('.display.webp')
    if not path.exists():raise FileNotFoundError('卫星显示图正在准备')
    return path
