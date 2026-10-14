# 晴川观象

这是一个单机天气可视化项目。首页使用 D3 正射投影和 Canvas 连续风场，FastAPI 直接读取 Open-Meteo S3 的原生网格。

## 目录

```text
frontend/   React + TypeScript + Vite + D3 / Canvas
backend/    FastAPI API 与 Worker 入口
docs/       架构与数据接入说明
data/       本地天气场、云图和边界数据目录
```

## 本地启动

### 前端

```bash
cd frontend
npm install
npm run dev
```

### 后端

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

前端开发服务器会把 `/api` 请求代理到 `http://localhost:8000`。打开 `http://localhost:5173` 查看页面，打开 `http://localhost:8000/docs` 查看 API 文档。

### 后台任务

```bash
cd backend
python -m app.worker
```

API 启动后自动运行预取任务，无需再启动 Worker。独立 Worker 入口可用于分进程部署，文件锁避免同时重复同步。默认每 5 分钟轮询最新起报清单，按预报时刻提前缓存全部已接入变量。

## 当前状态

- 首页：真实四模型全球风速底色（GFS/IFS/AIFS 0.25°、GRAPES 0.125°）、连续流线、旋转缩放和默认流线动画；显示模型实际高度及有效时间。
- `/api/wind/gfs`：只读取本地预缓存，支持 `field`、`run_time`、`valid_time`；请求不触发 S3 下载。S3 同步错误直接展示。
- 四模型自动提前缓存最新起报，支持要素切换、时间轴拖动和自动播放。IFS/AIFS/GRAPES 使用 10m 风、2m 温湿度、海平面气压及时段降水；GFS 保留实际 80m 风和 1000hPa 温湿度，缺失降水不伪造。底图已接入 Esri World Imagery 全球影像；卫星图层尚未迁移。
- 海岸线采用 Natural Earth；正式中国省级边界尚未接入，现有省界文件为空占位。
- 实现与测试见 [风场渲染说明](docs/wind-rendering.md)。

## Docker 生产部署

使用独立 Compose 项目：`docker compose -f deploy/compose.yml up -d --build`。前端默认端口 8091，后端只在容器内网访问。全模型共享 4 路并发预取，完成后清理原始分块。配置与维护说明见 [部署文档](docs/deployment.md)。
