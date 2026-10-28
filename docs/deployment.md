# 部署

## 服务器

- 生产服务器：腾讯云美国硅谷 `49.51.229.109`（2 核 3.6 GB，Ubuntu 24.04），部署账号 `ubuntu`（免密 sudo）。
- 正式入口：`https://meteo.weishenai.cn`；IP:8091 为兼容入口。
- 生产目录：`/opt/qingchuan`，Compose 文件 `deploy/compose.yml`，项目名 `qingchuan`。

组成：

- 主机 Nginx：`qingchuan.conf` 常驻，80 端口与 8091 提供 `/var/www/qingchuan` 静态页面，并把 `/api/` 代理到 `127.0.0.1:18001`；证书签发成功后启用 `qingchuan-https.conf`（80→443 与 HTTPS）。两份配置共用 `snippets/qingchuan-site.conf`。Nginx 与 Certbot 续期由 systemd 管理。
- 后端 FastAPI：Docker 内运行，绑定 `127.0.0.1:18001`，单进程内运行后台预取。CPU 上限 1.8 核、内存 1800 MiB。
- 资讯 Worker：独立容器 `news-worker`，见 [资讯](news.md)。
- 前端：构建机生成 `frontend/dist` 后复制到 Nginx 目录，没有前端容器。
- 数据：`/opt/qingchuan/data/forecasts` 挂载到后端 `/data/forecasts`。
- Open-Meteo：不在本机，跑在原服务器 `192.236.166.152:8090`（站点预测、新能源态势使用）。`deploy/.env` 的 `OPEN_METEO_ORIGIN` 指向它；原服务器用 `DOCKER-USER` 链只放行本机 IP（已用 `netfilter-persistent` 持久化）。

## GitHub Actions 自动部署

推送 `main` 触发 `.github/workflows/deploy.yml`，只更新 `/opt/qingchuan` 下的服务，不碰 Open-Meteo。

在 **Settings → Secrets and variables → Actions** 配置：

| Secret | 值 |
|---|---|
| `DEPLOY_HOST` | `49.51.229.109` |
| `DEPLOY_USER` | `ubuntu` |
| `DEPLOY_PORT` | `22` |
| `DEPLOY_PATH` | `/opt/qingchuan` |
| `DEPLOY_SSH_KEY` | 服务器 `~/.ssh/meteo-github-actions` 对应的私钥 |

另设 `OPEN_METEO_ORIGIN` = `http://192.236.166.152:8090`（Variables 或 Secrets 均可）。公钥需加入服务器 `~ubuntu/.ssh/authorized_keys`。

- 部署包排除 `backend/.env.news`、`data`、虚拟环境和构建产物，服务器上的缓存、资讯数据库和密钥会保留。
- 打包时写入 `backend/app/build_info.json`（提交哈希、提交时间、构建时间，不入库），访问 `/api/version` 可核对线上版本；本地没有该文件时读 git，`dirty` 表示有未提交改动。
- 证书签发失败不中断部署，只提供 HTTP，域名解析到本机后下次部署自动签发。
- 部署结束等待 `http://127.0.0.1:8091/api/health` 成功，并输出容器状态。

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

停止：`docker compose -f deploy/compose.yml stop`。不要执行全局 prune，也不要删业务数据卷。

## 预报缓存

- 数据全部来自 Open-Meteo S3，用户请求只读本地缓存，不触发下载。
- 每 300 秒检查各模型最新起报，失败 30 秒后重试。全模型共用 4 路下载并发，按模型轮流优先下载近时效，256 KiB 分块，每个时刻失败最多重试一次，成功后删除原始分块，只留 NPZ。单模型失败不影响其他模型。
- 一个批次的全部时刻、浏览器数据块（见 [渲染](rendering.md)）和省平均（见 [首页功能](home.md)）都完成后，才原子替换对外清单 `status.json`；期间继续提供上一批次，进度和错误写在 `status.pending.json`。首次启动没有旧批次时只显示进度。
- 保留最近两个已发布批次，保证切换时在途请求不失败。
- 新增要素时升级数据块标记（当前 `wire-v5`），后台从本地 NPZ 补生成，补齐前继续提供原批次。
- 可配置：`WEATHER_FORECAST_CACHE`（默认 `data/cache/forecasts`）、`WEATHER_POLL_SECONDS`（默认 300）。

模型与要素：

| 模型 | 网格 | 风 | 温湿 | 降水 / 云量 |
|---|---|---|---|---|
| GFS | 0.25°（1440×721） | 80m | 1000hPa | 无 |
| IFS、AIFS | 0.25°（1440×721） | 10m | 2m | 时段降水、总云量 |
| GRAPES | 0.125°（2880×1440，纬度格心 -89.9375° 起） | 10m | 2m | 时段降水、总云量 |

各模型都有海平面气压。预报长度和间隔以 S3 的 `latest.json` 为准。降水第 0 时效缺失时不补零，时间轴只列该要素实际有的时刻。

`/api/models/{model}/runs` 浏览器不缓存（前端 `no-store`），前端每 10 秒轮询。后端仍下发 Cloudflare 边缘缓存头（5 秒 + `stale-while-revalidate=30`），目前不经 Cloudflare，这些头不起作用。所选批次已被清理时，前端重读清单并重试一次。

## 底图

后端把 Esri World Imagery（4096×2048，EPSG:4326）下载到 `/data/basemap/world-imagery-4096x2048.jpg`，启动时预热，缓存 30 天，前端通过 `/api/basemap/world-imagery` 获取。

## 国内访问慢

域名直接解析到服务器 `49.51.229.109`，不经 Cloudflare（响应头 `server: nginx`，无 `cf-ray`）。瓶颈在跨境线路：服务器空闲时国内下载仍可能只有十几 KB/s，原因是线路丢包（约 2–3%）。服务器端的处理：

- 启用 BBR 拥塞控制（`/etc/sysctl.d/99-bbr.conf` 与 `/etc/modules-load.d/bbr.conf`，手动配置，部署不管）。默认的 cubic 遇到丢包会把发送窗口压到个位数。
- Nginx 压缩 JS、CSS、JSON、GeoJSON、SVG（`qingchuan-site.conf`）；`/api/` 关闭 Nginx 压缩，由后端自行 gzip，数据块流保持逐块到达。

前端 `frontend/src/net.ts` 的处理：

- JSON 请求限时 12 秒，网络类失败（超时、断开、408/429/5xx，含接入 Cloudflare 时的 520–524）按 0.8 秒、2.5 秒退避重试；后端业务错误（503 + detail）不重试。
- 数据块流 20 秒没有新数据视为卡住，只补请求未到的块，最多重试两次。
- 已有画面时，加载失败只在左上角温和提示并自动重试，不清空画面；单点面板失败给出「重试」按钮。

进一步改善：换香港/日本服务器，或备案后用国内 CDN。若重新接入 Cloudflare，可把 `/api/tiles/*`、`/api/provinces/shapes`、`/api/province-map/*`（内容固定）设为可缓存。
