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
_POWER_OUTLOOK_CACHE: dict[tuple[int, int], tuple[float, dict[str, Any]]] = {}


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
    _POWER_OUTLOOK_CACHE.clear()
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


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _ensemble(values: list[float], capacity_kw: float) -> tuple[float, float, float, int]:
    """把四个模型的功率结果压成区间、中心值和一致性分数。"""
    if not values:
        raise ValueError("无法计算空的功率集合")
    ordered = sorted(values)
    low, high, center = ordered[0], ordered[-1], _median(ordered)
    spread = (high - low) / max(capacity_kw, 1.0)
    confidence = int(round(max(38.0, min(99.0, 98.0 - spread * 180.0))))
    return round(low, 1), round(center, 1), round(high, 1), confidence


def _outlook_stations(limit: int) -> list[dict[str, Any]]:
    """态势页默认展示精选和自定义站点，避免首次打开就请求整个编目。"""
    rows = _all_stations()
    selected = [row for row in rows if row.get("is_featured") or row.get("is_custom")]
    selected.sort(key=lambda row: (-float(row.get("capacity_kw") or 0), row.get("name", "")))
    return selected[:limit]


async def power_outlook(hours: int = 24, limit: int = 12) -> dict[str, Any]:
    """汇总精选新能源站点，供新能源态势模块绘制区域功率和爬坡预警。"""
    hours = max(6, min(hours, 48))
    limit = max(1, min(limit, 24))
    cache_key = (hours, limit)
    cached = _POWER_OUTLOOK_CACHE.get(cache_key)
    if cached and time.monotonic() - cached[0] < 300:
        return cached[1]

    stations = _outlook_stations(limit)
    model_ids = tuple(MODEL_PARAMS)
    semaphore = asyncio.Semaphore(6)

    async def read_one(station: dict[str, Any], model: str):
        async with semaphore:
            try:
                return station, model, await forecast(station["id"], model, include_satellite=False), None
            except (ValueError, RuntimeError, httpx.HTTPError) as error:
                return station, model, None, str(error)

    reads = await asyncio.gather(*(read_one(station, model) for station in stations for model in model_ids))
    grouped: dict[str, dict[str, dict[str, Any]]] = {station["id"]: {} for station in stations}
    errors: list[str] = []
    for station, model, result, error in reads:
        if result is not None:
            grouped[station["id"]][model] = result
        elif error:
            errors.append(f"{station['short_name']} {model.upper()}：{error}")

    station_payloads: list[dict[str, Any]] = []
    all_times: list[str] = []
    for station in stations:
        models = grouped[station["id"]]
        if not models:
            continue
        base = next(iter(models.values()))
        series = []
        for index in range(hours):
            timestamp = next((item.get("time") for item in base.get("hourly", [])[index:index + 1]), None)
            values = [
                float(item["hourly"][index]["power_kw"])
                for item in models.values()
                if index < len(item.get("hourly", [])) and item["hourly"][index].get("power_kw") is not None
            ]
            if not values or timestamp is None:
                continue
            low, center, high, confidence = _ensemble(values, float(station["capacity_kw"]))
            ramp = 0.0 if not series else round(center - series[-1]["p50_kw"], 1)
            series.append({"time": timestamp, "p10_kw": low, "p50_kw": center, "p90_kw": high, "ramp_kw": ramp, "confidence": confidence})
            if timestamp not in all_times:
                all_times.append(timestamp)
        if not series:
            continue
        next_window = series[: min(7, len(series))]
        ramp_item = max(next_window[1:] or next_window, key=lambda item: abs(item["ramp_kw"]))
        current = series[0]
        peak = max(item["p50_kw"] for item in series)
        station_payloads.append({
            "station": station,
            "models": list(models),
            "current_kw": current["p50_kw"],
            "peak_kw": round(peak, 1),
            "ramp_kw": ramp_item["ramp_kw"],
            "ramp_time": ramp_item["time"],
            "confidence": current["confidence"],
            "series": series,
        })

    all_times = sorted(all_times)[:hours]
    totals = []
    for timestamp in all_times:
        points = [next((item for item in station["series"] if item["time"] == timestamp), None) for station in station_payloads]
        points = [item for item in points if item]
        if not points:
            continue
        totals.append({
            "time": timestamp,
            "p10_kw": round(sum(item["p10_kw"] for item in points), 1),
            "p50_kw": round(sum(item["p50_kw"] for item in points), 1),
            "p90_kw": round(sum(item["p90_kw"] for item in points), 1),
            "confidence": round(sum(item["confidence"] for item in points) / len(points)),
        })
    for index, item in enumerate(totals):
        item["ramp_kw"] = 0.0 if index == 0 else round(item["p50_kw"] - totals[index - 1]["p50_kw"], 1)

    alerts = []
    for payload in station_payloads:
        capacity = float(payload["station"]["capacity_kw"])
        if abs(payload["ramp_kw"]) < max(1000.0, capacity * 0.08):
            continue
        direction = "上升" if payload["ramp_kw"] > 0 else "下降"
        severity = "high" if abs(payload["ramp_kw"]) >= capacity * 0.2 else "medium"
        alerts.append({
            "station_id": payload["station"]["id"],
            "station_name": payload["station"]["short_name"],
            "type": payload["station"]["type"],
            "time": payload["ramp_time"],
            "direction": direction,
            "ramp_kw": payload["ramp_kw"],
            "ramp_mw": round(payload["ramp_kw"] / 1000, 1),
            "confidence": payload["confidence"],
            "severity": severity,
            "message": f"{payload['station']['short_name']}未来窗口预计{direction} {abs(payload['ramp_kw']) / 1000:.1f} MW",
        })
    alerts.sort(key=lambda item: abs(item["ramp_kw"]), reverse=True)

    capacity_kw = sum(float(item["station"]["capacity_kw"]) for item in station_payloads)
    total_current = totals[0]["p50_kw"] if totals else 0.0
    next_ramp = totals[1]["ramp_kw"] if len(totals) > 1 else 0.0
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "hours": hours,
        "models": [{"id": key, "name": value["name"]} for key, value in MODEL_PARAMS.items()],
        "station_count": len(station_payloads),
        "errors": errors[:12],
        "totals": {
            "capacity_kw": round(capacity_kw, 1),
            "current_kw": round(total_current, 1),
            "next_ramp_kw": round(next_ramp, 1),
            "peak_kw": round(max((item["p50_kw"] for item in totals), default=0.0), 1),
            "confidence": totals[0]["confidence"] if totals else 0,
            "series": totals,
        },
        "alerts": alerts[:8],
        "stations": [{key: value for key, value in payload.items() if key != "models"} for payload in station_payloads],
    }
    _POWER_OUTLOOK_CACHE[cache_key] = (time.monotonic(), result)
    return result
