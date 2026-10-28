import asyncio
import httpx
from contextlib import asynccontextmanager, suppress
from .forecast_cache import sync_loop, read_public_status, cached_field, cached_response, STOP
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from .catalog import MODEL_CATALOG, VARIABLE_CATALOG
from .config import get_settings
from .basemap_service import ensure_china_street_map, ensure_world_imagery, warm_world_imagery
from .schemas import BoundaryCollection, FieldManifest, ModelSummary
from .satellite_service import latest_himawari, local_image_bounds, satellite_loop, station_image
from .spatial_provider import SpatialDataError
from .weather_service import WeatherDataError, get_weather_grid, get_weather_particles
from .site_forecast import SiteCreate, _station, create_station, forecast as site_forecast, list_station_points, list_stations, power_outlook, satellite_radiation
from .price.fetcher import price_loop
from .satellite_catalog import categories as satellite_categories, constellation_members, get_satellite, list_satellites, satellite_orbit_loop, track as satellite_track


settings = get_settings()
@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(sync_loop())
    satellite_task = asyncio.create_task(satellite_loop())
    orbit_task = asyncio.create_task(satellite_orbit_loop())
    basemap_task = asyncio.create_task(warm_world_imagery())
    price_task = asyncio.create_task(price_loop())
    yield
    STOP.set()
    task.cancel()
    satellite_task.cancel()
    orbit_task.cancel()
    basemap_task.cancel()
    price_task.cancel()
    with suppress(asyncio.CancelledError):
        await satellite_task
    with suppress(asyncio.CancelledError):
        await task
    with suppress(asyncio.CancelledError):
        await orbit_task
    with suppress(asyncio.CancelledError):
        await basemap_task
    with suppress(asyncio.CancelledError):
        await price_task

app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=6)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "meteo-api"}


@app.get("/api/version")
def version():
    """返回当前运行代码对应的 git 提交，用于核对线上部署版本。"""
    from fastapi.responses import JSONResponse
    from .build_info import build_info
    return JSONResponse(build_info(), headers={"Cache-Control": "no-store", "CDN-Cache-Control": "no-store"})


@app.get("/api/basemap/world-imagery")
async def world_imagery_basemap():
    """服务端缓存 Esri 全球影像，浏览器后续直接命中本地响应。"""
    from fastapi.responses import FileResponse

    try:
        path, state = await ensure_world_imagery()
        return FileResponse(
            path,
            media_type="image/jpeg",
            headers={
                "Cache-Control": "public, max-age=604800, stale-while-revalidate=86400",
                "Content-Encoding": "identity",
                "X-Basemap-Cache": state,
            },
        )
    except (httpx.HTTPError, OSError, RuntimeError) as error:
        raise HTTPException(status_code=503, detail=f"Esri 底图加载失败：{error}") from error


@app.get("/api/basemap/china-street")
async def china_street_basemap():
    """服务端缓存与态势地图投影一致的 Esri 中国浅色底图。"""
    from fastapi.responses import FileResponse

    try:
        path, state = await ensure_china_street_map()
        return FileResponse(
            path,
            media_type="image/png",
            headers={
                "Cache-Control": "public, max-age=604800, stale-while-revalidate=86400",
                "Content-Encoding": "identity",
                "X-Basemap-Cache": state,
                "X-Basemap-Attribution": "Esri, HERE, Garmin, (c) OpenStreetMap contributors",
            },
        )
    except (httpx.HTTPError, OSError, RuntimeError) as error:
        raise HTTPException(status_code=503, detail=f"Esri 中国底图加载失败：{error}") from error


@app.get("/api/models", response_model=list[ModelSummary])
def models() -> list[dict[str, str]]:
    return MODEL_CATALOG


@app.get("/api/variables")
def variables() -> list[dict[str, str]]:
    return VARIABLE_CATALOG


@app.get("/api/satellites")
def satellites(keyword: str = "", category: str = "", limit: int = Query(default=80, ge=1, le=200)) -> dict[str, object]:
    """卫星目录摘要。轨道位置由服务端按当前轨道参数生成，前端不接触原始编目文件。"""
    return list_satellites(keyword=keyword, category=category, limit=limit)


