# 卫星

## 卫星观测

默认使用 JMA 葵花 9 号真彩色再现产品（REP/ETC），可切换红外 B13（B13/TBB）。两种产品独立维护观测时间轴、缓存与错误状态；不以红外替代真彩色。真彩色受日照影响。

服务器每五分钟检查上游，优先发布两种产品的最新帧，再补齐各自最近 36 帧。瓦片下载共享 8 路并发，完整拼接后原子发布。每种产品失败独立显示错误。全圆盘正常有 48 块瓦片（其余在圆盘外），不足 48 块视为 JMA 仍在上传：该时刻跳过、下一轮再取，不发布缺块帧，也不因最新帧未就绪而报错或中断补历史；只有一帧都没有时才提示原因。清单列出 36 帧，磁盘多保留 2 帧，前端清单晚到时旧时刻仍可读取。原生 zoom 3 的 256 像素瓦片拼成 2048×2048 透明纹理，不降低分辨率。

原图缓存使用无损 WebP，避免 PNG 重复 gzip。实测红外样本由 1,109,862 字节降至 616,774 字节，减少约 44%；可见像素保持一致。实际压缩率随产品、时刻变化。

首页延迟三秒预热最新真彩色，再预热红外，并复用三十秒内的观测清单；卫星面板预取后续三帧，在末帧时预取播放起点，并准备同一时刻另一种产品。浏览器最多保留八帧解码缓存，约 128 MiB；文件 URL 带产品和观测时间，可长期缓存。切换保留上一张图，底部标注实际显示的产品和观测时间，加载成功后一起替换。

显示链路另生成 quality=90 的 WebP，保留 2048×2048 分辨率，存在轻微有损压缩；实测真彩色 1,325,728 → 374,388 字节，红外 614,702 → 213,740 字节。无损原图仍留在服务器。

接口：

- `/api/satellite/himawari/latest?product=truecolor`（默认）
- `/api/satellite/himawari/latest?product=infrared`
- `/api/satellite/himawari/images/{product}/{time}.display.webp`
- `/api/satellite/himawari/station/{station_id}?product=truecolor`：场站周边 zoom 5 局部拼图。时刻取全球缓存已完整发布的最新帧（无缓存时才读 JMA 清单）；局部瓦片缺块时依次退回前两帧，圆盘边缘站点取块数最多的一帧。进程内按最近使用最多缓存 200 份，最新时刻的结果直接复用，退回旧帧的结果只复用 60 秒；浏览器缓存 60 秒。

来源：[JMA 官方卫星地图](https://www.jma.go.jp/bosai/map.html)、[真彩色产品说明](https://ds.data.jma.go.jp/mscweb/data/himawari/index.html)。首次加载仍受服务器到用户的网络速度影响，预热命中不能视为冷启动速度保证。

线上验证：服务器本机读取 374,388 字节显示图耗时约 11 毫秒；当前本地到服务器网络测试存在明显波动，冷下载约 5–16 秒。因此预热用于减少交互等待，尚不能保证未经预热的首次访问在一秒内完成。原 Open-Meteo 容器未重启。

## 卫星轨迹

卫星栏目分为两个独立入口：`/#observation` 为葵花卫星观测，`/#satellite` 为卫星轨迹。导航顺序中卫星轨迹位于站点预测之前。

卫星轨迹第一版包含：

- 代表性卫星和星座目录，支持按类型、名称筛选；
- 轨道位置、当前选中卫星的多圈轨道线和地球视图点击选择；
- 支持输入定位时间，并选择显示 1、3 或 5 圈轨道；
- Starlink、OneWeb 等星座可展开为单星列表，选择单星后只绘制该单星轨迹；
- 轨道类别、周期、倾角、高度、运营方、发射时间和任务简介；
- 资料来源链接和大模型整理字段；
- 葵花观测独立使用真彩色、红外观测时间轴；卫星轨迹不再与葵花观测共用栏目，地球视图继续使用 Esri 影像底图。

### 接口

```text
GET /api/satellites?category=weather&keyword=风云&limit=80
GET /api/satellites/categories
GET /api/satellites/{id}/members?limit=80
GET /api/satellites/{id}?at=2026-10-15T08:30:00Z&orbits=3
GET /api/satellites/{id}/track?hours=4&step_minutes=10&at=2026-10-15T08:30:00Z&orbits=3
```

`backend/app/satellite_catalog.py` 中的 `SATELLITES` 是可扩展种子目录。每个条目都包含 `orbit`、`sources` 和 `ai` 三部分，后续同步 CelesTrak/Space-Track 的 OMM 或 TLE 时，只替换轨道字段即可，不需要修改前端。

当前轨迹接口使用目录参数生成稳定的可视化轨迹，接口格式已经固定为时间、经度、纬度、高度和速度。接入真实 OMM/TLE 后，前端仍使用同一格式。

### 大模型资料整理

`ai` 字段用于保存批量资料整理结果：

```json
{
  "state": "pending|ready|error|seeded",
  "summary": "基于公开资料的任务简介",
  "points": [],
  "confidence": "基础资料",
  "model": null,
  "updated_at": null
}
```

模型只根据卫星名称、轨道目录和已核验来源生成摘要，原始来源链接始终保留；没有可靠来源时显示“公开资料不足”，不让模型补写事实。模型整理应在后台批量执行，点击卫星时只读取缓存。

批量整理入口：

```bash
PYTHONPATH=backend python -m app.satellite_ai --limit 8
```

该命令沿用资讯模块的 `NEWS_LLM_URL`、`NEWS_LLM_KEY` 和 `NEWS_LLM_MODEL`，结果写入 `data/satellite_ai.json`。密钥只在后端环境中读取，不进入浏览器。

### 后续扩展

分类配置已经覆盖气象、遥感、海洋、通信、低轨互联网、导航、空间科学、空间天气、测绘与地球物理、载人、搜救与中继、技术验证、教育与业余无线电、安全与侦察、轨道目标等类型。新增卫星或星座只增加目录条目，新增类型只增加 `CATEGORIES` 配置。

后端启动后会每 6 小时从 CelesTrak 更新有 NORAD 编号条目的 OMM 和 TLE，并同步 Starlink、OneWeb 的单星目录。安装 `sgp4` 后，轨迹使用真实 SGP4 传播，并以定位时刻的地球姿态生成闭合轨道投影；上游或依赖暂不可用时保留目录参数轨迹，并在接口的 `orbit.source` 中区分同步状态。轨道线支持按圈数采样，前端只显示当前可见半球，地球背面的轨道完全隐藏。
