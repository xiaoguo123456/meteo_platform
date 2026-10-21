# 中国省界来源及处理

- 数据：GMT China Geospatial Data v0.4.0，发布于 2024-12-25。
- 原始数据：1:100 万全国基础地理数据库（2021 版）。引自全国地理信息资源目录服务系统 https://www.webmap.cn/ 。
- 上游说明：https://docs.gmt-china.org/latest/dataset/CN-border/
- 下载：https://github.com/gmt-china/china-geospatial-data/releases/tag/v0.4.0
- 文件：UTF8 包中的 CN-border-La.gmt，EPSG:4326，含中国国界、省界、海岛及十段线。
- 本地：backend/app/data/provinces.geojson；只绘制线，不对面进行填色。

上游明确仅供科研用途，不能宣称为经过地图审核的正式发布底图；需要正式对外发布时须替换为用途授权及审核均满足要求的数据版本。该来源不是天地图在线行政区划接口，不冒称已取得天地图授权。

转换脚本 `scripts/convert_boundaries.py` 保留所有 1083 条线段，省级行政区名称含港澳台，额外图元保留。线条显示采用 0.003 度容差简化，从 794169 个点减至 73799 点；未丢弃独立岛屿和边界线段。该处理仅用于边界渲染，不涉及任何气象网格的分辨率或数值。

同一文件实为面数据（`@GPOLYGON`，含 @P 外环与 @H 洞）。`python scripts/convert_boundaries.py CN-border-La.gmt backend/app/data/provinces.geojson backend/app/data/province_regions.json` 额外按省级代码合并为 34 个 MultiPolygon（0.001 度容差简化，简化后不足三角形的微小岛屿保留原始坐标；面积与源数据 Shape_Area 一致，如北京 1.7348 平方度），仅用于省平均统计和选中高亮，不填色。用法见 `province-average.md`。
