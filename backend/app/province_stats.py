"""省级面积加权统计：随预取逐帧算好，接口只读取本地小文件。"""
import json
import math
from functools import lru_cache
from pathlib import Path
import numpy as np
from .spatial_provider import MODEL_GRIDS, SpatialDataError, model_fields

REGIONS_PATH = Path(__file__).parent/'data/province_regions.json'
# 每个格点 4×4 子采样估算落在省内的面积比例，边界格点按比例计入。
SUBSAMPLE = 4


@lru_cache(maxsize=1)
def regions():
    features = json.loads(REGIONS_PATH.read_text())['features']
    result = {}
    for f in features:
        rings = [np.asarray(r, dtype=np.float64) for polygon in f['geometry']['coordinates'] for r in polygon]
        points = np.vstack(rings)
        result[f['properties']['code']] = dict(
            name=f['properties']['name'], geometry=f['geometry'], centre=points.mean(axis=0),
            bbox=(points[:, 0].min(), points[:, 1].min(), points[:, 0].max(), points[:, 1].max()),
            edges=(np.vstack([r[:-1] for r in rings]), np.vstack([r[1:] for r in rings])))
    return result


def province_list():
    return [{'code': code, 'name': item['name']} for code, item in regions().items()]


def _inside(edges, xs, y):
    # 偶奇规则：外环与洞统一计数，奇数次穿越即在省内。
    a, b = edges
    crossing = (a[:, 1] > y) != (b[:, 1] > y)
    if not crossing.any():
        return np.zeros(len(xs), bool)
    xa, ya, xb, yb = a[crossing, 0], a[crossing, 1], b[crossing, 0], b[crossing, 1]
    cuts = np.sort(xa + (y - ya) * (xb - xa) / (yb - ya))
    return np.searchsorted(cuts, xs) % 2 == 1


def locate(longitude, latitude):
    """返回经纬度所在省份；不在中国省级行政区内返回 None。"""
    for code, item in regions().items():
        west, south, east, north = item['bbox']
        if not (west <= longitude <= east and south <= latitude <= north):
            continue
        if _inside(item['edges'], np.array([longitude]), latitude)[0]:
            return {'code': code, 'name': item['name']}
    return None


@lru_cache(maxsize=len(MODEL_GRIDS))
def weights(model):
    """每省的扁平格点索引与权重：覆盖比例 × cos(纬度)，与经纬网格单元面积成正比。"""
    grid = MODEL_GRIDS[model]
    dx, dy, step = grid['dx'], grid['dy'], grid['dx']/SUBSAMPLE
    result = {}
    for code, item in regions().items():
        west, south, east, north = item['bbox']
        c0, c1 = math.floor((west-grid['lon0'])/dx+0.5), math.ceil((east-grid['lon0'])/dx-0.5)
        r0, r1 = max(0, math.floor((south-grid['lat0'])/dy+0.5)), min(grid['height']-1, math.ceil((north-grid['lat0'])/dy-0.5))
        cols, rows = np.arange(c0, c1+1), np.arange(r0, r1+1)
        offsets = (np.arange(SUBSAMPLE)+0.5)*step - dx/2
        xs = (grid['lon0']+cols[:, None]*dx+offsets[None, :]).reshape(-1)
        share = np.zeros((len(rows), len(cols)))
        for i, row in enumerate(rows):
            for offset in offsets:
                share[i] += _inside(item['edges'], xs, grid['lat0']+row*dy+offset).reshape(len(cols), SUBSAMPLE).sum(axis=1)
        share /= SUBSAMPLE*SUBSAMPLE
        rr, cc = np.nonzero(share)
        nearest = not len(rr)
        if nearest:
            # 面积小于一个格点（如澳门）时取离省域中心最近的格点。
            longitude, latitude = item['centre']
            row_index = np.array([min(grid['height']-1, max(0, round((latitude-grid['lat0'])/dy)))])
            col_index = np.array([round((longitude-grid['lon0'])/dx)])
            fraction = np.ones(1)
        else:
            row_index, col_index, fraction = rows[rr], cols[cc], share[rr, cc]
        latitudes = grid['lat0']+row_index*dy
        index = (row_index*grid['width'] + col_index % grid['width']).astype(np.int64)
        result[code] = dict(index=index, weight=fraction*np.cos(np.radians(latitudes)), cells=len(index), nearest=nearest)
    return result


