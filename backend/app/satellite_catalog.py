"""卫星轨迹与资料卡目录。

轨道位置由目录里的公开轨道参数计算。目录本身故意采用可扩展的结构：
后续同步 CelesTrak/Space-Track 的 OMM 或 TLE 时，只需替换 orbit 字段，前端
不需要改动。mission 字段是可核验的种子资料，ai 字段保留给大模型批量整理结果。
"""
from __future__ import annotations

import math
import json
import os
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

try:
    from sgp4.api import Satrec, jday
except ImportError:  # 本地未安装依赖时仍保留目录和可视化轨迹
    Satrec = None
    jday = None


CATEGORIES: list[dict[str, str]] = [
    {"id": "weather", "name": "气象卫星", "description": "气象观测、云图和大气探测"},
    {"id": "earth-observation", "name": "地球遥感", "description": "光学、雷达和高光谱遥感"},
    {"id": "ocean", "name": "海洋观测", "description": "海面高度、海色和海洋环境"},
    {"id": "communications", "name": "通信卫星", "description": "固定通信、移动通信和数据中继"},
    {"id": "leo-internet", "name": "低轨互联网", "description": "低轨宽带和星座通信"},
    {"id": "navigation", "name": "导航定位", "description": "导航、授时和增强服务"},
    {"id": "science", "name": "空间科学", "description": "天文、太阳和空间物理任务"},
    {"id": "space-weather", "name": "空间天气", "description": "太阳风、磁层和空间天气监测"},
    {"id": "geodesy", "name": "测绘与地球物理", "description": "重力场、测高和地球物理测量"},
    {"id": "crewed", "name": "载人航天", "description": "空间站、载人飞船和货运飞船"},
    {"id": "search-rescue", "name": "搜救与中继", "description": "遇险信标搜救和数据中继"},
    {"id": "technology", "name": "技术验证", "description": "新载荷、编队和平台技术验证"},
    {"id": "amateur", "name": "教育与业余无线电", "description": "大学、教育和业余无线电任务"},
    {"id": "security", "name": "安全与侦察", "description": "仅按公开资料标注的安全相关任务"},
    {"id": "debris", "name": "轨道目标", "description": "火箭末级、空间碎片和未知目标"},
]


def _source(title: str, url: str, source_type: str = "官方") -> dict[str, str]:
    return {"title": title, "url": url, "type": source_type}


def _satellite(
    id: str,
    name: str,
    category: str,
    country: str,
    operator: str,
    purpose: str,
    summary: str,
    period_minutes: float,
    inclination: float,
    altitude: float,
    base_longitude: float,
    phase: float,
    *,
    norad_id: int | None = None,
    cospar_id: str = "",
    launch_date: str = "",
    source_urls: list[dict[str, str]] | None = None,
    orbit_class: str = "LEO",
    subcategories: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": id,
        "name": name,
        "aliases": [],
        "category": category,
        "subcategories": subcategories or [],
        "country": country,
        "operator": operator,
        "purpose": purpose,
        "mission_summary": summary,
        "launch_date": launch_date,
        "cospar_id": cospar_id,
        "norad_id": norad_id,
        "orbit": {
            "orbit_class": orbit_class,
            "period_minutes": period_minutes,
            "inclination_deg": inclination,
            "altitude_km": altitude,
            "apogee_km": altitude,
            "perigee_km": altitude,
            "eccentricity": 0.0,
            "epoch": "目录参数",
            "source": "CelesTrak / Space-Track 轨道目录（参数同步位）",
        },
        "_ground": {"base_longitude": base_longitude, "phase": phase},
        "sources": source_urls or [],
        "ai": {
            "state": "seeded",
            "summary": summary,
            "points": [],
            "confidence": "基础资料",
            "model": None,
            "updated_at": None,
        },
    }