@app.get("/api/satellites/categories")
def satellite_category_list() -> list[dict[str, str]]:
    return satellite_categories()


@app.get("/api/satellites/{satellite_id}/members")
def satellite_members(satellite_id: str, limit: int = Query(default=80, ge=1, le=200)) -> dict[str, object]:
    value = constellation_members(satellite_id, limit=limit)
    if not value:
        raise HTTPException(status_code=404, detail="该卫星不是可展开的星座条目")
    return value


@app.get("/api/satellites/{satellite_id}")
def satellite_detail(satellite_id: str, at: Optional[str] = Query(default=None, max_length=40), orbits: int = Query(default=3, ge=1, le=5)) -> dict[str, object]:
    try:
        value = get_satellite(satellite_id, at=at, orbits=orbits)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    if not value:
        raise HTTPException(status_code=404, detail="卫星资料不存在")
    return value


@app.get("/api/satellites/{satellite_id}/track")
def satellite_orbit_track(satellite_id: str, hours: float = Query(default=6, ge=0.5, le=24), step_minutes: int = Query(default=2, ge=1, le=60), at: Optional[str] = Query(default=None, max_length=40), orbits: Optional[int] = Query(default=None, ge=1, le=5)) -> dict[str, object]:
    try:
        value = satellite_track(satellite_id, hours=hours, step_minutes=step_minutes, at=at, orbits=orbits)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    if not value:
        raise HTTPException(status_code=404, detail="卫星轨迹不存在")
    return value


