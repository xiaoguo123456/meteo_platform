# 晴川观象部署

生产服务器：腾讯云美国硅谷 `49.51.229.109`（2 核 3.6 GB，Ubuntu 24.04），部署账号 `ubuntu`（免密 sudo）。2026-10 起由原服务器 `192.236.166.152` 迁来：itdog 全国 300+ 节点实测，新服务器电信、联通、移动成功率均 95% 以上、1 MB 中位下载 0.4–0.7 秒；原服务器经 Cloudflare 时联通成功率仅 52%，直连时移动仅 43%。原服务器继续运行 Open-Meteo（站点预测与新能源态势使用），晴川观象不再部署到原服务器。

生产目录：`/opt/qingchuan`。Compose 文件：`deploy/compose.yml`，项目名 `qingchuan`。

- 主机 Nginx：`qingchuan.conf` 始终启用，80 端口（默认站点，含测试子域名与 IP 访问）与 8091 兼容入口提供 `/var/www/qingchuan` 静态页面并代理 `/api/` 到 `127.0.0.1:18001`；`meteo.weishenai.cn` 证书签发成功后再启用 `qingchuan-https.conf`（80→443 跳转与 HTTPS）。两份配置共用 `snippets/qingchuan-site.conf`。
- Open-Meteo：不在本机运行。`deploy/.env` 的 `OPEN_METEO_ORIGIN`（部署流程按 GitHub 变量写入）指向原服务器 `http://192.236.166.152:8090`；原服务器以 `DOCKER-USER` 链只放行本机 IP（规则已用 `netfilter-persistent` 持久化，备份在 `/etc/iptables/rules.v4.backup-*`）。
- 后端 FastAPI：Docker 内运行，绑定宿主机 `127.0.0.1:18001`，不直接暴露公网；单进程内启动后台预取。
- 前端不再运行独立 Docker 容器，部署流程在构建机生成 `frontend/dist` 后复制到主机 Nginx 目录。
- 数据目录：`/opt/qingchuan/data/forecasts`，挂载到后端 `/data/forecasts`。
- 后端 CPU 上限 1.8 核、内存 1800 MiB（原服务器为 1.25 核、1200 MiB；新服务器不跑 Open-Meteo，首次同步时 1.25 核即顶满而网卡只有约 8 Mbit/s，瓶颈在 CPU）。日志每服务最多 3×10 MB，自动重启与健康检查开启。主机 Nginx 由 systemd 管理。

## 缓存预取

默认全模型共用 4 路并发（并发上限 4），按模型轮流提交近时效预报，256 KiB S3 分块；每个时刻独立临时目录，失败最多重试一次，成功后删除原始分块。NPZ 采用一级无损压缩，浏览器数据块提前生成。批次失败保持错误可见，30 秒后继续；正常每 300 秒检查最新起报。四模型分别追踪最新起报；单模型失败不阻断其他模型。未完成批次也会每 300 秒重新读取最新清单，避免一直追旧批次。

新起报的全部预报时刻、浏览器数据块及省平均统计（见 [首页功能](home.md)）缓存完成后，才原子替换对外清单 `status.json`。缓存期间继续提供上一批次；后台进度和错误记录在 `status.pending.json`，新批次失败不撤下旧数据。首次启动没有旧批次时，只显示缓存进度，不发布半成品时间轴。每个已发布批次保存 `published.json`，保留最近两个已发布批次，固定起报请求可继续读取上一批次，避免时间轴轮询与批次切换之间的在途请求失败。用户请求只读取本地缓存。

`/api/models/{model}/runs` 浏览器不缓存（前端以 `no-store` 请求，绕过 Cloudflare 规则改写的 4 小时浏览器缓存），Cloudflare 边缘缓存 5 秒、过期后 30 秒内先返回旧清单并后台刷新（`Cloudflare-CDN-Cache-Control: max-age=5, stale-while-revalidate=30`），前端每 10 秒轮询大多在边缘返回；批次失效时带随机参数绕过缓存。批次切换时暂停播放、重置时间轴，并保留旧画面与真实起报标记，直到完整新帧到达。长时间停留导致所选批次已被清理时，前端主动重读清单并重试；同一失效批次最多立即刷新一次，之后跟随轮询重试，避免请求循环。

