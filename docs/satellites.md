# 卫星轨迹

卫星栏目分为两个独立入口：`/#observation` 为葵花卫星观测，`/#satellite` 为卫星轨迹。导航顺序中卫星轨迹位于站点预测之前。

卫星轨迹第一版包含：

- 代表性卫星和星座目录，支持按类型、名称筛选；
- 轨道位置、轨迹线和地球视图点击选择；
- 轨道类别、周期、倾角、高度、运营方、发射时间和任务简介；
- 资料来源链接和大模型整理字段；
- 葵花观测独立使用真彩色、红外观测时间轴；卫星轨迹不再与葵花观测共用栏目，地球视图继续使用 Esri 影像底图。

## 接口

```text
GET /api/satellites?category=weather&keyword=风云&limit=80
GET /api/satellites/categories
GET /api/satellites/{id}
GET /api/satellites/{id}/track?hours=4&step_minutes=10
```

`backend/app/satellite_catalog.py` 中的 `SATELLITES` 是可扩展种子目录。每个条目都包含 `orbit`、`sources` 和 `ai` 三部分，后续同步 CelesTrak/Space-Track 的 OMM 或 TLE 时，只替换轨道字段即可，不需要修改前端。

当前轨迹接口使用目录参数生成稳定的可视化轨迹，接口格式已经固定为时间、经度、纬度、高度和速度。接入真实 OMM/TLE 后，前端仍使用同一格式。

## 大模型资料整理

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

## 后续扩展

分类配置已经覆盖气象、遥感、海洋、通信、低轨互联网、导航、空间科学、空间天气、测绘与地球物理、载人、搜救与中继、技术验证、教育与业余无线电、安全与侦察、轨道目标等类型。新增卫星或星座只增加目录条目，新增类型只增加 `CATEGORIES` 配置。

后端启动后会每 6 小时从 CelesTrak 更新有 NORAD 编号条目的 OMM 和 TLE。安装 `sgp4` 后，轨迹使用真实 SGP4 传播；上游或依赖暂不可用时保留目录参数轨迹，并在接口的 `orbit.source` 中区分同步状态。