# 这是第一版的代表性目录，不试图冒充完整卫星编目。新增条目只需添加一个对象。
SATELLITES: list[dict[str, Any]] = [
    _satellite("fy-4a", "风云四号 A", "weather", "中国", "中国气象局", "静止气象观测", "中国第二代静止气象卫星，承担云图、大气和灾害天气连续监测。", 1436, 0.1, 35786, 104.7, 0.1, norad_id=41882, cospar_id="2016-078A", launch_date="2016-12-11", orbit_class="GEO", source_urls=[_source("中国气象局风云四号", "https://www.cma.gov.cn/2011zjt/2011zjty/2011ztjj/2011ztjj01/201612/t20161211_344232.html"), _source("CelesTrak GEO", "https://celestrak.org/NORAD/elements/gp.php?GROUP=geo&FORMAT=JSON", "轨道")]),
    _satellite("fy-4b", "风云四号 B", "weather", "中国", "中国气象局", "静止气象观测", "风云四号系列静止气象卫星，提供高频率、宽覆盖的云图和大气观测。", 1436, 0.2, 35786, 133.0, 1.2, norad_id=49349, cospar_id="2021-048A", launch_date="2021-06-03", orbit_class="GEO", source_urls=[_source("中国气象局卫星资料", "https://www.cma.gov.cn/2011zjt/2011zjty/2011ztjj/2011ztjj01/")]),
    _satellite("himawari-9", "向日葵九号", "weather", "日本", "日本气象厅 JMA", "静止气象观测", "日本静止气象卫星，覆盖东亚、西太平洋和澳大利亚附近海域。", 1436, 0.1, 35786, 140.7, 0.4, norad_id=41836, cospar_id="2016-064A", launch_date="2016-11-02", orbit_class="GEO", source_urls=[_source("JMA Himawari", "https://www.jma.go.jp/jma/jma-eng/satellite/")]),
    _satellite("goes-16", "GOES-16", "weather", "美国", "NOAA", "静止气象观测", "NOAA 东部业务静止气象卫星，持续提供云图、雷暴和空间天气观测。", 1436, 0.1, 35786, -75.2, 0.9, norad_id=41866, cospar_id="2016-071A", launch_date="2016-11-19", orbit_class="GEO", source_urls=[_source("NOAA GOES-R", "https://www.goes-r.gov/")]),
    _satellite("metop-c", "Metop-C", "weather", "欧洲", "EUMETSAT", "极轨气象观测", "欧洲极轨气象卫星，为数值天气预报提供大气温湿度和地球表面观测。", 101.5, 98.7, 817, 20.0, 1.4, norad_id=43689, cospar_id="2018-087A", launch_date="2018-11-07", source_urls=[_source("EUMETSAT Metop", "https://www.eumetsat.int/metop")]),
    _satellite("sentinel-1a", "Sentinel-1A", "earth-observation", "欧盟", "ESA / 欧盟委员会", "SAR 雷达遥感", "Copernicus Sentinel-1 雷达卫星，用于全天时、全天候地表和海洋观测。", 98.7, 98.2, 693, 0, 2.2, norad_id=39634, cospar_id="2014-016A", launch_date="2014-04-03", source_urls=[_source("ESA Sentinel-1", "https://www.esa.int/Applications/Observing_the_Earth/Copernicus/Sentinel-1")]),
    _satellite("sentinel-2a", "Sentinel-2A", "earth-observation", "欧盟", "ESA / 欧盟委员会", "光学遥感", "Copernicus 光学成像卫星，服务土地覆盖、农业、灾害和生态监测。", 100.6, 98.6, 786, 0, 0.6, norad_id=40697, cospar_id="2015-028A", launch_date="2015-06-23", source_urls=[_source("ESA Sentinel-2", "https://www.esa.int/Applications/Observing_the_Earth/Copernicus/Sentinel-2")]),
    _satellite("landsat-9", "Landsat 9", "earth-observation", "美国", "NASA / USGS", "陆地光学遥感", "持续记录陆地表面变化，为资源、生态、农业和灾害监测提供数据。", 98.8, 98.2, 705, 0, 1.7, norad_id=49260, cospar_id="2021-088A", launch_date="2021-09-27", source_urls=[_source("USGS Landsat 9", "https://www.usgs.gov/landsat-missions/landsat-9")]),
    _satellite("terra", "Terra", "earth-observation", "美国", "NASA", "地球系统观测", "NASA 地球观测旗舰任务，综合观测陆地、海洋、大气和能量平衡。", 98.8, 98.2, 705, 0, 2.9, norad_id=25994, cospar_id="1999-068A", launch_date="1999-12-18", source_urls=[_source("NASA Terra", "https://terra.nasa.gov/")]),
    _satellite("gaofen-3", "高分三号", "earth-observation", "中国", "中国航天科技集团", "海洋与陆地 SAR 遥感", "中国高分辨率 C 波段 SAR 卫星，适合海洋、灾害和地表形变观测。", 97.5, 98.4, 755, 0, 1.1, norad_id=41727, cospar_id="2016-049A", launch_date="2016-08-09", source_urls=[_source("中国高分专项", "https://www.sastind.gov.cn/")], subcategories=["SAR", "海洋"]),
    _satellite("starlink-group", "Starlink 星座", "leo-internet", "美国", "SpaceX", "低轨宽带通信", "低轨宽带通信星座，条目按星座展示，后续可由轨道目录展开到单星。", 95, 53.2, 550, -20, 0.8, source_urls=[_source("Starlink 官方", "https://www.starlink.com/")], subcategories=["通信", "星座"]),
    _satellite("oneweb-group", "Eutelsat OneWeb 星座", "leo-internet", "英国", "Eutelsat OneWeb", "低轨宽带通信", "全球低轨通信星座，条目按星座展示，后续可展开单颗卫星。", 109, 87.9, 1200, 10, 1.5, source_urls=[_source("Eutelsat OneWeb", "https://www.eutelsat.com/en/satellites/oneweb.html")], subcategories=["通信", "星座"]),
    _satellite("gps-iif", "GPS IIF 代表星", "navigation", "美国", "美国太空军", "导航与授时", "GPS 导航星座代表条目，展示导航卫星的典型中圆轨道参数。", 718, 55, 20200, -70, 0.5, orbit_class="MEO", source_urls=[_source("GPS 官方", "https://www.gps.gov/systems/gps/space/")]),
    _satellite("beidou-meo", "北斗三号 MEO 代表星", "navigation", "中国", "中国卫星导航系统管理办公室", "导航与授时", "北斗全球卫星导航系统中圆轨道代表条目，支持全球定位、导航和授时。", 717, 55, 21528, 100, 0.9, orbit_class="MEO", source_urls=[_source("中国北斗卫星导航系统", "https://www.beidou.gov.cn/")]),
    _satellite("galileo", "Galileo 代表星", "navigation", "欧盟", "欧盟委员会 / ESA", "导航与授时", "欧洲 Galileo 全球导航卫星系统代表条目。", 843, 56, 23222, 20, 0.7, orbit_class="MEO", source_urls=[_source("ESA Galileo", "https://www.esa.int/Applications/Navigation/Galileo")]),
    _satellite("iss", "国际空间站", "crewed", "国际合作", "NASA / Roscosmos / ESA 等", "载人空间站", "长期载人轨道实验室，开展微重力科学、生命科学和空间技术试验。", 92.7, 51.6, 408, 0, 0.2, norad_id=25544, cospar_id="1998-067A", launch_date="1998-11-20", source_urls=[_source("NASA International Space Station", "https://www.nasa.gov/international-space-station/")]),
    _satellite("tiangong", "中国空间站", "crewed", "中国", "中国载人航天工程办公室", "载人空间站", "中国长期有人照料的国家空间实验室，开展空间科学和应用技术试验。", 92.2, 41.5, 390, 0, 1.4, norad_id=48274, cospar_id="2021-035A", launch_date="2021-04-29", source_urls=[_source("中国载人航天", "https://www.cmse.gov.cn/")]),
    _satellite("hubble", "哈勃空间望远镜", "science", "美国", "NASA / ESA", "天文观测", "在近地轨道开展紫外、可见光和近红外天文观测。", 95.4, 28.5, 540, 0, 2.4, norad_id=20580, cospar_id="1990-037B", launch_date="1990-04-24", source_urls=[_source("NASA Hubble", "https://science.nasa.gov/mission/hubble/")]),
    _satellite("dscovr", "DSCOVR", "space-weather", "美国", "NOAA / NASA / USSF", "太阳风和空间天气", "在日地 L1 附近监测太阳风，为空间天气预警提供数据。", 0, 0, 1500000, 0, 0, norad_id=40390, cospar_id="2015-007A", launch_date="2015-02-11", orbit_class="日地 L1", source_urls=[_source("NOAA DSCOVR", "https://www.nesdis.noaa.gov/our-satellites/dscovr")]),
    _satellite("grace-fo", "GRACE-FO 代表星", "geodesy", "美国 / 德国", "NASA / GFZ", "重力场测量", "通过双星编队测量地球重力场变化，服务水资源和冰盖研究。", 94.5, 89, 490, 0, 1.8, source_urls=[_source("NASA GRACE-FO", "https://gracefo.jpl.nasa.gov/")], subcategories=["重力场", "编队飞行"]),
    _satellite("cubesat-demo", "CubeSat 技术验证代表", "technology", "多国", "高校与商业机构", "技术验证", "用于展示小卫星平台、通信、姿态控制或新型载荷的技术验证任务。", 96, 97, 500, 0, 1.1, source_urls=[_source("NASA Small Satellite Missions", "https://www.nasa.gov/smallsat-institute/")], subcategories=["CubeSat", "技术验证"]),
]

