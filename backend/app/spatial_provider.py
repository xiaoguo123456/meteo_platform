"""Open-Meteo S3 空间文件读取器。

该模块是正式数据路径。依赖或上游不可用时抛出明确错误，不生成替代天气场。
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

MODEL_SPATIAL_NAMES = {
    "gfs": "ncep_gfs025",
    "ifs": "ecmwf_ifs025",
    "aifs": "ecmwf_aifs025_single",
    "grapes": "cma_grapes_global",
}


# 与 Open-Meteo 各 Domain 的 RegularGrid 一致，GRAPES 纬度为格心。
MODEL_GRIDS = {
    model: dict(width=1440, height=721, lon0=-180, lat0=-90, dx=0.25, dy=0.25)
    for model in ("gfs", "ifs", "aifs")
}
MODEL_GRIDS["grapes"] = dict(width=2880, height=1440, lon0=-180, lat0=-89.9375, dx=0.125, dy=0.125)


class SpatialDataError(RuntimeError):
    """S3 空间数据无法读取。"""

MODEL_VARIABLE_NAMES = {
    "gfs": {
        "u": "wind_u_component_80m",
        "v": "wind_v_component_80m",
        "temperature": "temperature_1000hPa",
        "humidity": "relative_humidity_1000hPa",
        "pressure": "pressure_msl",
        "precipitation": None,
        "cloud": "cloud_cover_1000hPa",
    },
    "ifs": {
        "u": "wind_u_component_10m",
        "v": "wind_v_component_10m",
        "temperature": "temperature_2m",
        "humidity": "relative_humidity_2m",
        "pressure": "pressure_msl",
        "precipitation": "precipitation",
        "cloud": "cloud_cover",
    },
    "aifs": {
        "u": "wind_u_component_10m",
        "v": "wind_v_component_10m",
        "temperature": "temperature_2m",
        "humidity": "relative_humidity_2m",
        "pressure": "pressure_msl",
        "precipitation": "precipitation",
        "cloud": "cloud_cover",
    },
    "grapes": {
        "u": "wind_u_component_10m",
        "v": "wind_v_component_10m",
        "temperature": "temperature_2m",
        "humidity": "relative_humidity_2m",
        "pressure": "pressure_msl",
        "precipitation": "precipitation",
        "cloud": "cloud_cover",
    },
}


def latest_manifest(model_id: str) -> dict:
    import httpx
    if model_id not in MODEL_SPATIAL_NAMES:
        raise SpatialDataError('不支持的模型')
    try:
        response = httpx.get(f"https://openmeteo.s3.amazonaws.com/data_spatial/{MODEL_SPATIAL_NAMES[model_id]}/latest.json", timeout=20)
        response.raise_for_status()
        payload = response.json()
        datetime.fromisoformat(payload['reference_time'].replace('Z', '+00:00'))
        if not payload['valid_times'] or not isinstance(payload['variables'], list):
            raise ValueError('无有效预报时刻')
        for t in payload['valid_times']:
            datetime.fromisoformat(t.replace('Z', '+00:00'))
        return payload
    except Exception as error:
        raise SpatialDataError(f'S3 起报清单读取失败：{error}') from error


def snapshot_uri(model_id, manifest, valid_time):
    if valid_time not in manifest['valid_times']:
        raise SpatialDataError('预报时刻不属于该起报批次')
    reference = datetime.fromisoformat(manifest['reference_time'].replace('Z', '+00:00'))
    valid = datetime.fromisoformat(valid_time.replace('Z', '+00:00'))
    return (f"s3://openmeteo/data_spatial/{MODEL_SPATIAL_NAMES[model_id]}/{reference:%Y/%m/%d}/"
            f"{reference:%H%M}Z/{valid:%Y-%m-%dT%H%M}.om")


def _latest_uri(model_id):
    manifest = latest_manifest(model_id)
    valid = manifest['valid_times'][0]
    return snapshot_uri(model_id, manifest, valid), valid, set(manifest['variables'])


def _read_array(root: Any, name: str) -> Any:
    child = root.get_child_by_name(name)
    ranges = tuple(slice(None) for _ in child.shape)
    return child.read_array(ranges)


def read_native_snapshot(model_id: str, manifest=None, selected_time=None, cache_dir_override=None) -> dict[str, Any]:
    """读取最新一帧原生网格，并转成 numpy 数组。

    OM 文件和依赖都在运行时检查，读取失败会向 API 层抛出错误。
    """

    if model_id not in MODEL_SPATIAL_NAMES:
        raise SpatialDataError(f"不支持的 S3 模型：{model_id}")
    try:
        import fsspec
        import numpy as np
        from omfiles import OmFileReader

        manifest = manifest or latest_manifest(model_id)
        valid_time = selected_time or manifest['valid_times'][0]
        available_variables = set(manifest['variables'])
        uri = snapshot_uri(model_id, manifest, valid_time)
        cache_dir = Path(cache_dir_override or os.getenv("WEATHER_BLOCK_CACHE", "data/cache/omfiles"))
        cache_dir.mkdir(parents=True, exist_ok=True)
        backend = fsspec.open(
            f"blockcache::{uri}",
            mode="rb",
            skip_instance_cache=True,
            s3={"anon": True, "default_block_size": int(os.getenv("WEATHER_S3_BLOCK_SIZE", "262144"))},
            blockcache={"cache_storage": str(cache_dir), "check_files": False},
        )
        variable_names = MODEL_VARIABLE_NAMES[model_id]
        missing_required = [key for key in ("u", "v") if variable_names[key] not in available_variables]
        if missing_required:
            raise SpatialDataError(f"S3 元数据缺少 {model_id} 的必需变量：{', '.join(missing_required)}")
        with OmFileReader(backend) as root:
            children = {root.get_child_by_index(i).name for i in range(root.num_children)}
            arrays = {
                key: np.asarray(_read_array(root, name), dtype=np.float32)
                for key, name in variable_names.items()
                if name and name in available_variables and name in children
            }
        if "u" not in arrays or "v" not in arrays:
            raise SpatialDataError("当前 S3 文件缺少必需风分量")
        first = arrays["u"]
        if first.ndim != 2 or arrays["v"].shape != first.shape:
            raise SpatialDataError("OM 文件中的风场数组形状不一致")
        height, width = first.shape
        grid = MODEL_GRIDS[model_id]
        if (height, width) != (grid["height"], grid["width"]) or any(a.shape != first.shape for a in arrays.values()):
            raise SpatialDataError("S3 网格与模型定义不一致")
        return {
            "arrays": arrays,
            "latitudes": grid["lat0"] + np.arange(height, dtype=np.float32) * grid["dy"],
            "longitudes": np.linspace(-180, 180, width, endpoint=False, dtype=np.float32),
            "valid_time": valid_time,
            "run_time": manifest["reference_time"],
            "native_resolution": 360 / width,
            "missing_variables": [key for key, name in variable_names.items() if not name or name not in available_variables],
        }
    except SpatialDataError:
        raise
    except (ImportError, OSError, KeyError, TypeError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        raise SpatialDataError(f"无法读取 Open-Meteo S3 OM 文件：{error}") from error
    except Exception as error:
        raise SpatialDataError(f"读取 Open-Meteo S3 时发生未知错误：{error}") from error
