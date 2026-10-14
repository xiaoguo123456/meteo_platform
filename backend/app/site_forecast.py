"""站点目录和预测适配层。"""
from __future__ import annotations

import asyncio
import gzip
import json
import time
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from pydantic import BaseModel, Field

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
CATALOG_PATH = Path(__file__).with_name("site_catalog.json.gz")
_SATELLITE_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


class SiteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    type: str = Field(pattern="^(wind|solar)$")
    capacity_kw: float = Field(gt=0, le=10_000_000)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    province: str = Field(default="", max_length=32)
    city: str = Field(default="", max_length=32)


@lru_cache(maxsize=1)
def _catalog_rows() -> tuple[dict[str, Any], ...]:
    if not CATALOG_PATH.exists():
        return ()
    with gzip.open(CATALOG_PATH, "rt", encoding="utf-8") as handle:
        raw = json.load(handle)
    rows = []
    for item in raw:
        name = item.get("name_local") or item.get("name") or "未命名站点"
        rows.append({
            "id": item["id"], "name": name, "short_name": name[:18],
            "province": item.get("province") or "", "city": item.get("city") or "",
            "district": item.get("district") or "", "type": item["type"],
            "latitude": item["latitude"], "longitude": item["longitude"],
            "capacity_kw": item["capacity_kw"], "source": item.get("source"),
            "owner_name": item.get("owner_name"), "is_catalog": True,
        })
    return tuple(rows)