CONSTELLATION_GROUPS: dict[str, dict[str, Any]] = {
    "starlink-group": {"group": "starlink", "count": 24, "country": "美国", "operator": "SpaceX", "purpose": "低轨宽带通信"},
    "oneweb-group": {"group": "oneweb", "count": 16, "country": "英国", "operator": "Eutelsat OneWeb", "purpose": "低轨宽带通信"},
}
for _item in SATELLITES:
    if _item["id"] in CONSTELLATION_GROUPS:
        _item["is_constellation"] = True
        _item["member_count"] = CONSTELLATION_GROUPS[_item["id"]]["count"]


def orbit_cache_path() -> Path:
    return Path(os.getenv("METEO_DATA_DIR", str(Path(__file__).resolve().parents[2] / "data"))) / "satellite_orbits.json"


def constellation_cache_path() -> Path:
    return Path(os.getenv("METEO_DATA_DIR", str(Path(__file__).resolve().parents[2] / "data"))) / "satellite_constellations.json"


def _orbit_cache() -> dict[str, Any]:
    path = orbit_cache_path()
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _constellation_cache() -> dict[str, Any]:
    path = constellation_cache_path()
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _merged_item(item: dict[str, Any]) -> dict[str, Any]:
    cached = _orbit_cache().get(item["id"])
    if not isinstance(cached, dict):
        return item
    value = {**item, "orbit": {**item["orbit"], **cached.get("orbit", {})}}
    if cached.get("tle"):
        value["_tle"] = cached["tle"]
    return value


