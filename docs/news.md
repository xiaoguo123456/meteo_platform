# 电力与气象资讯

入口 `/#news`，四个频道：两个细则、功率预测、电力交易、气象大模型。支持搜索、地区筛选、最新/重点排序、AI 摘要、原文和附件链接。两个细则频道另有「新闻动态」和「政策资料」两个视图。

## 架构

- 独立 `news-worker` 容器负责采集和调用模型（内存 512 MiB、0.4 CPU），与后端通过 `/data/news/news.sqlite`（WAL）共享结果。前端只读处理好的结果。
- 每 5 分钟调度一次，单个信源默认每小时检查；总并发 3 路，同一主机串行；每源每轮最多 12 条候选。官方政策每天复查，正文变化时保存旧版本。去重按 URL 和正文指纹。
- 模型走 OpenAI 兼容接口，凭据在 `backend/.env.news`（权限 600，不入 Git、不进构建上下文），只注入资讯 Worker。`NEWS_LLM_DAILY_CALLS=0`、`NEWS_LLM_DAILY_TOKENS=0` 表示不设每日上限，改成正整数即启用。
- 信源配置在 `backend/app/news/sources.json`，只放在部署服务器上实测能取到相关正文的来源。

内容规则：

- 先做领域筛选；没有发布日期的标「待核实」，不用采集时间代替。
- 公开页面只显示短摘录或 AI 摘要，不转载全文；AI 引用必须逐字出现在原文里。
- PDF 每篇最多取 4 个附件，每个最多 12 MB、前 60 页；扫描件标「待识别」，不伪造 OCR。Word 等附件只给链接。
- 来源类型分官方、企业、预印本、开源版本分别标注。

## 两个细则资料库

- 「新闻动态」按时间展示政策发布、修订、征求意见；「政策资料」按区域、省份、文件类型、状态整理官方文件，记录发布机构、日期、生效日期、适用主体、原文和附件。
- `version_type`：现行版本、历史版本、补充通知、考核参数、结算办法、区域适用说明。`status`：正式执行、修订实施、征求意见、历史版本、区域规则覆盖、有效性待复核。没核验现行有效性的文件不标为正式有效。
- 省级条目优先用能源监管机构的正式发布页；只有区域规则时建「区域规则适用说明」，不冒充省级文件。替换文件时记录 `supersedes_id`。
- 详情页嵌入 PDF 预览，AI 解读给出摘要、关键变化和效力提示，执行和结算数字须回原文核对。

## 接口

`GET /api/news`、`/api/news/{id}`、`/api/news/policies`（支持 `version_type`）、`/api/news/policies/{id}`。不提供采集状态的公开接口。

## 运维

```bash
cd /opt/qingchuan
# 采集日志
docker compose -f deploy/compose.yml logs --tail 60 news-worker
# 信源状态
docker compose -f deploy/compose.yml exec news-worker python -m app.news.manage sources
# 定向重试某个来源（不启动 AI）
docker compose -f deploy/compose.yml exec news-worker python -m app.news.worker --once --force --no-ai --sources ecmwf
# 补充政策 AI 解读
docker compose -f deploy/compose.yml exec news-worker python -m app.news.worker --once --policy-ai --no-ai
# 隐藏 / 恢复 / 重新摘要 / 纠正分类
docker compose -f deploy/compose.yml exec news-worker python -m app.news.manage hide ARTICLE_ID
docker compose -f deploy/compose.yml exec news-worker python -m app.news.manage restore ARTICLE_ID
docker compose -f deploy/compose.yml exec news-worker python -m app.news.manage retry ARTICLE_ID
docker compose -f deploy/compose.yml exec news-worker python -m app.news.manage classify ARTICLE_ID --channel forecast
# 新增信源前做验收
docker compose -f deploy/compose.yml exec news-worker python -m app.news.audit --output /tmp/news-audit.json
```

备份用 SQLite backup API，不要直接复制正在写入的数据库文件。
