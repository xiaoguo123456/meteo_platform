# 电力与气象资讯

## 电力与气象资讯

入口为 `/#news`，四个频道：两个细则、功率预测、电力交易、气象大模型。支持搜索、地区筛选、最新/重点排序、文章摘要、原文和附件入口、引用依据。两个细则频道另外提供“新闻动态”和“政策资料”两个视图。

### 两个细则资料库

“新闻动态”按时间展示政策发布、修订、征求意见和执行变化；“政策资料”按区域、省份、文件类型和状态整理官方文件。首批资料覆盖华北、华东、华中、东北，以及山东、江苏、福建、河南、湖南、四川。资料记录发布机构、发布日期、生效日期、适用主体、官方原文和附件链接。

政策状态使用“正式执行”“修订实施”“征求意见”“有效性待复核”等明确标签。未完成现行有效性核验的文件不会标成正式有效；资料库保存的是官方入口和结构化摘要，不替代原文，也不自动给出法律效力判断。

### 单机架构

独立 `news-worker` 容器采集并调用模型，限制 512 MiB 内存、0.4 CPU。与现有后端通过 `/data/news/news.sqlite` 共享结果，SQLite WAL 支持并发读写。前端只读取预处理结果，不实时调用模型。原 Open-Meteo 容器不变。

每五分钟调度一次，单个信源默认每小时检查。采集总并发三路，同一主机串行。每源每轮最多处理十二条候选，重复 URL 跳过；官方政策每天重新检查，正文变化保存旧版本。当前去重是 URL 和正文指纹精确去重，不宣称已完成跨媒体语义事件聚合或完整政策效力判定。

模型通过用户指定的 OpenAI 兼容接口使用 `gpt-5.6-luna`。凭据只在 `backend/.env.news`，权限 600，Git 和 Docker 构建上下文均排除。只给资讯 Worker 注入，不给前端或天气 API 注入。

**按照用户要求，不设置每日调用次数或 token 上限**：`NEWS_LLM_DAILY_CALLS=0`、`NEWS_LLM_DAILY_TOKENS=0`。调用和 token 统计仍保留。正整数可以重新启用可选上限。单次输出长度和重试间隔是技术保护，不是每日额度。

### 信源与内容质量

`backend/app/news/sources.json` 只保存已验收启用的信源。新增来源必须在部署服务器上通过栏目、文章链接、相关正文的端到端实测。访问受限、动态适配未完成、未取得有效文章的来源不进入运行名单。完整验收结果与停用原因保存在 `docs/data-sources/news-audit.json`，有效目录见下文「资讯信源目录」。

信源维护仅在服务器命令行进行，前端不展示采集状态、故障、调用量等运营信息，也不提供公开状态接口。文章仍保留来源名称、原文链接，以便读者核验。停用来源退出定时采集，但不删除已收录的有效文章及出处。可用性是验收时的结果，后续网络故障仍记录在服务日志。

新增内容先做领域筛选。无发布日期的内容标记待核实，不用采集时间代替发布日期。保留原始标题；公开页面只显示短摘录或 AI 摘要，不转载整篇正文。AI 依据引用必须逐字存在于输入中，不自动认定政策现行有效。

PDF 提取前四份优先与风光功率相关的附件，每个最多 12 MB、前 60 页；文件格式异常不影响其他信源。扫描件不伪造 OCR 结果，标记待识别。Word 等附件目前只提供原文链接。文档正文存于数据库用于核验，不公开全文。

企业宣传与官方、预印本、开源版本分别标注来源类型。初次回溯会出现较早的真实资料，按真实发布日期排序。

### 运维

```bash
# 查看采集日志，不输出环境变量
cd /opt/qingchuan
docker compose -f deploy/compose.yml logs --tail 60 news-worker

# 定向重试某个来源，不再次启动 AI 消费者
docker compose -f deploy/compose.yml exec news-worker python -m app.news.worker --once --force --no-ai --sources ecmwf

# 隐藏、恢复、重新摘要、纠正分类；管理入口仅在服务器内
docker compose -f deploy/compose.yml exec news-worker python -m app.news.manage hide ARTICLE_ID
docker compose -f deploy/compose.yml exec news-worker python -m app.news.manage restore ARTICLE_ID
docker compose -f deploy/compose.yml exec news-worker python -m app.news.manage retry ARTICLE_ID
docker compose -f deploy/compose.yml exec news-worker python -m app.news.manage classify ARTICLE_ID --channel forecast
```

接口：`GET /api/news`、`GET /api/news/{id}`、`GET /api/news/policies`、`GET /api/news/policies/{id}`。采集失败通过服务器命令 `python -m app.news.manage sources` 与日志检查。备份应使用 SQLite backup API，同时保留信源配置；不要直接复制写入中的单个数据库文件。

### 验证

新增测试覆盖日期、来源域限制、SQL 参数、分类、模型引文核验、访问校验页拦截、无限额配置和可选预算跨重启保持。前端构建与原气象后端测试一并执行。上线后通过真实文章验证四个频道、筛选、详情及来源状态。

