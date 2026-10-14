"""站点预测的轻量适配层：把自部署 Open-Meteo 响应整理成网站需要的口径。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from .config import get_settings


STATIONS: list[dict[str, Any]] = [
    {"id": "zhangbei-wind", "name": "张北风电示范站", "short_name": "张北风电", "province": "河北省", "city": "张家口", "type": "wind", "latitude": 41.16, "longitude": 114.70, "capacity_kw": 180000},
    {"id": "jiuquan-wind", "name": "酒泉新能源基地", "short_name": "酒泉风电", "province": "甘肃省", "city": "酒泉", "type": "wind", "latitude": 39.74, "longitude": 98.52, "capacity_kw": 240000},
    {"id": "xilingol-wind", "name": "锡林郭勒风电场", "short_name": "锡盟风电", "province": "内蒙古自治区", "city": "锡林浩特", "type": "wind", "latitude": 44.00, "longitude": 116.06, "capacity_kw": 210000},
    {"id": "ningxia-solar", "name": "宁夏沙漠光伏基地", "short_name": "宁夏光伏", "province": "宁夏回族自治区", "city": "中卫", "type": "solar", "latitude": 37.50, "longitude": 105.19, "capacity_kw": 300000},
    {"id": "qingtongxia-solar", "name": "青铜峡光伏站", "short_name": "青铜峡光伏", "province": "宁夏回族自治区", "city": "吴忠", "type": "solar", "latitude": 37.98, "longitude": 105.98, "capacity_kw": 120000},
    {"id": "tongzhou-solar", "name": "通州分布式光伏站", "short_name": "通州光伏", "province": "江苏省", "city": "南通", "type": "solar", "latitude": 31.98, "longitude": 121.09, "capacity_kw": 85000},
]

MODEL_PARAMS = {
    "gfs": {"name": "GFS", "models": "gfs_global"},
    "ifs": {"name": "IFS", "models": "ecmwf_ifs025"},
    "aifs": {"name": "AIFS", "models": "ecmwf_aifs025"},
    "grapes": {"name": "GRAPES", "models": "cma_grapes_global"},
}


def list_stations() -> list[dict[str, Any]]:
    return STATIONS


def _station(station_id: str) -> dict[str, Any]:
    try:
        return next(item for item in STATIONS if item["id"] == station_id)
    except StopIteration as exc:
        raise ValueError("站点不存在") from exc


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _power(station: dict[str, Any], wind: float | None, radiation: float | None, cloud: float | None) -> float | None:
    if station["type"] == "solar":
        if radiation is None:
            return None
        cloud_factor = 1.0 - 0.25 * _clamp((cloud or 0) / 100.0)
        return round(station["capacity_kw"] * _clamp(radiation / 850.0) * cloud_factor, 1)
    if wind is None:
        return None
    # 用于展示站点功率趋势的平滑通用风机曲线，实际业务可替换成场站曲线。
    ratio = _clamp((wind - 3.0) / 9.0) if wind < 12 else 1.0
    if wind < 3 or wind >= 25:
        ratio = 0.0 if wind < 3 or wind >= 25 else ratio
    return round(station["capacity_kw"] * ratio, 1)


def _iso(value: str | None) -> str | None:
    return value.replace(" ", "T") if value else None


async def forecast(station_id: str, model: str = "gfs") -> dict[str, Any]:
    station = _station(station_id)
    params = MODEL_PARAMS.get(model)
    if not params:
        raise ValueError("不支持的预报模型")
    settings = get_settings()
    query = {
        "latitude": station["latitude"],
        "longitude": station["longitude"],
        "models": params["models"],
        "forecast_days": 7,
        "timezone": "Asia/Shanghai",
        "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m,cloud_cover,precipitation,shortwave_radiation",
        "hourly": "temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m,cloud_cover,precipitation,shortwave_radiation",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max,sunrise,sunset",
    }
    async with httpx.AsyncClient(timeout=18) as client:
        response = await client.get(settings.open_meteo_base_url, params=query)
    if response.status_code >= 400:
        raise RuntimeError(f"自部署 Open-Meteo 返回 {response.status_code}")
    raw = response.json()
    hourly_raw = raw.get("hourly") or {}
    times = hourly_raw.get("time") or []
    wind = hourly_raw.get("wind_speed_10m") or []
    direction = hourly_raw.get("wind_direction_10m") or []
    cloud = hourly_raw.get("cloud_cover") or []
    radiation = hourly_raw.get("shortwave_radiation") or []
    temperature = hourly_raw.get("temperature_2m") or []
    humidity = hourly_raw.get("relative_humidity_2m") or []
    precipitation = hourly_raw.get("precipitation") or []
    hourly = []
    for i, value_time in enumerate(times):
        item_wind = wind[i] if i < len(wind) else None
        item_radiation = radiation[i] if i < len(radiation) else None
        item_cloud = cloud[i] if i < len(cloud) else None
        hourly.append({
            "time": _iso(value_time),
            "temperature": temperature[i] if i < len(temperature) else None,
            "humidity": humidity[i] if i < len(humidity) else None,
            "wind_speed": item_wind,
            "wind_direction": direction[i] if i < len(direction) else None,
            "cloud_cover": item_cloud,
            "precipitation": precipitation[i] if i < len(precipitation) else None,
            "radiation": item_radiation,
            "power_kw": _power(station, item_wind, item_radiation, item_cloud),
        })
    daily_raw = raw.get("daily") or {}
    days = []
    for i, day in enumerate(daily_raw.get("time") or []):
        start = i * 24
        chunk = hourly[start:start + 24]
        powers = [x["power_kw"] for x in chunk if x["power_kw"] is not None]
        days.append({
            "date": day,
            "temperature_max": (daily_raw.get("temperature_2m_max") or [None] * (i + 1))[i],
            "temperature_min": (daily_raw.get("temperature_2m_min") or [None] * (i + 1))[i],
            "precipitation": (daily_raw.get("precipitation_sum") or [None] * (i + 1))[i],
            "wind_speed_max": (daily_raw.get("wind_speed_10m_max") or [None] * (i + 1))[i],
            "sunrise": _iso((daily_raw.get("sunrise") or [None] * (i + 1))[i]),
            "sunset": _iso((daily_raw.get("sunset") or [None] * (i + 1))[i]),
            "power_peak_kw": round(max(powers), 1) if powers else None,
            "energy_kwh": round(sum(powers), 1) if powers else None,
        })
    current = raw.get("current") or {}
    return {
        "station": station,
        "model": model,
        "model_name": params["name"],
        "source": "Open-Meteo 自部署服务",
        "timezone": raw.get("timezone", "Asia/Shanghai"),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "current": {
            "time": _iso(current.get("time")),
            "temperature": current.get("temperature_2m"),
            "humidity": current.get("relative_humidity_2m"),
            "wind_speed": current.get("wind_speed_10m"),
            "wind_direction": current.get("wind_direction_10m"),
            "cloud_cover": current.get("cloud_cover"),
            "precipitation": current.get("precipitation"),
            "radiation": current.get("shortwave_radiation"),
            "power_kw": _power(station, current.get("wind_speed_10m"), current.get("shortwave_radiation"), current.get("cloud_cover")),
        },
        "hourly": hourly[:72],
        "days": days,
    }
