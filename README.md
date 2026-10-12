# 全球天气态势浏览器

这是一个基于 Globe.gl 的单机天气可视化项目骨架，前端负责三维地球和交互，后端负责天气数据接口，后台任务负责后续的数据同步与预处理。

## 目录

```text
frontend/   React + TypeScript + Vite + Globe.gl
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

当前 Worker 只有同步入口和日志，真实模型数据接入按 [docs/architecture.md](docs/architecture.md) 的数据流程实现。

## 当前状态

- Globe.gl 地球、夜间纹理和大气光晕已经接入；
- 模型选择、天气要素、时间轴和播放控制已经有页面骨架；
- 后端提供健康检查、模型目录、天气场清单和省界接口；
- 省级边界文件目前是空的 GeoJSON 占位，待接入正式数据；
- 风场粒子和卫星云图接口预留了扩展位置。
