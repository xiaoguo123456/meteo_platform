"""原生 128×128 数值块，分块 gzip + 索引，按视野流式输出。"""
import gzip
import json
import struct
import threading
from collections import OrderedDict
import numpy as np
from .response_cache import pack_values
from .wind_grid import encode_grid
from .spatial_provider import SpatialDataError, MODEL_GRIDS

SIZE = 128
LOCKS = [threading.Lock() for _ in range(64)]
_BLOCK_CACHE: OrderedDict[tuple[str, int, int], bytes] = OrderedDict()
_BLOCK_CACHE_BYTES = 0
_BLOCK_CACHE_LIMIT = 256 * 1024 * 1024
_BLOCK_CACHE_LOCK = threading.Lock()


def _read_block(path, offset, length):
    """缓存已经压缩好的块，避免每次切换要素都重新触发大量随机磁盘读。"""
    global _BLOCK_CACHE_BYTES
    key = (str(path), int(offset), int(length))
    with _BLOCK_CACHE_LOCK:
        cached = _BLOCK_CACHE.get(key)
        if cached is not None:
            _BLOCK_CACHE.move_to_end(key)
            return cached
    with path.open('rb') as source:
        source.seek(offset)
        value = source.read(length)
    if len(value) != length:
        raise SpatialDataError('预报数据块读取不完整')
    with _BLOCK_CACHE_LOCK:
        old = _BLOCK_CACHE.pop(key, None)
        if old is not None:
            _BLOCK_CACHE_BYTES -= len(old)
        _BLOCK_CACHE[key] = value
        _BLOCK_CACHE_BYTES += len(value)
        while _BLOCK_CACHE_BYTES > _BLOCK_CACHE_LIMIT and _BLOCK_CACHE:
            _, removed = _BLOCK_CACHE.popitem(last=False)
            _BLOCK_CACHE_BYTES -= len(removed)
    return value


def tile_paths(folder, index, field, version=4, scale=1):
    stem = f'{index}.{field}.v{version}' + ('' if scale == 1 else f'.s{scale}')
    return folder/f'{stem}.blocks', folder/f'{stem}.json'


def half_resolution(arrays, meta):
    """缩小地球视图用：先做 [1,2,1] 平滑再隔点抽取，格点仍落在原网格偶数位置上。
    经向首尾相接，纬向边缘按镜像处理；原值缺测的位置保持缺测，邻点缺测不参与加权。
    结果按 0.1 取整，与源数据精度一致，字典编码才能保持紧凑。"""
    weights = np.array([1., 2., 1.])
    finite = np.isfinite(arrays)
    values = np.where(finite, arrays, 0).astype(np.float64)
    mask = finite.astype(np.float64)
    def smooth(data, axis):
        if axis == 2:
            return sum(w*np.roll(data, shift, axis=2) for w, shift in zip(weights, (1, 0, -1)))
        padded = np.concatenate([data[:, 1:2], data, data[:, -2:-1]], axis=1)
        return sum(w*padded[:, i:i+data.shape[1]] for w, i in zip(weights, (0, 1, 2)))
    total, count = smooth(smooth(values, 2), 1), smooth(smooth(mask, 2), 1)
    with np.errstate(invalid='ignore', divide='ignore'):
        averaged = np.round(total/count*10)/10
    averaged[~finite] = np.nan
    reduced = averaged[:, ::2, ::2].astype('<f4')
    return reduced, dict(meta, width=reduced.shape[2], height=reduced.shape[1], dx=meta['dx']*2, dy=meta['dy']*2, scale=2)


def prepare_tiles(folder, index, model, field, native, version=4, scale=1):
    data_path, index_path = tile_paths(folder, index, field, version, scale)
    with LOCKS[hash(str(data_path)) % len(LOCKS)]:
        if index_path.exists() and data_path.exists():
            return data_path, json.loads(index_path.read_text())
        raw = encode_grid(native, model, field)
        size = struct.unpack('<I', raw[:4])[0]
        meta = json.loads(raw[4:4+size])
        channels = 2 if field == 'wind' else 1
        arrays = np.frombuffer(raw, dtype='<f4', offset=4+size).reshape(2, meta['height'], meta['width'])[:channels]
        if scale == 2:
            arrays, meta = half_resolution(arrays, meta)
        entries = {}
        temporary = data_path.with_suffix('.tmp')
        columns = (meta['width']+SIZE-1)//SIZE
        with temporary.open('wb') as output:
            for y in range(0, meta['height'], SIZE):
                for x in range(0, meta['width'], SIZE):
                    block = arrays[:, y:y+SIZE, x:x+SIZE]
                    tile_meta = dict(meta, full_width=meta['width'], full_height=meta['height'],
                                     tile_x=x, tile_y=y, width=block.shape[2], height=block.shape[1])
                    packed = gzip.compress(pack_values(tile_meta, block.reshape(-1), channels, delta=version==4), compresslevel=6, mtime=0)
                    tile_id = str(y//SIZE*columns+x//SIZE)
                    entries[tile_id] = [output.tell(), len(packed)]
                    output.write(packed)
        temporary.replace(data_path)
        temporary_index = index_path.with_suffix('.tmp')
        temporary_index.write_text(json.dumps(entries))
        temporary_index.replace(index_path)
        return data_path, entries


def cached_tiles(model, field, run, valid, ids, version=3, scale=1):
    if version not in (3,4):
        raise SpatialDataError('不支持的数据编码版本')
    if scale not in (1, 2) or scale == 2 and version != 4:
        raise SpatialDataError('不支持的数据分辨率')
    from .forecast_cache import locate_field, ROOT, read_cached_native
    from .response_cache import FIELDS
    if field not in FIELDS:
        raise SpatialDataError('不支持的气象要素')
    grid = MODEL_GRIDS.get(model)
    if not grid:
        raise SpatialDataError('不支持的模型')
    width, height = (grid['width']+scale-1)//scale, (grid['height']+scale-1)//scale
    count = ((width+SIZE-1)//SIZE)*((height+SIZE-1)//SIZE)
    if not ids or len(ids)>count or any(i<0 or i>=count for i in ids) or len(set(ids))!=len(ids):
        raise SpatialDataError('请求的数据块范围无效')
    status, valid, index = locate_field(model, field, run, valid)
    folder = ROOT/model/status['key']
    data_path, index_path = tile_paths(folder, index, field, version, scale)
    # 升级压缩期间优先直接读取已完成的旧编码，禁止把批量编码工作推给交互请求。
    # 两个版本表示完全相同的原始数值，浏览器均支持；后台仍继续准备 v4。
    if version == 4 and scale == 1 and (not data_path.exists() or not index_path.exists()):
        previous_data = folder/f'{index}.{field}.v3.blocks'
        previous_index = folder/f'{index}.{field}.v3.json'
        if previous_data.exists() and previous_index.exists():
            data_path, index_path = previous_data, previous_index
    if not data_path.exists() or not index_path.exists():
        native = read_cached_native(model, field, status, valid, index)
        # 半分辨率在旧批次补齐前现场生成：只读本地快照，单帧十几个块，代价远小于整批编码。
        data_path, entries = prepare_tiles(folder, index, model, field, native, version, scale)
    else:
        entries = json.loads(index_path.read_text())
    def generate():
        for tile in ids:
            offset, length = entries[str(tile)]
            block = _read_block(data_path, offset, length)
            yield struct.pack('<I', length) + block
    return generate(), sum(4+entries[str(i)][1] for i in ids)
