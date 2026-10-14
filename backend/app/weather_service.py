"""天气场读取、缓存和前端渲染采样。

模型源数据按 0.25°（GRAPES 为 0.125°）处理，浏览器只接收固定数量的
粒子时间序列。这样保留模型精度，又不会把全球约百万个网格点直接塞进页面。
"""

from __future__ import annotations

import asyncio
import math
import os
import time
from datetime import datetime, timezone
from typing import Any

import httpx


class WeatherDataError(RuntimeError):
    """天气源不可用或返回数据不完整。"""


MODEL_SOURCES: dict[str, dict[str, Any]] = {
    "gfs": {"url": "https://api.open-meteo.com/v1/gfs", "params": {}, "label": "GFS", "native_resolution": 0.25},
    "ifs": {"url": "https://api.open-meteo.com/v1/ecmwf", "params": {"models": "ecmwf_ifs025"}, "label": "IFS", "native_resolution": 0.25},
    "aifs": {"url": "https://api.open-meteo.com/v1/ecmwf", "params": {"models": "ecmwf_aifs025_single"}, "label": "AIFS", "native_resolution": 0.25},
    "grapes": {"url": "https://api.open-meteo.com/v1/cma", "params": {}, "label": "GRAPES", "native_resolution": 0.125},
}

# S3 原始源保持 0.25°/0.125°；粒子预算只影响浏览器渲染数量。
RENDER_GRID_STEP = 5.0
FORECAST_HOURS = 48
CACHE_TTL_SECONDS = 900
MAX_PARTICLES = 6000
HOURLY_VARIABLES = "temperature_2m,wind_speed_10m,wind_direction_10m,pressure_msl,precipitation,cloud_cover"

_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_cache_lock = asyncio.Lock()


def build_grid(step: float = RENDER_GRID_STEP) -> tuple[list[float], list[float]]:
    latitudes = [round(-80 + index * step, 4) for index in range(int(160 / step) + 1)]
    longitudes = [round(-180 + index * step, 4) for index in range(int(360 / step))]
    return latitudes, longitudes


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _base_metadata(model_id: str, source: str, source_error: str | None = None) -> dict[str, Any]:
    return {
        "model": model_id,
        "model_name": MODEL_SOURCES.get(model_id, {}).get("label", model_id.upper()),
        "source": source,
        "source_error": source_error,
        "native_resolution": MODEL_SOURCES.get(model_id, {}).get("native_resolution", 0.25),
        "render_resolution": RENDER_GRID_STEP,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "units": {"speed": "m/s", "temperature": "°C", "pressure": "hPa", "precipitation": "mm", "cloud": "%"},
    }


def _build_request(model_id: str, hours: int) -> tuple[str, dict[str, Any]]:
    source = MODEL_SOURCES[model_id]
    latitudes, longitudes = build_grid()
    params: dict[str, Any] = {
        "latitude": ",".join(str(value) for value in latitudes for _ in longitudes),
        "longitude": ",".join(str(value) for _ in latitudes for value in longitudes),
        "hourly": HOURLY_VARIABLES,
        "forecast_hours": max(12, min(hours, FORECAST_HOURS)),
        "wind_speed_unit": "ms",
        "temperature_unit": "celsius",
        "precipitation_unit": "mm",
        "timeformat": "iso8601",
        "timezone": "UTC",
    }
    params.update(source["params"])
    return source["url"], params


def _parse_response(model_id: str, payload: Any, requested_hours: int) -> dict[str, Any]:
    items = payload if isinstance(payload, list) else [payload]
    if not items or not isinstance(items[0], dict) or "hourly" not in items[0]:
        raise ValueError("Open-Meteo 返回格式不完整")
    latitudes, longitudes = build_grid()
    point_count = len(latitudes) * len(longitudes)
    if len(items) != point_count:
        raise ValueError(f"返回网格数量异常：期望 {point_count}，实际 {len(items)}")
    first_hourly = items[0]["hourly"]
    times = list(first_hourly.get("time", []))[:requested_hours]
    if not times:
        raise ValueError("Open-Meteo 未返回时间轴")

    names = {"temperature": "temperature_2m", "speed": "wind_speed_10m", "direction": "wind_direction_10m", "pressure": "pressure_msl", "precipitation": "precipitation", "cloud": "cloud_cover"}
    fields: dict[str, list[float]] = {name: [] for name in ("u", "v", "speed", "temperature", "pressure", "precipitation", "cloud")}
    for time_index in range(len(times)):
        for item in items:
            hourly = item.get("hourly", {})
            speed = _float(hourly.get(names["speed"], [0.0] * len(times))[time_index])
            direction = _float(hourly.get(names["direction"], [0.0] * len(times))[time_index])
            direction_radians = math.radians(direction)
            fields["u"].append(-speed * math.sin(direction_radians))
            fields["v"].append(-speed * math.cos(direction_radians))
            fields["speed"].append(speed)
            fields["temperature"].append(_float(hourly.get(names["temperature"], [0.0] * len(times))[time_index]))
            fields["pressure"].append(_float(hourly.get(names["pressure"], [0.0] * len(times))[time_index]))
            fields["precipitation"].append(_float(hourly.get(names["precipitation"], [0.0] * len(times))[time_index]))
            fields["cloud"].append(_float(hourly.get(names["cloud"], [0.0] * len(times))[time_index]))

    data = _base_metadata(model_id, "open-meteo")
    data.update({"grid": {"latitudes": latitudes, "longitudes": longitudes}, "times": times, "fields": fields})
    return data