@app.get("/api/site-stations")
def site_stations(
    keyword: str = Query(default="", max_length=80),
    type: Optional[str] = Query(default=None, pattern="^(wind|solar)$"),
    province: str = Query(default="", max_length=32),
    sort: str = Query(default="capacity", pattern="^(capacity|name)$"),
    limit: int = Query(default=60, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    """EnerSight 风格的公开站点目录，站点预测不需要登录。"""
    from fastapi.responses import JSONResponse
    return JSONResponse(
        list_stations(keyword=keyword, type_=type, province=province, sort=sort, limit=limit, offset=offset),
        headers={
            "Cache-Control": "public, max-age=60, s-maxage=300, stale-while-revalidate=60",
            "CDN-Cache-Control": "max-age=300, stale-while-revalidate=60",
        },
    )


@app.get("/api/power-outlook/stations")
def power_outlook_stations() -> dict[str, object]:
    """返回全量新能源站点轻量坐标，前端只做密度聚合，不触发逐站预测。"""
    from fastapi.responses import JSONResponse
    return JSONResponse(
        list_station_points(),
        headers={
            "Cache-Control": "public, max-age=300, s-maxage=1800, stale-while-revalidate=600",
            "CDN-Cache-Control": "max-age=1800, stale-while-revalidate=600",
        },
    )


@app.post("/api/site-stations")
def create_site_station(payload: SiteCreate) -> dict[str, object]:
    """新增自定义场站，数据保存在服务端 data 目录。"""
    return create_station(payload)


@app.get("/api/site-forecast")
async def site_forecast_data(station_id: str = "zhangbei-wind", model: str = "gfs") -> dict[str, object]:
    try:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            await site_forecast(station_id, model, include_satellite=False),
            headers={
                "Cache-Control": "public, max-age=0, s-maxage=30, stale-while-revalidate=60",
                "CDN-Cache-Control": "max-age=30, stale-while-revalidate=60",
            },
        )
    except (ValueError, RuntimeError, httpx.HTTPError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.get("/api/site-satellite")
async def site_satellite_data(station_id: str = "ningxia-solar") -> dict[str, object]:
    try:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            await satellite_radiation(station_id),
            headers={
                "Cache-Control": "public, max-age=0, s-maxage=300, stale-while-revalidate=300",
                "CDN-Cache-Control": "max-age=300, stale-while-revalidate=300",
            },
        )
    except (ValueError, RuntimeError, httpx.HTTPError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.get("/api/power-outlook")
async def power_outlook_data(
    hours: int = Query(default=24, ge=6, le=48),
    limit: int = Query(default=12, ge=1, le=24),
) -> dict[str, object]:
    """新能源态势：聚合全量站点的多模型区域功率区间和爬坡预警。"""
    try:
        return await power_outlook(hours=hours, limit=limit)
    except (ValueError, RuntimeError, httpx.HTTPError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.get("/api/models/{model_id}/runs")
def model_runs(model_id: str) -> dict[str, object]:
    try:
        from fastapi.responses import JSONResponse
        # 国内经 Cloudflare 洛杉矶节点回源很慢：边缘缓存 5 秒、过期后 30 秒内先返回旧清单并后台刷新，
        # 每 10 秒的轮询大多在边缘直接返回。切换后上一批仍保留，晚几十秒看到新批次也不会读取失败。
        # 浏览器不缓存（前端另以 no-store 请求，绕过 Cloudflare 规则改写的浏览器缓存时间）。
        edge = "max-age=5, stale-while-revalidate=30"
        return JSONResponse(
            read_public_status(model_id),
            headers={
                "Cache-Control": "no-cache",
                "CDN-Cache-Control": edge,
                "Cloudflare-CDN-Cache-Control": edge,
            },
        )
    except SpatialDataError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.get("/api/fields/{model_id}")
async def weather_grid(model_id: str, hours: int = 48, refresh: bool = False) -> dict[str, object]:
    try:
        return await get_weather_grid(model_id, hours=hours, force_refresh=refresh)
    except (SpatialDataError, WeatherDataError, ValueError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.get("/api/fields/{model_id}/particles")
async def weather_particles(model_id: str, hours: int = 48, max_points: int = 6000, refresh: bool = False) -> dict[str, object]:
    try:
        return await get_weather_particles(model_id, hours=hours, max_points=max_points, force_refresh=refresh)
    except (SpatialDataError, WeatherDataError, ValueError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.get("/api/wind/{model_id}")
async def native_wind(request: Request, model_id: str, field: str = "wind", run_time: str = None, valid_time: str = None, format: str = "raw"):
    from fastapi.responses import Response
    from fastapi.responses import FileResponse
    try:
        if format == 'packed':
            path = await asyncio.to_thread(cached_response, model_id, field, run_time, valid_time)
            headers = {"Vary": "Accept-Encoding", "Cache-Control": "public, max-age=31536000, immutable" if run_time and valid_time else "no-cache"}
            if 'gzip' in request.headers.get('accept-encoding', ''):
                headers['Content-Encoding'] = 'gzip'
                return FileResponse(path, media_type='application/octet-stream', headers=headers)
            import gzip
            body = await asyncio.to_thread(lambda: gzip.decompress(path.read_bytes()))
            return Response(body, media_type='application/octet-stream', headers=headers)
        return Response(await asyncio.to_thread(cached_field, model_id, field, run_time, valid_time), media_type="application/octet-stream",
                        headers={"Cache-Control": "no-cache"})
    except SpatialDataError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.get("/api/fields/{model_id}/{valid_time}", response_model=FieldManifest)
def field_manifest(model_id: str, valid_time: str) -> FieldManifest:
    return FieldManifest(
        model=model_id,
        run_time=datetime.now(timezone.utc).isoformat(),
        valid_time=valid_time,
        bbox=[-180, -90, 180, 90],
        width=720,
        height=361,
        variables=["u10", "v10", "temperature_2m", "surface_pressure"],
        encoding="float32-gzip",
        data_url=None,
    )


@app.get("/api/satellite/himawari/latest")
async def himawari_latest(product: str = 'truecolor') -> dict[str, object]:
    try:return await latest_himawari(product)
    except ValueError as error:raise HTTPException(status_code=400, detail=str(error)) from error


@app.get('/api/satellite/himawari/station/{station_id}')
async def himawari_station_image(station_id: str, product: str = 'truecolor'):
    """按场站周边 bbox 获取葵花局部瓦片，前端右侧直接展示。"""
    from fastapi.responses import Response
    try:
        station = _station(station_id)
        observed, content = await station_image(station_id, station['latitude'], station['longitude'], product)
        west, south, east, north = local_image_bounds(station['longitude'], station['latitude'])
        return Response(content, media_type='image/webp', headers={
            'Cache-Control': 'public, max-age=60',
            'X-Satellite-Time': observed,
            'X-Satellite-Product': product,
            'X-Satellite-Bounds': f'{west:.6f},{south:.6f},{east:.6f},{north:.6f}',
        })
    except (ValueError, RuntimeError, httpx.HTTPError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.get('/api/boundaries/provinces')
def province_boundaries():
    from fastapi.responses import FileResponse
    return FileResponse(Path(__file__).parent/'data/provinces.geojson', media_type='application/geo+json',
                        headers={'Cache-Control':'public, max-age=86400'})

@app.get('/api/tiles/{model_id}')
async def native_tiles(model_id: str, field: str, run_time: str, valid_time: str, tiles: str, version: int = 3, scale: int = 1):
    from .tile_cache import cached_tiles
    from fastapi.responses import StreamingResponse
    try:
        ids = [int(value) for value in tiles.split(',')]
        stream, length = await asyncio.to_thread(cached_tiles, model_id, field, run_time, valid_time, ids, version, scale)
        return StreamingResponse(stream, media_type='application/octet-stream', headers={
            'Content-Length': str(length), 'Cache-Control':'public, max-age=31536000, immutable',
            # 分块内部已 gzip，禁止中间件再次压缩，保持逐块到达。
            'Content-Encoding':'identity', 'X-Accel-Buffering':'no'})
    except (ValueError, SpatialDataError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

@app.get('/api/point/{model_id}')
async def point_series(model_id: str, longitude: float, latitude: float, field: str = 'temperature', run_time: str = None):
    from .point_forecast import point_forecast
    try:
        return await asyncio.to_thread(point_forecast, model_id, field, longitude, latitude, run_time)
    except (ValueError, SpatialDataError, OSError, KeyError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

@app.get('/api/provinces')
def provinces():
    from fastapi.responses import JSONResponse
    from .province_stats import province_list
    return JSONResponse(province_list(), headers={'Cache-Control': 'public, max-age=86400'})

@app.get('/api/provinces/locate')
def locate_province(longitude: float, latitude: float):
    """点击位置所在省份；境外或海上返回 null。"""
    from .province_stats import locate
    return locate(longitude, latitude)

@app.get('/api/provinces/shapes')
def province_shapes():
    from fastapi.responses import JSONResponse
    from .province_stats import shapes
    return JSONResponse(shapes(), headers={'Cache-Control': 'public, max-age=86400'})

@app.get('/api/province-map/{model_id}')
async def province_values(model_id: str, field: str, run_time: str, valid_time: str):
    """某一时刻全部省份的省平均，固定批次与时刻的结果不会变化。"""
    from fastapi.responses import JSONResponse
    from .province_stats import province_map
    try:
        value = await asyncio.to_thread(province_map, model_id, field, run_time, valid_time)
    except (ValueError, SpatialDataError, OSError, KeyError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return JSONResponse(value, headers={'Cache-Control': 'public, max-age=86400'})

@app.get('/api/provinces/{code}/outline')
def province_outline(code: str):
    from fastapi.responses import JSONResponse
    from .province_stats import regions
    region = regions().get(code)
    if not region:
        raise HTTPException(status_code=404, detail='省份代码无效')
    return JSONResponse({'type': 'Feature', 'properties': {'code': code, 'name': region['name']}, 'geometry': region['geometry']},
                        headers={'Cache-Control': 'public, max-age=86400'})

@app.get('/api/province-forecast/{model_id}')
async def province_series(model_id: str, code: str, field: str = 'temperature', run_time: str = None):
    from .province_stats import province_forecast
    try:
        return await asyncio.to_thread(province_forecast, model_id, field, code, run_time)
    except (ValueError, SpatialDataError, OSError, KeyError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

@app.get('/api/satellite/himawari/images/{product}/{time}.display.webp')
async def satellite_image(product: str, time: str):
    from .satellite_service import display_path
    from fastapi.responses import FileResponse
    try:
        return FileResponse(display_path(time,product), media_type='image/webp', headers={'Cache-Control':'public, max-age=86400, immutable','Content-Encoding':'identity'})
    except (ValueError, FileNotFoundError) as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

from .news.api import router as news_router
app.include_router(news_router)
from .price.api import router as price_router
app.include_router(price_router)
