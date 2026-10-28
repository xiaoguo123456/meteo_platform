"""提前生成浏览器响应：无损字典编码、预压缩、磁盘复用。"""
import gzip
import json
import struct
import threading
from pathlib import Path
import numpy as np
from .wind_grid import encode_grid
from .spatial_provider import FIELDS, model_fields

LOCKS = [threading.Lock() for _ in range(64)]
PREPARE = threading.Semaphore(1)
# 浏览器数据块齐备标记；新增要素或数据块规格时升级版本，旧批次据此从本地 NPZ 补生成。
# v6：新增缩小视图用的半分辨率数据块。
WIRE_MARKER = 'wire-v6'


def pack_grid(native, model, field):
    raw = encode_grid(native, model, field)
    size = struct.unpack('<I', raw[:4])[0]
    meta = json.loads(raw[4:4+size])
    channels = 2 if field == 'wind' else 1
    values = np.frombuffer(raw, dtype='<f4', offset=4+size)[:meta['width']*meta['height']*channels]
    return pack_values(meta, values, channels)


def pack_values(meta, values, channels, delta=False):
    meta = dict(meta)
    palette, inverse = np.unique(values, return_inverse=True)
    meta['channels'] = channels
    if len(palette) <= 65536:
        meta.update(encoding='palette-u16-le', palette_size=len(palette))
        indices = inverse.astype('<u2')
        if delta:
            shaped = indices.reshape(channels, meta['height'], meta['width'])
            encoded = shaped.copy()
            encoded[:,:,1:] = shaped[:,:,1:] - shaped[:,:,:-1]
            indices = encoded
            meta['encoding'] = 'palette-delta-u16-le'
        body = palette.astype('<f4').tobytes() + indices.tobytes()
    else:
        meta['encoding'] = 'float32-le'
        body = values.tobytes()
    header = json.dumps(meta).encode()
    header += b' ' * (-len(header) % 4)
    return struct.pack('<I', len(header)) + header + body


def response_path(folder, index, field):
    if field not in FIELDS:
        from .spatial_provider import SpatialDataError
        raise SpatialDataError('不支持的气象要素')
    return folder / f'{index}.{field}.v2.gz'


def prepare_field(folder, index, model, field, native_factory):
    path = response_path(folder, index, field)
    with LOCKS[hash(str(path)) % len(LOCKS)]:
        if not path.exists():
            payload = pack_grid(native_factory(), model, field)
            temporary = path.with_suffix('.tmp')
            temporary.write_bytes(gzip.compress(payload, compresslevel=6, mtime=0))
            temporary.replace(path)
    return path


def prepare_snapshot(folder, index, model, native):
    # 压缩为 CPU 工作，只开一路，给 API 和下载保留资源。
    with PREPARE:
        for field in model_fields(model):
            if field == 'wind' or field in native['arrays'] and np.isfinite(native['arrays'][field]).any():
                from .tile_cache import prepare_tiles
                prepare_tiles(folder, index, model, field, native)
                prepare_tiles(folder, index, model, field, native, scale=2)
        (folder / f'{index}.{WIRE_MARKER}').touch()
