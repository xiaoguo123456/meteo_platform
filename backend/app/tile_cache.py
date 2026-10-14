"""原生 128×128 数值块，分块 gzip + 索引，按视野流式输出。"""
import gzip
import json
import struct
import threading
import numpy as np
from .response_cache import pack_values
from .wind_grid import encode_grid
from .spatial_provider import SpatialDataError, MODEL_GRIDS

SIZE = 128
LOCKS = [threading.Lock() for _ in range(64)]


def prepare_tiles(folder, index, model, field, native, version=4):
    prefix = folder / f'{index}.{field}.v{version}'
    data_path, index_path = prefix.with_suffix(f'.v{version}.blocks'), prefix.with_suffix(f'.v{version}.json')
    with LOCKS[hash(str(prefix)) % len(LOCKS)]:
        if index_path.exists() and data_path.exists():
            return data_path, json.loads(index_path.read_text())
        raw = encode_grid(native, model, field)
        size = struct.unpack('<I', raw[:4])[0]
        meta = json.loads(raw[4:4+size])
        channels = 2 if field == 'wind' else 1
        arrays = np.frombuffer(raw, dtype='<f4', offset=4+size).reshape(2, meta['height'], meta['width'])[:channels]
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


def cached_tiles(model, field, run, valid, ids, version=3):
    if version not in (3,4):
        raise SpatialDataError('不支持的数据编码版本')
    from .forecast_cache import locate_field, ROOT, read_cached_native
    from .response_cache import FIELDS
    if field not in FIELDS:
        raise SpatialDataError('不支持的气象要素')
    grid = MODEL_GRIDS.get(model)
    if not grid:
        raise SpatialDataError('不支持的模型')
    count = ((grid['width']+SIZE-1)//SIZE)*((grid['height']+SIZE-1)//SIZE)
    if not ids or len(ids)>count or any(i<0 or i>=count for i in ids) or len(set(ids))!=len(ids):
        raise SpatialDataError('请求的数据块范围无效')
    status, valid, index = locate_field(model, field, run, valid)
    folder = ROOT/model/status['key']
    data_path = folder/f'{index}.{field}.v{version}.blocks'
    index_path = folder/f'{index}.{field}.v{version}.json'
    # 升级压缩期间优先直接读取已完成的旧编码，禁止把批量编码工作推给交互请求。
    # 两个版本表示完全相同的原始数值，浏览器均支持；后台仍继续准备 v4。
    if version == 4 and (not data_path.exists() or not index_path.exists()):
        previous_data = folder/f'{index}.{field}.v3.blocks'
        previous_index = folder/f'{index}.{field}.v3.json'
        if previous_data.exists() and previous_index.exists():
            data_path, index_path = previous_data, previous_index
    if not data_path.exists() or not index_path.exists():
        native = read_cached_native(model, field, status, valid, index)
        data_path, entries = prepare_tiles(folder, index, model, field, native, version)
    else:
        entries = json.loads(index_path.read_text())
    # 在响应开始前打开文件，批次清理不会中断在途流。
    stream = data_path.open('rb')
    def generate():
        try:
            for tile in ids:
                offset, length = entries[str(tile)]
                stream.seek(offset)
                yield struct.pack('<I', length) + stream.read(length)
        finally:
            stream.close()
    return generate(), sum(4+entries[str(i)][1] for i in ids)