@lru_cache(maxsize=1)
def _custom_rows() -> tuple[dict[str, Any], ...]:
    path = get_settings().data_dir / "site_stations.json"
    if not path.exists():
        return ()
    try:
        return tuple(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return ()


def _all_stations() -> list[dict[str, Any]]:
    by_id = {row["id"]: dict(row) for row in _catalog_rows()}
    for row in STATIONS:
        by_id[row["id"]] = dict(row, is_featured=True)
    for row in _custom_rows():
        by_id[row["id"]] = dict(row, is_custom=True)
    return list(by_id.values())


def list_stations(keyword: str = "", type_: str | None = None, province: str = "", sort: str = "capacity", limit: int = 60, offset: int = 0) -> dict[str, Any]:
    all_rows = _all_stations()
    counts = {"all": len(all_rows), "solar": sum(row["type"] == "solar" for row in all_rows), "wind": sum(row["type"] == "wind" for row in all_rows)}
    query = keyword.strip().lower()
    filtered = [row for row in all_rows if (not type_ or row["type"] == type_) and (not province or row.get("province") == province) and (not query or query in " ".join(str(row.get(key, "")) for key in ("name", "short_name", "province", "city", "district")).lower())]
    if sort == "name":
        filtered.sort(key=lambda row: (row.get("name", ""), row["id"]))
    else:
        filtered.sort(key=lambda row: (-float(row.get("capacity_kw") or 0), row.get("name", "")))
    page = filtered[offset:offset + max(1, min(limit, 100))]
    return {"stations": page, "total": len(filtered), "has_more": offset + len(page) < len(filtered), "counts": counts, "regions": sorted({row.get("province") for row in all_rows if row.get("province")})}


def _station(station_id: str) -> dict[str, Any]:
    try:
        return next(item for item in _all_stations() if item["id"] == station_id)
    except StopIteration as exc:
        raise ValueError("站点不存在") from exc


def create_station(payload: SiteCreate) -> dict[str, Any]:
    row = payload.model_dump()
    row.update({"id": f"custom-{uuid4().hex[:12]}", "short_name": payload.name[:18], "is_custom": True})
    rows = [dict(item) for item in _custom_rows()]
    rows.append(row)
    path = get_settings().data_dir / "site_stations.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    _custom_rows.cache_clear()
    return row


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
    ratio = _clamp((wind - 3.0) / 9.0) if wind < 12 else 1.0
    if wind < 3 or wind >= 25:
        ratio = 0.0
    return round(station["capacity_kw"] * ratio, 1)


def _iso(value: str | None) -> str | None:
    return value.replace(" ", "T") + "+08:00" if value else None


def _satellite_latest(raw: dict[str, Any]) -> dict[str, Any]:
    block = raw.get("hourly") or {}
    times, ghi = block.get("time") or [], block.get("shortwave_radiation") or []
    direct, diffuse = block.get("direct_radiation") or [], block.get("diffuse_radiation") or []
    series, latest = [], None
    for i, value_time in enumerate(times):
        value = ghi[i] if i < len(ghi) else None
        item = {"time": value_time.replace(" ", "T") + "Z", "ghi_w_m2": value, "direct_w_m2": direct[i] if i < len(direct) else None, "diffuse_w_m2": diffuse[i] if i < len(diffuse) else None}
        if value is not None:
            series.append(item)
            latest = item
    if latest is None:
        return {"status": "unavailable", "source": "JAXA / P-Tree 葵花卫星", "series": series}
    return {"status": "ok", "source": "JAXA / P-Tree 葵花卫星", "observed_at": latest["time"], "ghi_w_m2": latest["ghi_w_m2"], "direct_w_m2": latest["direct_w_m2"], "diffuse_w_m2": latest["diffuse_w_m2"], "series": series}


async def forecast(station_id: str, model: str = "gfs", include_satellite: bool = False) -> dict[str, Any]:
    station, params, settings = _station(station_id), MODEL_PARAMS.get(model), get_settings()
    if not params:
        raise ValueError("不支持的预报模型")
    query = {"latitude": station["latitude"], "longitude": station["longitude"], "models": params["models"], "forecast_days": 7, "wind_speed_unit": "ms", "timezone": "Asia/Shanghai", "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m,cloud_cover,precipitation,shortwave_radiation", "hourly": "temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m,cloud_cover,precipitation,shortwave_radiation", "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max,sunrise,sunset"}
    satellite_base = None
    satellite_query = None
    if include_satellite and station["type"] == "solar":
        satellite_base = settings.open_meteo_satellite_base_url or settings.open_meteo_base_url.replace("/forecast", "/archive")
        now = datetime.now(timezone.utc)
        satellite_query = {"latitude": station["latitude"], "longitude": station["longitude"], "hourly": "shortwave_radiation,direct_radiation,diffuse_radiation", "temporal_resolution": "native", "models": settings.open_meteo_satellite_model, "timezone": "UTC", "start_date": (now - timedelta(days=1)).date().isoformat(), "end_date": now.date().isoformat()}
    async with httpx.AsyncClient(timeout=18) as client:
        response = await client.get(settings.open_meteo_base_url, params=query)
        satellite_response = await client.get(satellite_base, params=satellite_query) if satellite_base else None
    if response.status_code >= 400:
        raise RuntimeError(f"自部署 Open-Meteo 返回 {response.status_code}")
    hourly_raw, raw = response.json().get("hourly") or {}, response.json()
    arrays = {key: hourly_raw.get(key) or [] for key in ("wind_speed_10m", "wind_direction_10m", "cloud_cover", "shortwave_radiation", "temperature_2m", "relative_humidity_2m", "precipitation")}
    hourly = []
    for i, value_time in enumerate(hourly_raw.get("time") or []):
        wind = arrays["wind_speed_10m"][i] if i < len(arrays["wind_speed_10m"]) else None
        radiation = arrays["shortwave_radiation"][i] if i < len(arrays["shortwave_radiation"]) else None
        cloud = arrays["cloud_cover"][i] if i < len(arrays["cloud_cover"]) else None
        hourly.append({"time": _iso(value_time), "temperature": arrays["temperature_2m"][i] if i < len(arrays["temperature_2m"]) else None, "humidity": arrays["relative_humidity_2m"][i] if i < len(arrays["relative_humidity_2m"]) else None, "wind_speed": wind, "wind_direction": arrays["wind_direction_10m"][i] if i < len(arrays["wind_direction_10m"]) else None, "cloud_cover": cloud, "precipitation": arrays["precipitation"][i] if i < len(arrays["precipitation"]) else None, "radiation": radiation, "power_kw": _power(station, wind, radiation, cloud)})
    daily_raw, days = raw.get("daily") or {}, []
    for i, day in enumerate(daily_raw.get("time") or []):
        chunk, powers = hourly[i * 24:i * 24 + 24], []
        powers = [row["power_kw"] for row in chunk if row["power_kw"] is not None]
        def daily(key: str):
            values = daily_raw.get(key) or []
            return values[i] if i < len(values) else None
        days.append({"date": day, "temperature_max": daily("temperature_2m_max"), "temperature_min": daily("temperature_2m_min"), "precipitation": daily("precipitation_sum"), "wind_speed_max": daily("wind_speed_10m_max"), "sunrise": _iso(daily("sunrise")), "sunset": _iso(daily("sunset")), "power_peak_kw": round(max(powers), 1) if powers else None, "energy_kwh": round(sum(powers), 1) if powers else None})
    current, satellite_raw = raw.get("current") or {}, satellite_response.json() if satellite_response and satellite_response.is_success else None
    return {"station": station, "model": model, "model_name": params["name"], "source": "Open-Meteo 自部署服务", "timezone": raw.get("timezone", "Asia/Shanghai"), "updated_at": datetime.now(timezone.utc).isoformat(), "current": {"time": _iso(current.get("time")), "temperature": current.get("temperature_2m"), "humidity": current.get("relative_humidity_2m"), "wind_speed": current.get("wind_speed_10m"), "wind_direction": current.get("wind_direction_10m"), "cloud_cover": current.get("cloud_cover"), "precipitation": current.get("precipitation"), "radiation": current.get("shortwave_radiation"), "power_kw": _power(station, current.get("wind_speed_10m"), current.get("shortwave_radiation"), current.get("cloud_cover"))}, "satellite": _satellite_latest(satellite_raw) if satellite_raw else {"status": "unavailable", "source": "JAXA / P-Tree 葵花卫星", "series": []}, "hourly": hourly, "days": days}


async def satellite_radiation(station_id: str) -> dict[str, Any]:
    station = _station(station_id)
    if station["type"] != "solar":
        return {"status": "not_applicable", "source": "JAXA / P-Tree 葵花卫星", "series": []}
    cached = _SATELLITE_CACHE.get(station_id)
    if cached and time.monotonic() - cached[0] < 300:
        return cached[1]
    settings = get_settings()
    base = settings.open_meteo_satellite_base_url or settings.open_meteo_base_url.replace("/forecast", "/archive")
    now = datetime.now(timezone.utc)
    query = {"latitude": station["latitude"], "longitude": station["longitude"], "hourly": "shortwave_radiation,direct_radiation,diffuse_radiation", "temporal_resolution": "native", "models": settings.open_meteo_satellite_model, "timezone": "UTC", "start_date": (now - timedelta(days=1)).date().isoformat(), "end_date": now.date().isoformat()}
    async with httpx.AsyncClient(timeout=18) as client:
        response = await client.get(base, params=query)
    if response.status_code >= 400:
        raise RuntimeError(f"自部署 Open-Meteo 卫星接口返回 {response.status_code}")
    result = _satellite_latest(response.json())
    _SATELLITE_CACHE[station_id] = (time.monotonic(), result)
    return result
