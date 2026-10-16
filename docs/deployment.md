# 晴川观象部署

生产目录：`/opt/qingchuan`。Compose 文件：`deploy/compose.yml`，项目名 `qingchuan`。

- 主机 Nginx：监听宿主机 8091，提供 `/var/www/qingchuan` 静态页面并代理 `/api/` 到 `127.0.0.1:8000`。
- 后端 FastAPI：Docker 内运行，绑定宿主机 `127.0.0.1:8000`，不直接暴露公网；单进程内启动后台预取。
- 前端不再运行独立 Docker 容器，部署流程在构建机生成 `frontend/dist` 后复制到主机 Nginx 目录。
- 数据目录：`/opt/qingchuan/data/forecasts`，挂载到后端 `/data/forecasts`。
- 与既有 `/opt/open-meteo`、8090 端口和 Open-Meteo 数据卷独立。
- 后端 CPU 上限 1.25 核、内存 1200 MiB。日志每服务最多 3×10 MB，自动重启与健康检查开启。主机 Nginx 由 systemd 管理。

## 缓存预取

默认全模型共用 4 路并发（并发上限 4），按模型轮流提交近时效预报，256 KiB S3 分块；每个时刻独立临时目录，失败最多重试一次，成功后删除原始分块。仅保留一级无损压缩的 NPZ 数据，降低 CPU 开销。批次失败保持错误可见，30 秒后继续；正常每 300 秒检查最新起报。完整同步后每个模型保留最近两个批次。四模型分别追踪最新起报；单模型失败不阻断其他模型。每个时刻原子写入 NPZ 和要素元数据，只发布连续完成的时间前缀；用户操作只读取本地缓存。未完成批次也会每 300 秒重新读取最新清单，避免一直追旧批次。

上线模型为 GFS、IFS、AIFS（0.25°）和 GRAPES（原生 0.125°，纬度格心 -89.9375° 起）。GFS 使用 80m 风、1000hPa 温度/湿度、海平面气压；其当前空间数据没有降水。另三个模型使用 10m 风、2m 温度/湿度、海平面气压和时段降水。降水第 0 时效缺失时不补零，时间轴只列出该要素实际可用的时刻。卫星云图未接入本项目首页。所有数据来自 S3，不依赖现有 Open-Meteo API。

## 运维

```bash
cd /opt/qingchuan
docker compose -f deploy/compose.yml ps
docker compose -f deploy/compose.yml logs --tail 100 backend
docker compose -f deploy/compose.yml up -d --build
nginx -t
systemctl status nginx --no-pager
curl http://127.0.0.1:8091/api/health
curl http://127.0.0.1:8091/api/models/gfs/runs
```

停止本项目：`docker compose -f deploy/compose.yml stop`，再按需停止主机 Nginx。只影响 qingchuan 项目，不操作 open-meteo 项目。不执行全局 prune 或删除业务数据卷。

当前入口使用 IP 和 HTTP，未配置域名及 HTTPS。域名接入时，在主机 Nginx 的 `deploy/nginx/qingchuan.conf` 中增加域名并由主机 Nginx 终止 HTTPS。源代码更新通过构建机生成静态文件和后端镜像生效；不把开发服务器部署到生产。

## 多模型核验

IFS/AIFS 为 1440×721，GRAPES 为 2880×1440，不将 GRAPES 经纬度误套为包含两极的 GFS 网格。空间定义依据 [ECMWF Domain](https://github.com/open-meteo/open-meteo/blob/main/Sources/App/Ecmwf/EcmwfDomain.swift) 和 [CMA Domain](https://github.com/open-meteo/open-meteo/blob/main/Sources/App/CMA/CmaDomain.swift)，并逐模型读取 S3 文件检查形状和变量有效值。模型预报长度和时间间隔以 latest.json 为准，不写死 5 天或 15 天。

## 底图与交互

Esri World Imagery 官方全球影像（4096×2048，EPSG:4326）先由后端下载到 `/data/basemap/world-imagery-4096x2048.jpg`，服务启动时后台预热；文件缓存默认保留 30 天，前端通过 `/api/basemap/world-imagery` 获取并使用浏览器 HTTP 缓存。这样同一台服务器上的多个浏览器不再各自直连 Esri 重复下载，同时保留服务方署名。气象数据仍只来自本地 S3 预缓存。旋转、缩放与切换保留上一帧，Worker 完成重投影后整体替换，不再填充蓝色占位。首次底图下载仍受服务器到 Esri 的公网速度影响，缓存命中后直接从本机读取；底图网络失败会在页面明确提示。

## 预报切换响应优化

S3 预缓存增加 `.v2.gz` 浏览器响应文件：保留原始浮点值的字典编码、标量单通道、提前 gzip 压缩。接口使用 FileResponse 直接发送，避免事件循环执行压缩。旧 NPZ 会在后台补生成响应，首次命中尚未补齐的文件时按需生成一次。压缩阶段最多一路，与四路下载共享单机资源；响应文件随模型批次统一清理，会增加磁盘使用量。

前端请求带固定起报、有效时刻及 `format=packed`；成功响应允许浏览器长期缓存。前端已解码帧按 128 MiB 预算淘汰，当前请求优先，取消过时下载，仅在当前画面就绪后空闲预取下一帧。旧 raw 接口保留兼容。首次下载仍受公网速度和全球网格体积限制。

## 按视野分块版本

当前前端使用 `/api/tiles`，128×128 原始数值块按视野流式传输，后台预生成 `.v3.blocks` 和 `.v3.json`；保留旧接口兼容。当前最多 8 帧动画先缓冲后连续循环。设计、来源和适用边界见 `viewport-streaming.md`。旧 `.v2.gz` 随整个批次保留策略清理，不操作 Open-Meteo 数据卷。
## GitHub Actions 自动部署

仓库的 `main` 分支每次推送后会触发 `.github/workflows/deploy.yml`。Actions 只更新 `/opt/qingchuan` 下的晴川观象服务，执行 `deploy/compose.yml`，不会操作独立的 Open-Meteo Compose 项目。

在 GitHub 仓库的 **Settings → Secrets and variables → Actions** 中配置以下 Secrets：

| Secret | 值 |
|---|---|
| `DEPLOY_HOST` | `192.236.166.152` |
| `DEPLOY_USER` | `root` |
| `DEPLOY_PORT` | `22` |
| `DEPLOY_PATH` | `/opt/qingchuan` |
| `DEPLOY_SSH_KEY` | 服务器端 `~/.ssh/meteo-github-actions` 对应的完整私钥内容 |

公钥需要提前加入服务器 `/root/.ssh/authorized_keys`。私钥只进入 GitHub Actions Secret，不提交到仓库。部署包会排除 `backend/.env.news`、`data`、本地虚拟环境和构建产物，服务器上已有的模型缓存、资讯数据库和模型密钥会保留。

部署完成后流程会等待 `http://127.0.0.1:8091/api/health` 返回成功，并输出后端和资讯 Worker 容器状态。主机 Nginx 由 systemd 管理。Open-Meteo 服务使用独立 Compose 项目，不会被这条流程重启。