def _seed_constellation_members(parent_id: str) -> list[dict[str, Any]]:
    """上游暂不可用时保留少量可用的星座代表轨道，真实目录同步后自动替换。"""
    parent = next((value for value in SATELLITES if value["id"] == parent_id), None)
    config = CONSTELLATION_GROUPS.get(parent_id)
    if not parent or not config:
        return []
    members: list[dict[str, Any]] = []
    count = int(config["count"])
    for index in range(count):
        member_id = f"{parent_id}-member-{index + 1:02d}"
        member = _satellite(
            member_id,
            f"{parent['name'].replace(' 星座', '')}-{index + 1:02d}",
            parent["category"],
            config["country"],
            config["operator"],
            config["purpose"],
            f"{parent['name']}的单星轨道条目。选择后显示该卫星相对于地球的当前轨迹。",
            parent["orbit"]["period_minutes"],
            parent["orbit"]["inclination_deg"],
            parent["orbit"]["altitude_km"],
            parent["_ground"]["base_longitude"],
            parent["_ground"]["phase"] + index * (360 / max(1, count)),
            orbit_class=parent["orbit"]["orbit_class"],
            source_urls=parent["sources"],
            subcategories=parent.get("subcategories", []),
        )
        member["parent_id"] = parent_id
        member["is_constellation_member"] = True
        members.append(member)
    return members