def frame_stats(model, arrays):
    """单个预报时刻各省统计：[平均, 最低, 最高]，风另附平均矢量用于风向。"""
    output = {}
    flat = {name: np.asarray(array, dtype=np.float64).reshape(-1) for name, array in arrays.items()}
    if 'u' in flat and 'v' in flat:
        flat['wind'] = np.hypot(flat['u'], flat['v'])
    for code, item in weights(model).items():
        stats = {}
        for field in model_fields(model):
            if field not in flat:
                continue
            values = flat[field][item['index']]
            valid = np.isfinite(values)
            if not valid.any():
                continue
            w = item['weight'][valid]
            entry = [float(np.average(values[valid], weights=w)), float(values[valid].min()), float(values[valid].max())]
            if field == 'wind':
                u, v = flat['u'][item['index']][valid], flat['v'][item['index']][valid]
                entry += [float(np.average(u, weights=w)), float(np.average(v, weights=w))]
            stats[field] = [round(value, 3) for value in entry]
        output[code] = stats
    return output


def write_frame_stats(folder, index, model, arrays):
    path = folder/f'{index}.provinces.json'
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(frame_stats(model, arrays), separators=(',', ':')))
    temporary.replace(path)


@lru_cache(maxsize=48)
def _series(root, model, key, field, indices):
    # 只保留单一要素的紧凑数组（帧 × 省 × 统计量），缺测为 NaN，避免缓存整帧字典占用内存。
    folder = Path(root)/model/key
    codes = list(regions())
    width = 5 if field == 'wind' else 3
    values = np.full((len(indices), len(codes), width), np.nan, dtype=np.float32)
    for i, index in enumerate(indices):
        frame = json.loads((folder/f'{index}.provinces.json').read_text())
        for j, code in enumerate(codes):
            entry = frame.get(code, {}).get(field)
            if entry:
                values[i, j] = entry
    return {code: j for j, code in enumerate(codes)}, values


def province_forecast(model, field, code, run=None):
    from .forecast_cache import ROOT, read_run_status
    from .wind_grid import field_spec
    if model not in MODEL_GRIDS or field not in model_fields(model):
        raise ValueError('模型或气象要素无效')
    if code not in regions():
        raise ValueError('省份代码无效')
    status = read_run_status(model, run)
    times = tuple(status.get('field_times', {}).get(field, []))
    if not times:
        raise SpatialDataError('当前模型没有该要素的已缓存预报')
    indices = tuple(status['expected_times'].index(t) for t in times)
    folder = ROOT/model/status['key']
    ready = sum((folder/f'{i}.provinces.json').exists() for i in indices)
    if ready < len(indices):
        raise SpatialDataError(f'省平均正在后台计算（{ready}/{len(indices)}），请稍后重试')
    columns, values = _series(str(ROOT), model, status['key'], field, indices)
    points = []
    for valid, entry in zip(times, values[:, columns[code]].tolist()):
        point = {'time': valid, 'mean': None, 'min': None, 'max': None}
        if math.isfinite(entry[0]):
            point.update(mean=round(entry[0], 3), min=round(entry[1], 3), max=round(entry[2], 3))
            if field == 'wind':
                direction = (math.degrees(math.atan2(-entry[3], -entry[4]))+360) % 360
                point['direction'] = round(direction, 1) if math.hypot(entry[3], entry[4]) > 0 else None
        points.append(point)
    item = weights(model)[code]
    unit, level = field_spec(model, field)
    return dict(model=model, field=field, run_time=status['run_time'], code=code, name=regions()[code]['name'],
                level=level, unit=unit, cells=item['cells'], nearest=item['nearest'],
                resolution=MODEL_GRIDS[model]['dx'], points=points)
