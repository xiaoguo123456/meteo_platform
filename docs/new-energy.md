# 新能源

站点预测和新能源态势的天气数据来自自部署 Open-Meteo（地址见 [部署](deployment.md) 的 `OPEN_METEO_ORIGIN`）。模型参数 `gfs`、`grapes`、`ifs`、`aifs` 分别对应 Open-Meteo 的 GFS、CMA GRAPES、ECMWF IFS 和 AIFS。

## 站点预测

公开站点目录、模型切换、当前气象、功率预测曲线和未来 7 天概览。功率、装机容量、峰值统一用 MW / MWh。

- `GET /api/site-stations`：站点目录。
- `GET /api/site-forecast?station_id=&model=gfs`：站点天气与功率预测。
- `GET /api/site-satellite?station_id=`：光伏站点的葵花卫星反演辐射（Open-Meteo `/v1/archive?models=jma_jaxa_himawari`），与模型辐射对比，独立加载。场站云图白天用真彩色、夜间用红外。

功率是按站点类型、装机容量和气象要素做的估算；接入真实场站功率曲线时，替换 `backend/app/site_forecast.py` 里的 `_power`。

## 新能源态势

把全部 17,842 个场站的四模型功率预报聚合到一条时间轴，给出出力区间、模型一致性和短时爬坡。

- **区域排名**：按真实省界落点，分西北、华北、东北、华东、华中、华南、西南给出 P50 出力和爬坡值，点击联动详情。
- **全国功率**：P10 / P50 / P90 对应四个模型的下界、中心值、上界，未来 24 小时。
- **爬坡预警**：未来 6 小时内功率变化超过装机容量 8%（最低 1 MW）。
- **地图**：分「底图、站点密度、省界、重点站点」四层；全量站点只传坐标、类型和容量，前端做六边形密度聚合，不逐站请求模型。

接口：

- `GET /api/power-outlook?hours=24`：`hours` 6–48。返回 `totals`、`station_count`、`regions`、`alerts`、`errors`（单模型失败时降级，其余模型照常计算）。后端按省汇总容量，以容量加权省中心批量请求各模型，结果缓存 5 分钟。
- `GET /api/power-outlook/stations`：全量站点坐标索引。
- `GET /api/basemap/china-street`：后端缓存的 Esri World Street Map 中国底图（EPSG:3857），保留 Esri 署名。

「模型一致性」是四模型功率区间相对装机容量的反向评分，只反映预报分歧，不代表实际准确率。
