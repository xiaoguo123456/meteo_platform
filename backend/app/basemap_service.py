"""Esri 全球底图的单机缓存。"""
from __future__ import annotations

import asyncio
import math
import os
import time
from pathlib import Path

import httpx


ESRI_IMAGE_URL = (
    "https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/export"
    "?bbox=-180,-90,180,90&bboxSR=4326&imageSR=4326&size=4096,2048&format=jpg&f=image"
)
DEFAULT_DATA_DIR = Path(os.getenv("METEO_DATA_DIR", str(Path(__file__).resolve().parents[2] / "data")))
CACHE_PATH = DEFAULT_DATA_DIR / "basemap" / "world-imagery-4096x2048.jpg"
CACHE_TTL_SECONDS = int(os.getenv("METEO_BASEMAP_CACHE_TTL", str(30 * 24 * 3600)))
_CACHE_LOCK = asyncio.Lock()
CHINA_BOUNDS = (73.5, 18.0, 135.1, 54.2)
CHINA_STREET_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/export"
CHINA_STREET_PATH = DEFAULT_DATA_DIR / "basemap" / "china-street-1600.png"
_CHINA_STREET_LOCK = asyncio.Lock()


def _fresh(path: Path) -> bool:
    try:
        return path.stat().st_size > 1024 and time.time() - path.stat().st_mtime < CACHE_TTL_SECONDS
    except OSError:
        return False


async def ensure_world_imagery() -> tuple[Path, str]:
    """返回本地底图路径和命中状态，多个请求只允许一次上游下载。"""
    path = CACHE_PATH
    if _fresh(path):
        return path, "hit"
    async with _CACHE_LOCK:
        if _fresh(path):
            return path, "hit"
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".part")
        try:
            async with httpx.AsyncClient(timeout=90, follow_redirects=True) as client:
                response = await client.get(ESRI_IMAGE_URL)
                response.raise_for_status()
                if len(response.content) <= 1024:
                    raise RuntimeError("Esri 底图响应为空")
            temporary.write_bytes(response.content)
            temporary.replace(path)
            return path, "miss"
        except Exception:
            temporary.unlink(missing_ok=True)
            # 已有旧缓存时继续提供底图，避免 Esri 临时波动让页面失去背景。
            if path.exists() and path.stat().st_size > 1024:
                return path, "stale"
            raise


async def warm_world_imagery() -> None:
    """服务启动时提前填充缓存，不阻塞 API 启动。"""
    try:
        await ensure_world_imagery()
    except Exception:
        # 首次启动没有底图时，页面请求会再次尝试并返回明确错误。
        return


def _web_mercator(lon: float, lat: float) -> tuple[float, float]:
    """将经纬度转为 EPSG:3857，供静态底图导出范围使用。"""
    radius = 6378137.0
    clipped_lat = max(-85.05112878, min(85.05112878, lat))
    x = radius * math.radians(lon)
    y = radius * math.log(math.tan(math.pi / 4 + math.radians(clipped_lat) / 2))
    return x, y


def _china_street_url() -> str:
    west, south, east, north = CHINA_BOUNDS
    xmin, ymin = _web_mercator(west, south)
    xmax, ymax = _web_mercator(east, north)
    width = 1600
    height = round(width * (ymax - ymin) / (xmax - xmin))
    params = (
        f"?bbox={xmin:.3f},{ymin:.3f},{xmax:.3f},{ymax:.3f}"
        f"&bboxSR=3857&imageSR=3857&size={width},{height}"
        "&format=png32&transparent=false&f=image"
    )
    return CHINA_STREET_URL + params


async def ensure_china_street_map() -> tuple[Path, str]:
    """返回与 Web Mercator 地图一致的中国 Esri 浅色底图缓存。"""
    path = CHINA_STREET_PATH
    if _fresh(path):
        return path, "hit"
    async with _CHINA_STREET_LOCK:
        if _fresh(path):
            return path, "hit"
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".part")
        try:
            async with httpx.AsyncClient(timeout=90, follow_redirects=True) as client:
                response = await client.get(_china_street_url())
                response.raise_for_status()
                if len(response.content) <= 1024:
                    raise RuntimeError("Esri 中国底图响应为空")
            temporary.write_bytes(response.content)
            temporary.replace(path)
            return path, "miss"
        except Exception:
            temporary.unlink(missing_ok=True)
            if path.exists() and path.stat().st_size > 1024:
                return path, "stale"
            raise
