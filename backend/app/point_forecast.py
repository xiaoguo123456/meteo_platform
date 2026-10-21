"""从本地原生数据块提取单点完整预报，不读取全球数组或访问上游。"""
import gzip
import json
import math
import struct
from functools import lru_cache
import numpy as np
from .spatial_provider import MODEL_GRIDS, SpatialDataError


def decode_values(raw):
    size = struct.unpack('<I', raw[:4])[0]
    meta = json.loads(raw[4:4+size])
    offset = 4+size
    if meta.get('encoding') in ('palette-u16-le','palette-delta-u16-le'):
        palette = np.frombuffer(raw, '<f4', count=meta['palette_size'], offset=offset)
        indices = np.frombuffer(raw, '<u2', offset=offset+4*meta['palette_size'])
        if meta['encoding']=='palette-delta-u16-le':
            indices = np.cumsum(indices.reshape(meta['channels'],meta['height'],meta['width']),axis=2,dtype=np.uint16).reshape(-1)
        values = palette[indices]
    else:
        values = np.frombuffer(raw, '<f4', offset=offset)
    return meta, values.reshape(meta.get('channels', 2), meta['height'], meta['width'])


@lru_cache(maxsize=256)
def _series(root, model, key, field, times, indices, row, col):
    from pathlib import Path
    folder = Path(root)/model/key
    columns = math.ceil(MODEL_GRIDS[model]['width']/128)
    tile = str(row//128*columns+col//128)
    points = []
    metadata = None
    for valid, index in zip(times, indices):
        version=4 if (folder/f'{index}.{field}.v4.json').exists() else 3
        prefix = folder/f'{index}.{field}.v{version}'
        entries = json.loads(prefix.with_suffix(f'.v{version}.json').read_text())
        offset, length = entries[tile]
        with prefix.with_suffix(f'.v{version}.blocks').open('rb') as source:
            source.seek(offset)
            metadata, values = decode_values(gzip.decompress(source.read(length)))
        components = values[:, row%128, col%128]
        value = float(np.hypot(*components)) if field == 'wind' else float(components[0])
        point = {'time': valid, 'value': value if math.isfinite(value) else None}
        if field == 'wind':
            direction = (math.degrees(math.atan2(-float(components[0]), -float(components[1])))+360)%360
            point['direction'] = direction if math.isfinite(direction) and value>0 else None
        points.append(point)
    return {'points':points, 'level':metadata.get('level') if metadata else None,
            'unit':metadata.get('unit') if metadata else None}


def point_forecast(model, field, longitude, latitude, run=None):
    from .forecast_cache import ROOT, read_run_status
    if model not in MODEL_GRIDS or not math.isfinite(longitude) or not math.isfinite(latitude) or not -180<=longitude<=180 or not -90<=latitude<=90:
        raise ValueError('经纬度或模型无效')
    status = read_run_status(model, run)
    times = tuple(status.get('field_times',{}).get(field, []))
    if not times:
        raise SpatialDataError('当前模型没有该要素的已缓存预报')
    m = MODEL_GRIDS[model]
    col = round(((longitude-m['lon0'])%360)/m['dx'])%m['width']
    row = max(0, min(m['height']-1, round((latitude-m['lat0'])/m['dy'])))
    indices = tuple(status['expected_times'].index(t) for t in times)
    result = _series(str(ROOT), model, status['key'], field, times, indices, row, col)
    return dict(result, model=model, field=field, run_time=status['run_time'], longitude=longitude, latitude=latitude,
                grid_longitude=m['lon0']+col*m['dx'], grid_latitude=m['lat0']+row*m['dy'], resolution=m['dx'])
