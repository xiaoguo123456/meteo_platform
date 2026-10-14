# 站点预测

首页导航新增“站点预测”栏目，功能取自 EnerSight 小程序的核心信息架构，收敛为公开站点目录、模型切换、当前气象、功率预测曲线和未来 7 天概览。

## 数据链路

浏览器只访问晴川观象后端的三个接口：

- `GET /api/site-stations`：公开站点目录；
- `GET /api/site-forecast?station_id=...&model=gfs`：站点天气与功率预测。
- `GET /api/site-satellite?station_id=...`：光伏站点的葵花卫星 10 分钟辐射附加数据，独立加载。

后端通过 `METEO_OPEN_METEO_BASE_URL` 访问同一台服务器上的自部署 Open-Meteo。生产环境由 `deploy/compose.yml` 将 `host.docker.internal` 映射到宿主机，默认地址为 `http://host.docker.internal:8090/v1/forecast`，不会影响已有 Open-Meteo 容器。

功率、装机容量和七天峰值在界面统一以 MW / MWh 展示；曲线支持点击和悬停，选中后同步显示该时刻的功率和风速或辐射。光伏站点额外请求本机 `/v1/archive?models=jma_jaxa_himawari&temporal_resolution=native`，展示葵花卫星反演辐射与模型辐射的同口径对比，并在场站云图上标出站点位置。真彩色为白天默认图层，夜间自动使用红外图层以避免可见光空白。

支持的模型参数为 `gfs`、`grapes`、`ifs`、`aifs`，分别映射到 Open-Meteo 的全球 GFS、CMA GRAPES、ECMWF IFS 和 AIFS 模型。功率曲线使用站点类型、装机容量和气象要素做统一的展示估算；接入实际场站功率曲线时，只需替换后端 `site_forecast.py` 的 `_power` 适配函数。

## 响应式处理

桌面端使用左侧站点目录和右侧预测内容，窄屏改为上下布局；资讯政策预览增加自适应容器和横向滚动保护，避免官方固定宽度页面撑破详情弹窗。
