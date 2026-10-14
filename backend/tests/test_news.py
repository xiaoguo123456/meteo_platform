import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import httpx
from app.news import store
from app.news.collector import extract,category,canonical,allowed,candidates
from app.news.worker import summarize
from app.news.api import listing, policies, policy

class NewsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.patch=patch.object(store,'ROOT',Path(self.temp.name));self.patch.start();store.initialize()
    def tearDown(self):self.patch.stop();self.temp.cleanup()
    def test_extract_date_attachment_and_navigation(self):
        html='<html><head><meta name="ArticleTitle" content="功率预测考核修订"><meta name="PubDate" content="2026-10-12"></head><body><nav>广告</nav><div class="TRS_Editor">正式条文<a href="file.pdf">附件</a></div></body></html>'
        result=extract(html.encode(),'https://example.org/news/test.html')
        self.assertEqual(result['published_at'],'2026-10-12');self.assertNotIn('广告',result['body']);self.assertEqual(result['attachments'][0]['url'],'https://example.org/news/file.pdf')
    def test_unknown_date_is_not_today(self):
        self.assertIsNone(extract(b'<h1>test</h1>','https://example.org/test.html')['published_at'])
    def test_categories_prioritize_rules(self):
        self.assertEqual(category('功率预测考核修订'),'rules');self.assertEqual(category('风电功率预测研究'),'forecast');self.assertEqual(category('电力现货市场交易规则'),'market');self.assertEqual(category('GraphCast weather model'),'ai');self.assertEqual(category('今天公司聚餐'),'')
    def test_links_are_limited_to_source(self):
        s={'url':'https://example.org/'}
        self.assertFalse(allowed('http://127.0.0.1/a',s));self.assertFalse(allowed('javascript:alert(1)',s));self.assertFalse(allowed('https://example.org.attacker.com/a',s));self.assertTrue(allowed('https://example.org/a',s));self.assertEqual(canonical('https://example.org/a?utm_source=x&id=2#top'),'https://example.org/a?id=2')
    def test_budget_survives_reinitialization(self):
        with patch.dict('os.environ',{'NEWS_LLM_DAILY_CALLS':'1','NEWS_LLM_DAILY_TOKENS':'10000'}):
            self.assertTrue(store.reserve_call(500));store.initialize();self.assertFalse(store.reserve_call(500))
    def test_list_filters_and_no_private_body(self):
        with store.db() as c:
            c.execute("INSERT INTO sources(id,name,tier) VALUES('test','测试源','官方')")
            c.execute("INSERT INTO articles(id,source_id,title,channel,region,body,excerpt) VALUES('a','test','预测公告','forecast','山东','内部全文','摘录')")
        result=listing(channel='forecast',region='山东',q='',sort='latest',page=1,limit=20)
        self.assertEqual(result['total'],1);self.assertNotIn('body',result['items'][0]);self.assertEqual(listing(channel='',region='',q="' OR 1=1 --",sort='latest',page=1,limit=20)['total'],0)
    def test_llm_facts_require_exact_quote(self):
        row={'id':'a','body':'本文件为征求意见稿，尚未正式发布。','title':'规则征求意见','source_id':'test','channel':'rules'}
        with store.db() as c:c.execute("INSERT INTO articles(id) VALUES('a')")
        async def run():
            def reply(request):return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'relevant':True,'summary':'正在征求意见。','score':80,'tags':[],'facts':[{'label':'状态','value':'生效','quote':'已经正式生效'},{'label':'状态','value':'征求意见','quote':'本文件为征求意见稿'}]})}}],'usage':{'total_tokens':50}})
            async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:return await summarize(client,row)
        with patch.dict('os.environ',{'NEWS_LLM_KEY':'test-only','NEWS_LLM_URL':'https://example.org'}):self.assertTrue(asyncio.run(run()))
        with store.db() as c:
            facts=json.loads(c.execute("SELECT facts FROM articles WHERE id='a'").fetchone()[0]);self.assertEqual(len(facts),1);self.assertEqual(facts[0]['value'],'征求意见')

    def test_access_challenge_never_becomes_news(self):
        with self.assertRaises(ValueError):extract(b'<body>{"_waf_abc":"encrypted"}</body>','https://example.org/a.html')
    def test_zero_budget_means_unlimited(self):
        with patch.dict('os.environ',{'NEWS_LLM_DAILY_CALLS':'0','NEWS_LLM_DAILY_TOKENS':'0'}):
            self.assertTrue(store.reserve_call(99999999));self.assertTrue(store.reserve_call(99999999))

    def test_vendor_headings_and_unsafe_attachment(self):
        html='<h1>栏目</h1><div class="join3_btm_01"><h2>真实新闻标题</h2></div><div class="join3_btm_02">新闻正文<a href="javascript:alert(1)//x.pdf">伪附件</a></div>'
        v=extract(html.encode(),'https://example.org/test.html')
        self.assertEqual(v['title'],'真实新闻标题');self.assertEqual(v['attachments'],[])

    def test_weather_wind_is_not_power_forecast(self):
        self.assertNotEqual(category('Wind, rain and sunshine in the forecast'),'forecast')
        self.assertEqual(category('Wind power forecasting methods'),'forecast')
    def test_source_status_is_not_public(self):
        from app.news.api import router
        self.assertNotIn('/api/news/sources',[r.path for r in router.routes])

    def test_article_scope_excludes_site_clock_and_navigation(self):
        html='<div>时间 2026-10-14 导航 电力交易</div><div class="fymainri"><h1>气象模型</h1><div class="fyykjj">实际正文</div></div>'
        doc=extract(html.encode(),'https://example.org/article/123.html')
        self.assertIsNone(doc['published_at']);self.assertEqual(doc['body'],'实际正文');self.assertEqual(doc['title'],'气象模型')

    def test_media_body_ignores_sidebar_keywords(self):
        html='<div class="cpnnlist_l"><h3>实际标题</h3><p class="times">时间：2026-10-12</p><p>正文内容</p></div><div class="cpnnlist_r">电力交易</div>'
        doc=extract(html.encode(),'https://example.org/a.html')
        self.assertEqual(doc['title'],'实际标题');self.assertEqual(doc['body'],'正文内容');self.assertEqual(doc['published_at'],'2026-10-12');self.assertEqual(category(doc['title'],doc['body']),'')

    def test_policy_library_filters_and_details(self):
        result=policies(region='华东',province='山东',status='正式执行',q='',page=1,limit=30)
        self.assertEqual(result['total'],3)
        self.assertEqual(result['items'][0]['province'],'山东')
        self.assertEqual(policy('shandong-2026-two-rules')['effective_at'],'2026-01-01')
        self.assertEqual(policy('shandong-2026-two-rules')['version_type'],'current')