async def get_weather_grid(model_id: str, hours: int = FORECAST_HOURS, force_refresh: bool = False) -> dict[str, Any]:
    if model_id not in MODEL_SOURCES:
        raise ValueError(f"不支持的模型：{model_id}")
    if os.getenv("WEATHER_SPATIAL_SOURCE", "s3").lower() != "api":
        raise WeatherDataError("当前使用严格 S3 模式，请调用粒子接口读取 Open-Meteo S3 空间文件")
    requested_hours = min(max(hours, 12), FORECAST_HOURS)
    cache_key = f"{model_id}:{requested_hours}"
    cached = _cache.get(cache_key)
    if cached and not force_refresh and time.monotonic() - cached[0] < CACHE_TTL_SECONDS:
        return {**cached[1], "cached": True}
    async with _cache_lock:
        cached = _cache.get(cache_key)
        if cached and not force_refresh and time.monotonic() - cached[0] < CACHE_TTL_SECONDS:
            return {**cached[1], "cached": True}
        url, params = _build_request(model_id, requested_hours)
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, params=params, timeout=45.0)
                response.raise_for_status()
                data = _parse_response(model_id, response.json(), requested_hours)
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as error:
            raise WeatherDataError(f"Open-Meteo API 数据读取失败：{error}") from error
        _cache[cache_key] = (time.monotonic(), data)
        return {**data, "cached": False}


def _sample_indices(point_count: int, max_points: int) -> list[int]:
    target = min(max(64, max_points), MAX_PARTICLES)
    if point_count <= target:
        return list(range(point_count))
    stride = math.ceil(point_count / target)
    return list(range(0, point_count, stride))[:target]


def _grid_to_particles(grid: dict[str, Any], max_points: int) -> dict[str, Any]:
    latitudes = grid["grid"]["latitudes"]
    longitudes = grid["grid"]["longitudes"]
    point_count = len(latitudes) * len(longitudes)
    selected = _sample_indices(point_count, max_points)
    names = ("u", "v", "speed", "temperature", "pressure", "precipitation", "cloud")
    points: list[dict[str, Any]] = []
    for index in selected:
        lat_index, lng_index = divmod(index, len(longitudes))
        point = {"lat": latitudes[lat_index], "lng": longitudes[lng_index]}
        for name in names:
            values = grid["fields"][name]
            point[name] = [values[time_index * point_count + index] for time_index in range(len(grid["times"]))]
        points.append(point)
    return {
        "model": grid["model"],
        "model_name": grid["model_name"],
        "source": grid["source"],
        "source_error": grid.get("source_error"),
        "native_resolution": grid["native_resolution"],
        "render_resolution": grid["render_resolution"],
        "generated_at": grid["generated_at"],
        "times": grid["times"],
        "units": grid["units"],
        "particle_count": len(points),
        "source_point_count": point_count,
        "sampling": "server-side-stride",
        "points": points,
    }


def _native_to_particles(native: dict[str, Any], model_id: str, max_points: int) -> dict[str, Any]:
    """把 S3 原生网格按固定预算采样成一帧粒子。"""

    import numpy as np

    latitudes = native["latitudes"]
    longitudes = native["longitudes"]
    height, width = native["arrays"]["u"].shape
    selected = _sample_indices(height * width, max_points)
    points: list[dict[str, Any]] = []
    for index in selected:
        lat_index, lng_index = divmod(index, width)
        u = float(native["arrays"]["u"][lat_index, lng_index])
        v = float(native["arrays"]["v"][lat_index, lng_index])
        point: dict[str, Any] = {
            "lat": float(latitudes[lat_index]),
            "lng": float(longitudes[lng_index]),
            "u": [u],
            "v": [v],
            "speed": [float(np.hypot(u, v))],
        }
        for name in ("temperature", "pressure", "precipitation", "cloud"):
            array = native["arrays"].get(name)
            point[name] = [float(array[lat_index, lng_index])] if array is not None else [0.0]
        points.append(point)
    now = native["valid_time"]
    return {
        "model": model_id,
        "model_name": MODEL_SOURCES[model_id]["label"],
        "source": "open-meteo-s3",
        "source_error": None,
        "native_resolution": native["native_resolution"],
        "render_resolution": native["native_resolution"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "times": [now],
        "units": {"speed": "m/s", "temperature": "°C", "pressure": "hPa", "precipitation": "mm", "cloud": "%"},
        "particle_count": len(points),
        "source_point_count": height * width,
        "sampling": "server-side-stride",
        "missing_variables": native.get("missing_variables", []),
        "points": points,
    }


async def get_weather_particles(model_id: str, hours: int = FORECAST_HOURS, max_points: int = MAX_PARTICLES, force_refresh: bool = False) -> dict[str, Any]:
    if model_id not in MODEL_SOURCES:
        raise ValueError(f"不支持的模型：{model_id}")
    if os.getenv("WEATHER_SPATIAL_SOURCE", "s3").lower() == "api":
        grid = await get_weather_grid(model_id, hours=hours, force_refresh=force_refresh)
        return _grid_to_particles(grid, max_points)
    from .spatial_provider import read_native_snapshot

    native = await asyncio.to_thread(read_native_snapshot, model_id)
    return _native_to_particles(native, model_id, max_points)
