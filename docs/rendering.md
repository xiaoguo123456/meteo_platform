# 风场渲染与数据分块

## 渲染

首页用 D3 正射投影（`d3-geo`）+ 分层 Canvas，算法参考 cambecc/earth（独立实现，未复制参考站代码）。

- Worker 负责：屏幕坐标反投影到经纬度、u/v 双线性插值、风向投影修正、2×2 像素风速/要素色场、Esri 底图采样。固定视角下反投影与底图采样结果缓存复用，视野、尺寸或底图变化时失效。
- 主线程负责粒子：在可见区域随机播种，每步按当前位置读取屏幕风矢量；寿命约 100 帧后重播种；上一帧以约 0.97 透明度衰减形成尾迹，按速度分桶批量描线。粒子数约为可见宽度 × 7，移动端 × 0.75。
- 只有风场有粒子；温度、气压、湿度、降水、云量只画数值色带，色标、单位和高度层随要素切换。
- 交互：Worker 与画布在组件生命周期内复用，拖动缩放时先按 6 像素步长预览，停止 100ms 后恢复 2 像素精度；最多一个渲染任务在途，旧结果按代次丢弃；重算完成前保留上一张完整画面。
- 画布按设备像素比（最高 2 倍）绘制，球面边缘用圆形裁剪抗锯齿。
- 海岸线为 Natural Earth 110m；底图为 Esri World Imagery 4096×2048 全球影像（见 [部署](deployment.md)「底图」），需保留 Esri 署名。

## 数据分块

每个时刻、每个要素按原生网格切成 128×128 块，块内字典编码，再对索引逐行做 uint16 差分后 gzip（v4，无损，含缺测）。同一要素存为一个 `.v4.blocks` 文件加 `.v4.json` 偏移索引。后台预缓存时生成；v4 未就绪而 v3 已就绪时直接返回 v3，浏览器兼容解码。GFS/IFS/AIFS 为 0.25°，GRAPES 为 0.125°，不做降采样金字塔。

`GET /api/tiles/{model}?field=&run_time=&valid_time=&tiles=&version=4`：响应为连续的「4 字节小端长度 + gzip 块」，浏览器用 DecompressionStream 逐块解码，每 250ms 合并一次画面更新。固定批次的响应可长期缓存。

前端按正射视野计算可见球冠（外扩插值边缘），从视野中心向外请求，背面不下载，拖动后只补缺块。缺失区域只显示底图，不填造数据。块缓存预算 192 MiB。

## 时间轴与预取

- 从当前时刻顺序播放到最后一帧停止，再点播放从头开始；每帧至少展示 1.5 秒，下一帧完整到达才切换，网络慢时显示缓冲、不跳帧。
- 后台预取后续帧；静止时额外预取其他要素的首帧，播放时只预取后续时刻。
- 切换视野、模型、要素或拖动时间轴会停止播放。新批次发布后暂停播放、重置时间轴，新帧到达前保留旧画面。

## 调试

地球元素上的 `data-fps`、`data-frame-cost-ms`、`data-field-build-ms` 和 `data-render-samples`（最近 120 帧的总耗时、等待时间、Worker 计算时间）用于性能排查，不在界面显示。

## 测试

```bash
cd frontend
./node_modules/.bin/esbuild tests/windMath.test.ts --bundle --platform=node --format=esm --outfile=/tmp/meteo-wind-test.mjs
node /tmp/meteo-wind-test.mjs
npm run build
cd ../backend
.venv/bin/python -m unittest discover -s tests -v
```

`frontend/tests/` 下其他 `*.test.ts` 用同样方式打包运行。