上线模型为 GFS、IFS、AIFS（0.25°）和 GRAPES（原生 0.125°，纬度格心 -89.9375° 起）。GFS 使用 80m 风、1000hPa 温度/湿度、海平面气压；其当前空间数据没有降水。另三个模型使用 10m 风、2m 温度/湿度、海平面气压、时段降水和总云量。GFS 空间数据只有 1000hPa 层云量、不是总云量，不提供云量图层。新增要素时升级浏览器数据块齐备标记（当前 `wire-v5`），已缓存批次由后台从本地 NPZ 补生成新要素的数据块，补齐前继续提供原批次。降水第 0 时效缺失时不补零，时间轴只列出该要素实际可用的时刻。卫星云图未接入本项目首页。所有数据来自 S3，不依赖现有 Open-Meteo API。

## 运维

```bash
cd /opt/qingchuan
docker compose -f deploy/compose.yml ps
docker compose -f deploy/compose.yml logs --tail 100 backend
docker compose -f deploy/compose.yml up -d --build
nginx -t
systemctl status nginx --no-pager
certbot certificates
curl http://127.0.0.1:8091/api/health
curl http://127.0.0.1:8091/api/models/gfs/runs
```

停止本项目：`docker compose -f deploy/compose.yml stop`，再按需停止主机 Nginx。只影响 qingchuan 项目，不操作 open-meteo 项目。不执行全局 prune 或删除业务数据卷。

当前正式入口为 `https://meteo.weishenai.cn`，证书由 Certbot 自动申请并由主机 Nginx 终止 HTTPS；IP:8091 仅作为迁移兼容入口。源代码更新通过构建机生成静态文件和后端镜像生效；不把开发服务器部署到生产。

## 多模型核验

