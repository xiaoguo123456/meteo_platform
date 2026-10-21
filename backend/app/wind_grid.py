"""原生风矢量二进制接口：单进程合并请求，有限缓存，不降级。"""
import asyncio
import json
import struct
import time

import numpy as np
from .spatial_provider import read_native_snapshot, SpatialDataError, MODEL_VARIABLE_NAMES, MODEL_GRIDS

_cache = {}
_lock = asyncio.Lock()


def field_spec(model, field):
    """要素单位与层次，空间帧和省平均共用。"""
    level = "1000hPa" if model == "gfs" else "2m"
    specs = {"wind": ("m/s", "80m" if model == "gfs" else "10m"), "temperature": ("°C", level), "pressure": ("hPa", "海平面"),
             "humidity": ("%", level), "precipitation": ("mm", "地面 · 时段降水")}
    if field not in specs:
        raise SpatialDataError("不支持的气象要素")
    return specs[field]


def encode_grid(native, model, field="wind"):
    grid = MODEL_GRIDS.get(model)
    if grid is None:
        raise SpatialDataError("不支持的模型")
    shape = (grid["height"], grid["width"])
    field_spec(model, field)
    u, v = native['arrays']['u'], native['arrays']['v']
    if u.shape != shape or v.shape != u.shape:
        raise SpatialDataError('该模型网格尚未核验，暂不提供风场')
    if not np.isfinite(u).any() or not np.isfinite(v).any():
        raise SpatialDataError('S3 风分量没有有效值')
    meta = dict(model=model, source='open-meteo-s3', **grid, valid_time=native['valid_time'],
                units='m/s', level=field_spec(model, 'wind')[1],
                variables=[MODEL_VARIABLE_NAMES[model]['u'], MODEL_VARIABLE_NAMES[model]['v']],
                encoding='float32-le', missing='NaN')
    meta['field'] = field
    meta['run_time'] = native.get('run_time')
    if field != 'wind':
        if field not in native['arrays']:
            raise SpatialDataError('当前 S3 模型文件未提供' + {'temperature':'温度','humidity':'湿度','pressure':'气压','precipitation':'降水'}[field] + '数据')
        u = native['arrays'][field]
        if u.shape != shape or not np.isfinite(u).any():
            raise SpatialDataError('气象要素网格不完整')
        v = np.zeros_like(u)
        meta['units'], meta['level'] = field_spec(model, field)
        meta['variables'] = [MODEL_VARIABLE_NAMES[model][field]]
        if field == 'precipitation':
            meta['interval_start'] = native.get('interval_start')
    header = json.dumps(meta).encode()
    header += b' ' * (-len(header) % 4)
    return struct.pack('<I', len(header)) + header + np.asarray(u, dtype='<f4').tobytes() + np.asarray(v, dtype='<f4').tobytes()


async def wind_grid(model, field="wind"):
    async with _lock:
        entry = _cache.get(model)
        if entry and time.monotonic() - entry[0] < 300:
            native = entry[1]
        else:
            native = await asyncio.to_thread(read_native_snapshot, model)
            _cache[model] = (time.monotonic(), native)
        return encode_grid(native, model, field)
