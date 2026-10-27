# 卫星

两个入口：`/#observation` 葵花卫星观测，`/#satellite` 卫星轨迹。

## 卫星观测

数据为 JMA 葵花 9 号，默认真彩色（REP/ETC），可切换红外 B13（B13/TBB）。两种产品各自维护时间轴、缓存和错误状态；真彩色夜间无图。

- 服务器每 5 分钟检查上游，先发布两种产品的最新帧，再补齐各自最近 36 帧（磁盘多留 2 帧）。瓦片下载共享 8 路并发，拼接完整后原子发布。
- 全圆盘正常有 48 块瓦片，不足 48 块说明 JMA 还在上传，该时刻跳过、下轮再取，不发布缺块帧。
- 原生 zoom 3 的 256 像素瓦片拼成 2048×2048 透明纹理。原图存无损 WebP；显示用另存一份 quality=90 的 WebP。
- 前端：首页延迟 3 秒预热最新真彩色和红外；卫星面板预取后续 3 帧，最多缓存 8 帧（约 128 MiB）；切换时保留上一张图直到新图加载完成。

接口：

- `/api/satellite/himawari/latest?product=truecolor|infrared`
- `/api/satellite/himawari/images/{product}/{time}.display.webp`
- `/api/satellite/himawari/station/{station_id}?product=truecolor`：场站周边 zoom 5 局部拼图，取已发布的最新帧，缺块时依次退回前两帧；进程内最多缓存 200 份，浏览器缓存 60 秒。

来源：[JMA 卫星地图](https://www.jma.go.jp/bosai/map.html)、[真彩色产品说明](https://ds.data.jma.go.jp/mscweb/data/himawari/index.html)。

## 卫星轨迹

- 卫星和星座目录，按类型、名称筛选；Starlink、OneWeb 可展开为单星列表。
- 选中卫星显示 1、3 或 5 圈轨道，可指定定位时间；只显示可见半球，背面轨道隐藏。
- 资料卡：轨道类别、周期、倾角、高度、运营方、发射时间、任务简介和来源链接。

接口：

```text
GET /api/satellites?category=weather&keyword=风云&limit=80
GET /api/satellites/categories
GET /api/satellites/{id}/members?limit=80
GET /api/satellites/{id}?at=2026-10-15T08:30:00Z&orbits=3
GET /api/satellites/{id}/track?hours=4&step_minutes=10&at=2026-10-15T08:30:00Z&orbits=3
```

- 目录在 `backend/app/satellite_catalog.py`：`SATELLITES` 每条含 `orbit`、`sources`、`ai`；新增类型改 `CATEGORIES`。
- 后端每 6 小时从 CelesTrak 同步有 NORAD 编号条目的 OMM/TLE，以及 Starlink、OneWeb 单星目录。装了 `sgp4` 时用 SGP4 计算真实轨迹，否则用目录参数生成轨迹；`orbit.source` 标明是哪种。

### 大模型资料整理

```bash
PYTHONPATH=backend python -m app.satellite_ai --limit 8
```

沿用资讯模块的 `NEWS_LLM_URL`、`NEWS_LLM_KEY`、`NEWS_LLM_MODEL`，结果写入 `data/satellite_ai.json`。模型只根据名称、轨道目录和已核验来源写摘要，没有可靠来源时显示「公开资料不足」。点击卫星时只读缓存。