借鉴 [AIHOT](https://github.com/KKKKhazix/AIHOT) 的采集、筛选和摘要流程，未复制其品牌或声称复用其运营信源。能源监管机构地址从 [国家能源局官网](https://www.nea.gov.cn/) 核验；论文订阅采用 [arXiv 官方 RSS 说明](https://github.com/arXiv/arxiv-docs/blob/develop/source/help/rss.md)。


### 信源复核

```sh
docker compose -f deploy/compose.yml exec news-worker python -m app.news.manage sources
docker compose -f deploy/compose.yml exec news-worker python -m app.news.audit --output /tmp/news-audit.json
```

验收脚本遵守同一 robots、超时和访问约束，不以固定历史种子代替栏目发现能力。只保存样本标题、网址和正文长度，不保存密钥或文章全文。

### 两个细则资料库维护规则

政策资料按 `version_type` 分为现行版本、历史版本、补充通知、考核参数、结算办法和区域适用说明；`status` 单独记录正式执行、修订实施、征求意见、历史版本、区域规则覆盖和有效性待复核。省级条目优先使用能源监管机构的正式发布页或附件，只有公开入口为区域规则时才建立“区域规则适用说明”，不会把区域文件冒充省级正式文件。

资料详情保留官方原文与附件链接，并在 PDF 存在时直接嵌入浏览器预览。AI 解读由独立 `news-worker` 读取公开原文后生成，展示摘要、关键变化和效力提示；解读仅用于快速理解，正式执行、考核参数和结算金额必须回到原文核对。

政策接口支持 `version_type` 筛选，并返回 `preview_url`、`ai_summary`、`ai_points` 与 `ai_state`。新增或替换文件时应同步记录 `supersedes_id`，以便追溯历史版本。

手动补充政策解读：

```bash
docker compose -f deploy/compose.yml exec news-worker python -m app.news.worker --once --policy-ai --no-ai
```

## 资讯信源目录

2026-10-14 在部署服务器完成实测，启用 33 个采集入口。入口包含同一机构的不同栏目，不等于独立机构数。仅启用取得有效相关文章的来源；维护状态仅在服务器命令行可见。

| 来源 | 类型 | 覆盖 | 入口 |
|---|---|---|---|
| 国家能源局 | 官方 | 全国 | [查看](https://www.nea.gov.cn/) |
| 华北能源监管机构 | 官方 | 华北 | [查看](https://hbj.nea.gov.cn/) |
| 东北能源监管机构 | 官方 | 东北 | [查看](https://dbj.nea.gov.cn/) |
| 西北能源监管机构 | 官方 | 西北 | [查看](https://xbj.nea.gov.cn/) |
| 华东能源监管机构 | 官方 | 华东 | [查看](https://hdj.nea.gov.cn/) |
| 南方能源监管机构 | 官方 | 南方 | [查看](https://nfj.nea.gov.cn/) |
| 山西能源监管机构 | 官方 | 山西 | [查看](https://sxb.nea.gov.cn/) |
| 山东能源监管机构 | 官方 | 山东 | [查看](https://sdb.nea.gov.cn/) |
| 甘肃能源监管机构 | 官方 | 甘肃 | [查看](https://gsb.nea.gov.cn/) |
| 新疆能源监管机构 | 官方 | 新疆 | [查看](https://xjb.nea.gov.cn/) |
| 浙江能源监管机构 | 官方 | 浙江 | [查看](https://zjb.nea.gov.cn/) |
| 江苏能源监管机构 | 官方 | 江苏 | [查看](https://jsb.nea.gov.cn/) |
| 福建能源监管机构 | 官方 | 福建 | [查看](https://fjb.nea.gov.cn/) |
| 湖南能源监管机构 | 官方 | 湖南 | [查看](https://hunb.nea.gov.cn/) |
| 四川能源监管机构 | 官方 | 四川 | [查看](https://scb.nea.gov.cn/) |
| 云南能源监管机构 | 官方 | 云南 | [查看](https://ynb.nea.gov.cn/) |
| 贵州能源监管机构 | 官方 | 贵州 | [查看](https://gzb.nea.gov.cn/) |
| 中国气象局·气象要闻 | 官方 | 全国 | [查看](https://www.cma.gov.cn/2011xwzx/2011xqxxw/2011xqxyw/) |
| 中国气象局·科技动态 | 官方 | 全国 | [查看](https://www.cma.gov.cn/2011xwzx/2011xqxkj/2011xkjdt/) |
| ECMWF·AIFS | 官方 | 国际 | [查看](https://www.ecmwf.int/en/about/media-centre/aifs-blog) |
| ECMWF·新闻 | 官方 | 国际 | [查看](https://www.ecmwf.int/en/about/media-centre/news) |
| Microsoft Research·Aurora | 官方 | 国际 | [查看](https://www.microsoft.com/en-us/research/project/aurora-forecasting/) |
| Aurora 开源版本 | 开源项目 | 国际 | [查看](https://github.com/microsoft/aurora/releases.atom) |
| Earth2Studio 开源版本 | 开源项目 | 国际 | [查看](https://github.com/NVIDIA/earth2studio/releases.atom) |
| Anemoi 开源版本 | 开源项目 | 国际 | [查看](https://github.com/ecmwf/anemoi-core/releases.atom) |
| 国能日新·技术动态 | 企业发布 | 全国 | [查看](https://www.sprixin.com/news/Company/) |
| 中国能源新闻网 | 行业媒体 | 全国 | [查看](https://www.cpnn.com.cn/index.html) |
| NVIDIA 技术动态 | 企业发布 | 国际 | [查看](https://blogs.nvidia.com/) |
| 广东省发展改革委 | 官方 | 广东 | [查看](https://drc.gd.gov.cn/) |
| 中国能源新闻网技术 | 行业媒体 | 全国 | [查看](https://www.cpnn.com.cn/qiye/jishu2023/) |
| 中国能源新闻网能源要闻 | 行业媒体 | 全国 | [查看](https://www.cpnn.com.cn/news/nytt/index.html) |
| 中国气象科学研究院 | 官方 | 全国 | [查看](https://www.camscma.cn/) |
| 宁夏发展改革委 | 官方 | 宁夏 | [查看](https://fzggw.nx.gov.cn/) |

完整验收及排除原因见 [验收记录](data-sources/news-audit.json)。网络和上游页面可能变化，验收结果不代表永久可用。