IFS/AIFS 为 1440×721，GRAPES 为 2880×1440，不将 GRAPES 经纬度误套为包含两极的 GFS 网格。空间定义依据 [ECMWF Domain](https://github.com/open-meteo/open-meteo/blob/main/Sources/App/Ecmwf/EcmwfDomain.swift) 和 [CMA Domain](https://github.com/open-meteo/open-meteo/blob/main/Sources/App/CMA/CmaDomain.swift)，并逐模型读取 S3 文件检查形状和变量有效值。模型预报长度和时间间隔以 latest.json 为准，不写死 5 天或 15 天。

## 底图与交互

Esri World Imagery 官方全球影像（4096×2048，EPSG:4326）先由后端下载到 `/data/basemap/world-imagery-4096x2048.jpg`，服务启动时后台预热；文件缓存默认保留 30 天，前端通过 `/api/basemap/world-imagery` 获取并使用浏览器 HTTP 缓存。这样同一台服务器上的多个浏览器不再各自直连 Esri 重复下载，同时保留服务方署名。气象数据仍只来自本地 S3 预缓存。旋转、缩放与切换保留上一帧，Worker 完成重投影后整体替换，不再填充蓝色占位。首次底图下载仍受服务器到 Esri 的公网速度影响，缓存命中后直接从本机读取；底图网络失败会在页面明确提示。

## 预报切换响应优化

S3 预缓存增加 `.v2.gz` 浏览器响应文件：保留原始浮点值的字典编码、标量单通道、提前 gzip 压缩。接口使用 FileResponse 直接发送，避免事件循环执行压缩。旧 NPZ 会在后台补生成响应，首次命中尚未补齐的文件时按需生成一次。压缩阶段最多一路，与四路下载共享单机资源；响应文件随模型批次统一清理，会增加磁盘使用量。

前端请求带固定起报、有效时刻及 `format=packed`；成功响应允许浏览器长期缓存。前端已解码帧按 128 MiB 预算淘汰，当前请求优先，取消过时下载，仅在当前画面就绪后空闲预取下一帧。旧 raw 接口保留兼容。首次下载仍受公网速度和全球网格体积限制。

## 按视野分块版本

当前前端使用 `/api/tiles`，128×128 原始数值块按视野流式传输，后台预生成 `.v3.blocks` 和 `.v3.json`；保留旧接口兼容。当前最多 8 帧动画先缓冲后连续循环。设计、来源和适用边界见 [风场渲染与数据分块](rendering.md)。旧 `.v2.gz` 随整个批次保留策略清理，不操作 Open-Meteo 数据卷。
## GitHub Actions 自动部署

仓库的 `main` 分支每次推送后会触发 `.github/workflows/deploy.yml`。Actions 只更新 `/opt/qingchuan` 下的晴川观象服务，执行 `deploy/compose.yml`，不会操作独立的 Open-Meteo Compose 项目。

在 GitHub 仓库的 **Settings → Secrets and variables → Actions** 中配置以下 Secrets：

| Secret | 值 |
|---|---|
| `DEPLOY_HOST` | `49.51.229.109` |
| `DEPLOY_USER` | `ubuntu` |
| `DEPLOY_PORT` | `22` |
| `DEPLOY_PATH` | `/opt/qingchuan` |
| `DEPLOY_SSH_KEY` | 服务器端 `~/.ssh/meteo-github-actions` 对应的完整私钥内容 |

另设置 `OPEN_METEO_ORIGIN` = `http://192.236.166.152:8090`（Variables 或 Secrets 均可）。远端命令以 `sudo` 执行，部署账号需要免密 sudo。公钥需要提前加入服务器 `~ubuntu/.ssh/authorized_keys`。私钥只进入 GitHub Actions Secret，不提交到仓库。部署包会排除 `backend/.env.news`、`data`、本地虚拟环境和构建产物，服务器上已有的模型缓存、资讯数据库和模型密钥会保留。

打包前流程把本次提交哈希、提交时间和构建时间写入 `backend/app/build_info.json`（不入库），部署后访问 `https://meteo.weishenai.cn/api/version` 即可核对线上运行的代码版本；本地开发没有该文件时直接读取 git，`dirty` 表示有未提交改动。

证书签发失败（如正式域名还未解析到本机）不会中断部署，此时只提供 HTTP；解析切到本机后，下一次部署会自动签发并启用 HTTPS。部署完成后流程会等待 `http://127.0.0.1:8091/api/health` 返回成功，并输出后端和资讯 Worker 容器状态。主机 Nginx 和 Certbot 续期由 systemd 管理；证书续期后自动 reload Nginx。Open-Meteo 服务使用独立 Compose 项目，不会被这条流程重启。

## 国内访问慢的应对

国内访问经 Cloudflare 洛杉矶节点回源美国服务器，实测服务器内部请求为毫秒级，而外部请求 1–7 秒不等、偶发 40 秒以上超时，瓶颈在跨境线路而非服务器。前端据此做了抗慢网络处理（`frontend/src/net.ts`）：

- JSON 请求每次限时 12 秒，网络类失败（超时、连接断开、408/429/5xx 网关与 Cloudflare 520–524）按 0.8 秒、2.5 秒退避重试；后端业务错误（503 + detail）不重试。
- 预报数据块流式下载 20 秒无新数据视为卡住，中止后只补请求尚未到达的数据块，网络类失败最多重试两次。
- 已有画面时，起报清单、省平均或某一帧因网络慢失败只在左上角给出温和提示并自动重试，不弹红色错误、不清空画面；单点面板失败给出"重试"按钮。

根本改善需要更近的线路：香港/日本服务器，或在 ICP 备案后使用国内 CDN。数据块（`/api/tiles/*`，URL 含批次与时刻、内容不变）、`/api/provinces/shapes`、`/api/province-map/*` 目前未被 Cloudflare 缓存（`cf-cache-status: DYNAMIC`），可在 Cloudflare 缓存规则中设为可缓存并遵循源站缓存头，重复访问即可在边缘返回。
