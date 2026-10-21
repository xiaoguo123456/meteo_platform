"""最新起报批次主动预取；接口只访问本地完整快照。"""
import asyncio
import json
import os
import time
import shutil
import fcntl
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from collections import deque
from pathlib import Path
from datetime import datetime, timezone
import numpy as np
from .spatial_provider import latest_manifest, read_native_snapshot, SpatialDataError, MODEL_SPATIAL_NAMES, model_fields
from .wind_grid import encode_grid
from .response_cache import prepare_snapshot, prepare_field, WIRE_MARKER
from .province_stats import write_frame_stats

# 一帧完成需要的全部文件：原始数据、浏览器数据块、省平均统计。
FRAME_FILES = ('npz', WIRE_MARKER, 'provinces.json')
ROOT = Path(os.getenv('WEATHER_FORECAST_CACHE', str(Path(__file__).resolve().parents[2] / 'data/cache/forecasts')))
STOP = threading.Event()
CONCURRENCY = max(1, min(4, int(os.getenv("WEATHER_DOWNLOAD_CONCURRENCY", "4"))))
INTERVAL = int(os.getenv('WEATHER_POLL_SECONDS', '300'))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False))
    temporary.replace(path)


def read_status(model):
    if model not in MODEL_SPATIAL_NAMES:
        raise SpatialDataError('不支持的模型')
    path = ROOT / model / 'status.json'
    if not path.exists():
        return {'model': model, 'run_time': None, 'times': [], 'total': 0, 'state': 'syncing', 'error': None}
    return json.loads(path.read_text())


def read_pending_status(model):
    """读取正在预取但尚未对外切换的起报批次。"""
    if model not in MODEL_SPATIAL_NAMES:
        raise SpatialDataError('不支持的模型')
    path = ROOT / model / 'status.pending.json'
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return None


def read_public_status(model):
    """返回当前可用批次，并附带后台待切换批次的进度。"""
    status = read_status(model)
    pending = read_pending_status(model)
    if not pending or pending.get('state') == 'ready':
        return status
    public = dict(status)
    public.update({
        'pending_run_time': pending.get('run_time'),
        'pending_cached': len(pending.get('times', [])),
        'pending_total': pending.get('total', 0),
        'pending_state': pending.get('state'),
        'pending_error': pending.get('error'),
    })
    return public


def read_run_status(model, run_time=None):
    """固定起报请求也可读取仍在保留期内的上一批，避免切换时拒绝在途请求。"""
    status = read_status(model)
    if not run_time or run_time == status.get('run_time'):
        return status
    try:
        key = datetime.fromisoformat(run_time.replace('Z', '+00:00')).strftime('%Y%m%dT%H%M')
        retained = json.loads((ROOT/model/key/'published.json').read_text())
        if retained.get('run_time') == run_time:
            return retained
    except (ValueError, FileNotFoundError):
        pass
    raise SpatialDataError('起报批次已更新，请刷新时间轴')


def frame_ready(folder, index):
    return all((folder/f'{index}.{suffix}').exists() for suffix in FRAME_FILES)


def sync_once(models=None):
    ROOT.mkdir(parents=True, exist_ok=True)
    with (ROOT / 'sync.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        _sync_once(tuple(models or MODEL_SPATIAL_NAMES))


def publish(context):
    status, folder = context['status'], context['folder']
    # 只统计连续完成的数据、响应与省平均文件，整批就绪前仅更新后台进度。
    available = []
    for i, valid in enumerate(status['expected_times']):
        if not frame_ready(folder, i):
            break
        available.append(valid)
    status['times'] = available
    field_times = {field: [] for field in model_fields(status['model'])}
    for i, valid in enumerate(available):
        metadata = folder / f'{i}.json'
        fields = json.loads(metadata.read_text()) if metadata.exists() else ('wind', 'temperature', 'humidity', 'pressure')
        for field in fields:
            if field in field_times:
                field_times[field].append(valid)
    status['field_times'] = field_times
    if status['total'] and len(available) == status['total'] and not status['error']:
        status['state'] = 'ready'
    model = status['model']
    active = read_status(model)
    active_path = ROOT/model/'status.json'
    pending_path = ROOT/model/'status.pending.json'
    # 发布指针只在整批完成后替换；先保存旧批次清单，固定批次请求仍可读取它。
    if status.get('state') == 'ready':
        if active.get('key') and active.get('times') and active.get('run_time') != status.get('run_time'):
            write_json(ROOT/model/active['key']/'published.json', active)
        write_json(folder/'published.json', status)
        write_json(active_path, status)
        pending_path.unlink(missing_ok=True)
    else:
        write_json(pending_path, status)


def download(context, index):
    status, folder = context['status'], context['folder']
    model = status['model']
    blocks = folder / f'blocks-{index}'
    temporary = folder / f'{index}.part'
    for attempt in range(2):
        try:
            if (folder / f'{index}.npz').exists():
                with np.load(folder / f'{index}.npz', allow_pickle=False) as snapshot:
                    arrays = {name:snapshot[name] for name in snapshot.files}
                native = dict(arrays=arrays, valid_time=status['expected_times'][index], run_time=status['run_time'])
                native['interval_start'] = status['expected_times'][index-1] if index else None
                prepare_snapshot(folder, index, model, native)
                # 旧批次升级后在此补算省平均，不重新下载。
                write_frame_stats(folder, index, model, arrays)
                return
            native = read_native_snapshot(model, context['manifest'], status['expected_times'][index], blocks)
            encode_grid(native, model)
            # 低级别无损压缩减少单机 CPU 争用，保持标准 NPZ 格式。
            with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=1) as output:
                for name, array in native['arrays'].items():
                    with output.open(name + '.npy', 'w', force_zip64=True) as entry:
                        np.lib.format.write_array(entry, array, allow_pickle=False)
            fields = ['wind'] + [name for name, array in native['arrays'].items() if name not in ('u', 'v') and np.isfinite(array).any()]
            write_json(folder / f'{index}.json', fields)
            native['interval_start'] = status['expected_times'][index-1] if index else None
            prepare_snapshot(folder, index, model, native)
            write_frame_stats(folder, index, model, native['arrays'])
            temporary.replace(folder / f'{index}.npz')
            return
        except Exception:
            if attempt or STOP.is_set():
                raise
        finally:
            shutil.rmtree(blocks, ignore_errors=True)
            temporary.unlink(missing_ok=True)