def _constellation_members(parent_id: str) -> list[dict[str, Any]]:
    cached = _constellation_cache().get(parent_id)
    if isinstance(cached, dict) and isinstance(cached.get("members"), list) and cached["members"]:
        return [value for value in cached["members"] if isinstance(value, dict)]
    return _seed_constellation_members(parent_id)


def constellation_members(parent_id: str, limit: int = 80) -> dict[str, Any]:
    if parent_id not in CONSTELLATION_GROUPS:
        return {}
    members = _constellation_members(parent_id)
    selected = members[:max(1, min(limit, 200))]
    items: list[dict[str, Any]] = []
    for member in selected:
        value = _public_record(member)
        points = build_track(member, hours=_orbit_window_hours(member), step_minutes=2)
        value["position"] = points[len(points) // 2] if points else None
        value["track"] = [{"longitude": point["longitude"], "latitude": point["latitude"]} for point in points]
        value["parent_id"] = parent_id
        value["is_constellation_member"] = True
        items.append(value)
    return {"parent_id": parent_id, "items": items, "total": len(members), "updated_at": _constellation_cache().get(parent_id, {}).get("updated_at")}


def _find_satellite(satellite_id: str) -> dict[str, Any] | None:
    item = next((value for value in SATELLITES if value["id"] == satellite_id), None)
    if item:
        return item
    for parent_id in CONSTELLATION_GROUPS:
        item = next((value for value in _constellation_members(parent_id) if value.get("id") == satellite_id), None)
        if item:
            return item
    return None


def _orbit_window_hours(item: dict[str, Any], orbits: int = 1) -> float:
    """按轨道圈数计算时间窗口的一半。"""
    period = float(item.get("orbit", {}).get("period_minutes") or 90)
    return min(24.0, max(0.5, period * max(1, orbits) / 120.0))


def _parse_target_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("定位时间格式无效") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(second=0, microsecond=0)


def _public_record(item: dict[str, Any], include_track: bool = False) -> dict[str, Any]:
    item = _merged_item(item)
    value = {k: v for k, v in item.items() if not k.startswith("_")}
    cache_path = Path(os.getenv("METEO_DATA_DIR", str(Path(__file__).resolve().parents[2] / "data"))) / "satellite_ai.json"
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8")).get(item["id"])
            if isinstance(cached, dict):
                value["ai"] = {**value.get("ai", {}), **cached}
        except (OSError, ValueError, TypeError):
            pass
    if include_track:
        value["track"] = build_track(item)
    return value


def categories() -> list[dict[str, str]]:
    return CATEGORIES


def list_satellites(keyword: str = "", category: str = "", limit: int = 80) -> dict[str, Any]:
    keyword = keyword.strip().lower()
    selected = [
        item for item in SATELLITES
        if (not category or item["category"] == category)
        and (not keyword or keyword in (item["name"] + " " + item["purpose"] + " " + item["operator"]).lower())
    ]
    selected = selected[:max(1, min(limit, 200))]
    public_items = []
    for item in selected:
        value = _public_record(item)
        if item.get("is_constellation"):
            value["member_count"] = len(_constellation_members(item["id"]))
        points = build_track(item, hours=0, step_minutes=2)
        value["position"] = points[len(points) // 2] if points else None
        value["track"] = [{"longitude": point["longitude"], "latitude": point["latitude"]} for point in build_track(item, step_minutes=2, orbits=1)]
        public_items.append(value)
    return {
        "items": public_items,
        "total": len(selected),
        "categories": CATEGORIES,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "晴川观象卫星资料库（轨道目录同步位）",
    }


def get_satellite(satellite_id: str, at: str | None = None, orbits: int = 3) -> dict[str, Any] | None:
    item = _find_satellite(satellite_id)
    if not item:
        return None
    item = _merged_item(item)
    value = _public_record(item)
    target_time = _parse_target_time(at)
    value["track"] = build_track(item, step_minutes=2, center_time=target_time, orbits=orbits)
    points = value.get("track") or []
    value["position"] = points[len(points) // 2] if points else None
    return value


def _gmst_radians(jd: float, fr: float) -> float:
    """将 SGP4 的 TEME 惯性坐标转换为相对地球的经度。"""
    days = jd + fr - 2451545.0
    centuries = days / 36525.0
    degrees = 280.46061837 + 360.98564736629 * days + 0.000387933 * centuries**2 - centuries**3 / 38710000.0
    return math.radians(degrees % 360.0)


def build_track(item: dict[str, Any], hours: float = 4, step_minutes: int = 2, center_time: datetime | None = None, orbits: int | None = None) -> list[dict[str, Any]]:
    """根据轨道参数生成可视化轨迹。

    对 GEO 和日地 L1 使用简化模型；接入真实 OMM/TLE 后由同步器替换这里的
    ground points，接口和前端格式保持不变。
    """
    item = _merged_item(item)
    orbit = item["orbit"]
    now = (center_time or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(second=0, microsecond=0)
    if orbit["orbit_class"] == "日地 L1":
        return [{"time": now.isoformat(), "longitude": item["_ground"]["base_longitude"], "latitude": 0.0, "altitude_km": orbit["altitude_km"], "velocity_km_s": 0.0}]
    # 静止卫星相对地面基本不移动。即使 TLE 传播出很小的经纬度摆动，
    # 页面也应以固定站点展示，避免把它误画成一条低轨卫星式轨迹。
    if orbit["orbit_class"] == "GEO":
        # 页面上的 GEO 标记代表固定地面站点，不把 TLE 的小倾角摆动画成地表移动。
        return [{"time": now.isoformat(), "longitude": item["_ground"]["base_longitude"], "latitude": 0.0, "altitude_km": orbit["altitude_km"], "velocity_km_s": 0.0}]
    # 已同步 TLE 时使用真实 SGP4 传播；没有依赖或上游数据时才回退到参数轨迹。
    tle = item.get("_tle")
    if Satrec and jday and isinstance(tle, list) and len(tle) >= 2:
        try:
            satrec = Satrec.twoline2rv(tle[0], tle[1])
            points: list[dict[str, Any]] = []
            # 轨道线表示当前时刻的闭合轨道面，而不是把地球自转也叠加进去的地面轨迹。
            # 对整段采样使用同一个 GMST，首尾在一个周期后能够回到同一条轨道线上。
            reference_jd, reference_fr = jday(now.year, now.month, now.day, now.hour, now.minute, now.second)
            reference_gmst = _gmst_radians(reference_jd, reference_fr)
            period = float(orbit["period_minutes"] or 90)
            total_minutes = period * max(1, orbits) if orbits is not None else hours * 120
            sample_count = max(2, math.ceil(total_minutes / max(1, step_minutes)))
            if sample_count % 2:
                sample_count += 1
            offsets = (-total_minutes / 2 + total_minutes * index / sample_count for index in range(sample_count + 1))
            for minute in offsets:
                value = now + timedelta(minutes=minute)
                jd, fr = jday(value.year, value.month, value.day, value.hour, value.minute, value.second)
                error, position, velocity = satrec.sgp4(jd, fr)
                if error:
                    raise ValueError(f"SGP4 error {error}")
                x, y, z = position
                radius = math.sqrt(x * x + y * y + z * z)
                points.append({
                    "time": value.isoformat(),
                    "longitude": round((math.degrees(math.atan2(y, x) - reference_gmst) + 180) % 360 - 180, 5),
                    "latitude": round(math.degrees(math.asin(max(-1, min(1, z / radius)))), 5),
                    "altitude_km": round(radius - 6378.137, 2),
                    "velocity_km_s": round(math.sqrt(sum(component * component for component in velocity)), 3),
                })
            return points
        except Exception:
            pass
    period = float(orbit["period_minutes"] or 90)
    inclination = float(orbit["inclination_deg"] or 0)
    radius = float(orbit["altitude_km"] or 500)
    points: list[dict[str, Any]] = []
    period = float(orbit["period_minutes"] or 90)
    total_minutes = period * max(1, orbits) if orbits is not None else hours * 120
    sample_count = max(2, math.ceil(total_minutes / max(1, step_minutes)))
    if sample_count % 2:
        sample_count += 1
    offsets = (-total_minutes / 2 + total_minutes * index / sample_count for index in range(sample_count + 1))
    for minute in offsets:
        angle = float(item["_ground"]["phase"]) + 360.0 * minute / period
        longitude = ((float(item["_ground"]["base_longitude"]) + angle + 180) % 360) - 180
        latitude = max(-89.0, min(89.0, inclination * math.sin(math.radians(angle))))
        velocity = 2 * math.pi * (6378 + radius) / (period * 60) if radius < 50000 else 0.0
        points.append({
            "time": (now + timedelta(minutes=minute)).isoformat(),
            "longitude": round(longitude, 5),
            "latitude": round(latitude, 5),
            "altitude_km": round(radius, 2),
            "velocity_km_s": round(velocity, 3),
        })
    return points


def track(satellite_id: str, hours: float = 6, step_minutes: int = 2, at: str | None = None, orbits: int | None = None) -> dict[str, Any]:
    item = _find_satellite(satellite_id)
    if not item:
        return {}
    return {"id": item["id"], "name": item["name"], "points": build_track(item, hours, step_minutes, center_time=_parse_target_time(at), orbits=orbits), "source": item["orbit"]["source"]}


async def refresh_constellation_members() -> int:
    """同步星链和 OneWeb 的单星目录；轨道目录不可用时保留代表性种子条目。"""
    cache = _constellation_cache()
    updated = 0
    async with httpx.AsyncClient(timeout=45, follow_redirects=True, headers={"User-Agent": "QingchuanSatellite/1.0"}) as client:
        for parent_id, config in CONSTELLATION_GROUPS.items():
            try:
                response = await client.get(f"https://celestrak.org/NORAD/elements/gp.php?GROUP={config['group']}&FORMAT=JSON")
                if response.status_code != 200:
                    continue
                payload = response.json()
                if not isinstance(payload, list):
                    continue
                members: list[dict[str, Any]] = []
                for index, data in enumerate(payload[:200]):
                    if not isinstance(data, dict):
                        continue
                    try:
                        norad_id = int(data.get("NORAD_CAT_ID"))
                        mean_motion = float(data.get("MEAN_MOTION"))
                        inclination = float(data.get("INCLINATION") or 0)
                        eccentricity = float(data.get("ECCENTRICITY") or 0)
                        semi_major = (398600.4418 / ((2 * math.pi * mean_motion / 86400) ** 2)) ** (1 / 3)
                    except (TypeError, ValueError, ZeroDivisionError):
                        continue
                    member_id = f"{parent_id}:{norad_id}"
                    member = _satellite(
                        member_id,
                        str(data.get("OBJECT_NAME") or f"{config['group'].title()}-{norad_id}"),
                        next(item["category"] for item in SATELLITES if item["id"] == parent_id),
                        config["country"],
                        config["operator"],
                        config["purpose"],
                        f"{next(item['name'] for item in SATELLITES if item['id'] == parent_id)}的实时单星轨道条目。",
                        1440 / mean_motion,
                        inclination,
                        semi_major - 6378.137,
                        float(data.get("RA_OF_ASC_NODE") or 0) % 360 - 180,
                        float(data.get("MEAN_ANOMALY") or index * 11),
                        norad_id=norad_id,
                        cospar_id=str(data.get("OBJECT_ID") or ""),
                        orbit_class=next(item["orbit"]["orbit_class"] for item in SATELLITES if item["id"] == parent_id),
                        source_urls=next(item["sources"] for item in SATELLITES if item["id"] == parent_id),
                    )
                    member["parent_id"] = parent_id
                    member["is_constellation_member"] = True
                    member["orbit"].update({
                        "eccentricity": eccentricity,
                        "apogee_km": round(semi_major * (1 + eccentricity) - 6378.137, 2),
                        "perigee_km": round(semi_major * (1 - eccentricity) - 6378.137, 2),
                        "epoch": data.get("EPOCH", ""),
                        "source": "CelesTrak 星座 GP（实时同步）",
                    })
                    members.append(member)
                if members:
                    cache[parent_id] = {"updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "members": members}
                    updated += len(members)
            except Exception:
                continue
    if updated:
        path = constellation_cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)
    return updated


async def refresh_orbit_parameters() -> int:
    """从 CelesTrak 更新有 NORAD 编号条目的 OMM 和 TLE，失败时保留本地资料。"""
    targets = [item for item in SATELLITES if item.get("norad_id")]
    cache = _orbit_cache()
    semaphore = asyncio.Semaphore(4)

    async with httpx.AsyncClient(timeout=25, follow_redirects=True, headers={"User-Agent": "QingchuanSatellite/1.0"}) as client:
        async def fetch(item: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
            async with semaphore:
                try:
                    base = "https://celestrak.org/NORAD/elements/gp.php?CATNR=" + str(item["norad_id"])
                    omm = (await client.get(base + "&FORMAT=JSON")).json()
                    tle_text = (await client.get(base + "&FORMAT=TLE")).text.splitlines()
                    if not omm or len(tle_text) < 3:
                        return item["id"], None
                    data = omm[0]
                    mean_motion = float(data.get("MEAN_MOTION") or item["orbit"]["period_minutes"] and 1440 / item["orbit"]["period_minutes"])
                    period = 1440 / mean_motion if mean_motion else item["orbit"]["period_minutes"]
                    eccentricity = float(data.get("ECCENTRICITY") or 0)
                    semi_major = (398600.4418 / ((2 * math.pi * mean_motion / 86400) ** 2)) ** (1 / 3) if mean_motion else 6378 + item["orbit"]["altitude_km"]
                    value = {
                        "orbit": {
                            "period_minutes": round(period, 4),
                            "inclination_deg": float(data.get("INCLINATION") or item["orbit"]["inclination_deg"]),
                            "eccentricity": eccentricity,
                            "apogee_km": round(semi_major * (1 + eccentricity) - 6378.137, 2),
                            "perigee_km": round(semi_major * (1 - eccentricity) - 6378.137, 2),
                            "altitude_km": round(semi_major - 6378.137, 2),
                            "epoch": data.get("EPOCH", ""),
                            "source": "CelesTrak GP / TLE（实时同步）",
                        },
                        "tle": [tle_text[-2].strip(), tle_text[-1].strip()],
                        "synced_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    }
                    return item["id"], value
                except Exception:
                    return item["id"], None

        results = await asyncio.gather(*(fetch(item) for item in targets))
    updated = 0
    for satellite_id, value in results:
        if value:
            cache[satellite_id] = value
            updated += 1
    path = orbit_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    return updated


async def satellite_orbit_loop() -> None:
    while True:
        try:
            await refresh_constellation_members()
            await refresh_orbit_parameters()
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        await asyncio.sleep(6 * 3600)