def _sync_once(models):
    contexts = []
    for model in models:
        status = read_pending_status(model) or read_status(model)
        try:
            manifest = latest_manifest(model)
            run = manifest['reference_time']
            key = datetime.fromisoformat(run.replace('Z', '+00:00')).strftime('%Y%m%dT%H%M')
            folder = ROOT/model/key
            folder.mkdir(parents=True, exist_ok=True)
            times = sorted(set(manifest['valid_times']))
            if not times:
                raise SpatialDataError('起报清单没有可缓存的预报时刻')
            status = dict(model=model, run_time=run, times=[], expected_times=times, total=len(times),
                          key=key, state='syncing', error=None, checked_at=datetime.now(timezone.utc).isoformat())
            context = dict(status=status, manifest=manifest, folder=folder,
                           pending=deque(i for i in range(len(times)) if not frame_ready(folder, i)))
            publish(context)
            contexts.append(context)
        except Exception as error:
            status.update(state='error', error=str(error))
            write_json(ROOT/model/'status.pending.json', status)

    # 全模型共用有界线程池；轮流提交近时效，某一模型失败不阻断其他模型。
    queue = deque(contexts)
    last_check = time.monotonic()
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        active = {}
        while queue or active:
            if STOP.is_set():
                return
            if time.monotonic() - last_check > INTERVAL:
                # 退出后重新读取每个模型的最新清单，续传未完成快照。
                return
            while queue and len(active) < CONCURRENCY:
                context = queue.popleft()
                if context['status']['error'] or not context['pending']:
                    continue
                index = context['pending'].popleft()
                active[pool.submit(download, context, index)] = context
                if context['pending']:
                    queue.append(context)
            if not active:
                break
            done, _ = wait(active, timeout=1, return_when=FIRST_COMPLETED)
            for future in done:
                context = active.pop(future)
                try:
                    future.result()
                except Exception as error:
                    context['status'].update(state='error', error=str(error))
                publish(context)
    for context in contexts:
        if context['status']['state'] != 'ready':
            continue
        # 保留当前批次与上一份已发布批次，不能让未完成目录挤掉可用旧批次。
        folders = sorted(p for p in (ROOT/context['status']['model']).iterdir()
                         if p.is_dir() and len(p.name) == 13 and 'T' in p.name)
        published = [p for p in folders if (p/'published.json').exists()]
        keep = set(published[-2:]) | {context['folder']}
        for old in (p for p in folders if p not in keep):
            shutil.rmtree(old)


async def sync_loop():
    STOP.clear()
    while not STOP.is_set():
        await asyncio.to_thread(sync_once)
        states = [
            (read_pending_status(model) or read_status(model))['state']
            for model in MODEL_SPATIAL_NAMES
        ]
        delay = 5 if 'syncing' in states else min(30, INTERVAL) if 'error' in states else INTERVAL
        await asyncio.sleep(delay)


def locate_field(model, field, run_time=None, valid_time=None):
    if model in MODEL_SPATIAL_NAMES and field not in model_fields(model):
        raise SpatialDataError('当前模型未提供该气象要素')
    status = read_run_status(model, run_time)
    if not status['times']:
        raise SpatialDataError(status.get('error') or '最新起报数据正在提前缓存，请稍后重试')
    valid = valid_time or status['times'][0]
    if valid not in status['times']:
        raise SpatialDataError('该预报时刻尚未缓存完成')
    index = status['expected_times'].index(valid)
    return status, valid, index


def read_cached_native(model, field, status, valid, index):
    with np.load(ROOT/model/status['key']/f'{index}.npz', allow_pickle=False) as snapshot:
        names = ('u', 'v') if field == 'wind' else ('u', 'v', field)
        arrays = {name:snapshot[name] for name in names if name in snapshot.files}
    return {'arrays':arrays, 'valid_time':valid, 'run_time':status['run_time'],
            'interval_start':status['expected_times'][index-1] if index else None}


def cached_field(model, field, run_time=None, valid_time=None):
    status, valid, index = locate_field(model, field, run_time, valid_time)
    return encode_grid(read_cached_native(model, field, status, valid, index), model, field)


def cached_response(model, field, run_time=None, valid_time=None):
    status, valid, index = locate_field(model, field, run_time, valid_time)
    return prepare_field(ROOT/model/status['key'], index, model, field,
                         lambda: read_cached_native(model, field, status, valid, index))
