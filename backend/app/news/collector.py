"""公开信源增量采集。源配置可信，网页及模型内容均按不可信文本处理。"""
import asyncio
import hashlib
import io
import ipaddress
import json
import re
import socket
from datetime import datetime, timezone
from functools import lru_cache
from urllib.parse import urljoin,urlsplit,urlunsplit,parse_qsl,urlencode
from urllib.robotparser import RobotFileParser
import feedparser
import httpx
from bs4 import BeautifulSoup
from pypdf import PdfReader
from . import store

AGENT='QingchuanNews/1.0'
TERMS={
'rules':r'两个细则|并网运行.*(?:细则|管理)|辅助服务.*(?:细则|管理)|功率预测.*考核',
'forecast':r'功率预测|(?:风光水|风光|新能源).{0,12}预测|发电.{0,6}预测|预测.{0,6}发电|出力预测|风电预测|光伏预测|辐照度预测|power forecast|(?:wind power|wind energy|solar power|solar energy|photovoltaic).{0,40}(?:forecast|predict)|(?:forecast|predict).{0,40}(?:wind power|wind energy|solar power|solar energy|photovoltaic)',
'market':r'电力交易|电力市场|电力现货|现货市场|中长期交易|绿电交易|绿证|辅助服务|电价|售电|electricity market|electricity pric',
'ai':r'AIFS|GraphCast|GenCast|WeatherNext|Aurora|Anemoi|Earth.?2|气象大模型|天气大模型|人工智能.*(?:气象|天气|预报)|(?:气象|天气).*人工智能|风乌|伏羲|盘古气象|风顺|旷冥|新能源大模型|machine.learn.*weather|weather.*(?:model|AI|neural)|foundation model.*atmospher'}


def category(title,body='',fallback=''):
    for channel,pattern in TERMS.items():
        if re.search(pattern,title,re.I):return channel
    if re.search(r'党建|招聘|网民留言|诚信兴商|巡视|干部任免|党纪|廉政|党组|传达.*精神|工作例会|begins role|appointed',title):return ''
    text=body[:12000]
    for channel,pattern in TERMS.items():
        if re.search(pattern,text,re.I):return channel
    return ''


def canonical(url):
    p=urlsplit(url)
    return urlunsplit((p.scheme,p.netloc.lower(),p.path,urlencode([(k,v) for k,v in parse_qsl(p.query) if not k.lower().startswith(('utm_','spm'))]),''))


def allowed(url,source):
    p=urlsplit(url)
    domains=source.get('allow_domains',[])+[urlsplit(source['url']).hostname]
    return p.scheme in ('https','http') and not p.username and p.hostname and any(p.hostname==d or p.hostname.endswith('.'+d) for d in domains if d)


@lru_cache(maxsize=256)
def validate_host(host):
    for address in socket.getaddrinfo(host,None):
        if not ipaddress.ip_address(address[4][0]).is_global:raise ValueError('不允许访问非公网地址')


class Fetcher:
    def __init__(self,client):self.client=client;self.robots={}
    async def raw(self,url,limit=3_000_000):
        for _ in range(5):
            p=urlsplit(url)
            if p.scheme not in ('http','https') or not p.hostname or p.username:raise ValueError('链接无效')
            await asyncio.to_thread(validate_host,p.hostname)
            async with self.client.stream('GET',url) as r:
                if r.is_redirect:url=urljoin(url,r.headers['location']);continue
                r.raise_for_status();chunks=[];size=0
                async for chunk in r.aiter_bytes():
                    size+=len(chunk)
                    if size>limit:raise ValueError('响应超过采集大小上限')
                    chunks.append(chunk)
                return b''.join(chunks),r.headers.get('content-type',''),str(r.url)
        raise ValueError('重定向过多')
    async def get(self,url,limit=3_000_000):
        p=urlsplit(url);origin=f'{p.scheme}://{p.netloc}'
        if origin not in self.robots:
            try:
                data,_,_=await self.raw(origin+'/robots.txt',500_000)
                parser=RobotFileParser();parser.parse(data.decode('utf-8','replace').splitlines());self.robots[origin]=parser
            except httpx.HTTPStatusError as e:
                if e.response.status_code not in (404,410):raise
                self.robots[origin]=None
        robot=self.robots[origin]
        if robot and not robot.can_fetch(AGENT,url):raise ValueError('信源 robots.txt 不允许采集该地址')
        return await self.raw(url,limit)


def soup_of(data):
    # 优先使用 HTML 声明的编码，避免中文被误判成单字节编码。
    head=data[:4096]
    match=re.search(br'charset=["\s]*([\w-]+)',head,re.I)
    encoding=match.group(1).decode() if match else 'utf-8'
    try:text=data.decode(encoding)
    except (UnicodeError,LookupError):text=data.decode('gb18030','replace')
    return BeautifulSoup(text,'html.parser')


def date_value(text):
    m=re.search(r'(20\d{2})[-/年.](\d{1,2})[-/月.](\d{1,2})',text or '')
    if not m:return None
    try:return datetime(*map(int,m.groups()),tzinfo=timezone.utc).date().isoformat()
    except ValueError:return None


def extract(data,url):
    soup=soup_of(data)
    title_meta=soup.select_one('meta[name="ArticleTitle"],meta[property="og:title"]')
    specific=soup.select_one('.article-title,.biaoti_title,.join3_btm_01 h2,.fymainribt,.fymainri h1,.fymainri h2,.cpnnlist_l h1,.cpnnlist_l h3')
    heading=specific or soup.select_one('h1') or soup.title
    title=(specific.get_text(' ',strip=True) if specific else title_meta.get('content','') if title_meta else heading.get_text(' ',strip=True) if heading else '').strip()
    title=re.sub(r'\s+\d{2}-\d{2}$','',title)
    title=re.split(r'\s*发布时间[：:]',title)[0].strip().lstrip('> ').strip()
    published=None;basis='未知'
    date_scope=soup.select_one('.fymainri,.cpnnlist_l') or soup
    for tag in soup.select('meta'):
        if str(tag.get('name',tag.get('property',''))).lower() in ('articletime','pubdate','publishdate','pubtime','date','article:published_time','dc.date','dc.date.issued'):
            published=date_value(tag.get('content',''))
            if published:basis='原文元数据';break
    if not published:
        article_date=soup.select_one('.article-data dt')
        if article_date:published=date_value(article_date.get_text());basis='原文时间'
    if not published:
        t=soup.find('time');published=date_value(t.get('datetime','') or t.get_text()) if t else None
        if published:basis='原文时间'
    if not published:
        match=re.search(r'(?:发布时间|发布日期|时间|日期)[：:\s]*(20\d{2}[-/年.]\d{1,2}[-/月.]\d{1,2})',date_scope.get_text(' ',strip=True))
        if match:published=date_value(match.group(1));basis='原文时间'
    if not published:
        match=re.search(r'(20\d{2})(\d{2})(\d{2})',url)
        if match:published=date_value('-'.join(match.groups()));basis='链接日期'
    for e in soup.select('script,style,nav,header,footer,aside,noscript,form'):e.decompose()
    node=soup.select_one('.fyykjj,.cpnnlist_l,.TRS_Editor,.TRS_UEDITOR,.join3_btm_02,.article-content,.article_content,#zoom,.entry-content,.rich-text,article')
    if not node:node=soup.select_one('main') or soup.body or soup
    if 'cpnnlist_l' in node.get('class',[]):
        for el in node.select('h3,.times'):el.decompose()
    body=node.get_text('\n',strip=True)
    if re.search(r'_waf_|var arg1=|verify you are human|checking your browser|访问过于频繁',body,re.I):raise ValueError('来源返回访问校验页，未获取正文')
    body=re.sub(r'\n{3,}','\n\n',body)[:100000]
    attachments=[]
    for a in node.select('a[href]'):
        link=canonical(urljoin(url,a['href']))
        if urlsplit(link).scheme not in ('http','https'):continue
        if re.search(r'\.(?:pdf|docx?|xlsx?)(?:\?|$)',link,re.I):attachments.append({'title':a.get_text(' ',strip=True)[:200] or '附件','url':link,'state':'仅原文链接'})
    return dict(title=title[:500],body=body,published_at=published,date_basis=basis,attachments=attachments[:12])


def candidates(data,source,url):
    soup=soup_of(data);seen=set();result=[]
    for a in soup.select('a[href]'):
        link=canonical(urljoin(url,a['href']));title=a.get('title') or a.get_text(' ',strip=True)
        if link in seen or not allowed(link,source) or len(title)<9:continue
        if not re.search(r'\.s?html?(?:\?|$)|/20\d{2}/|/20\d{6}/|/blog/[^/]+/?$|/news/[^/]+/?$|/focus-[^/]+/?$|/abs/',link):continue
        seen.add(link);result.append((link,title))
    # 相关标题优先，但未命中关键词的原文仍留部分名额供正文判断。
    return sorted(result,key=lambda pair:not bool(category(pair[1])))[:60]


async def collect_source(source,fetcher,force=False):
    sid=source['id']
    with store.db() as c:
        c.execute('INSERT INTO sources(id,name,url,kind,region,tier) VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET checked_at=CASE WHEN sources.url!=excluded.url THEN NULL ELSE sources.checked_at END,name=excluded.name,url=excluded.url,kind=excluded.kind,region=excluded.region,tier=excluded.tier',tuple(source.get(k,'') for k in ('id','name','url','kind','region','tier')))
        row=c.execute('SELECT checked_at FROM sources WHERE id=?',(sid,)).fetchone()
        if not force and row['checked_at'] and (datetime.now(timezone.utc)-datetime.fromisoformat(row['checked_at'])).total_seconds()<source.get('interval',3600):return
    added=0;count=0;errors=[]
    try:
        data,_,url=await fetcher.get(source['url'])
        entries={}
        if source['kind']=='rss':
            feed=feedparser.parse(data)
            if not feed.entries and not feed.feed.get('title'):raise ValueError('订阅源没有可解析条目')
            pairs=[]
            for e in feed.entries[:300]:
                link=canonical(e.link)
                if not allowed(link,source):continue
                pairs.append((link,e.title));entries[link]=e
            pairs.sort(key=lambda pair:not bool(category(pair[1],entries[pair[0]].get('summary',''))))
        else:
            pairs=candidates(data,source,url)
            if source.get('follow_sections'):
                soup=soup_of(data);sections=[]
                for a in soup.select('a[href]'):
                    if a.get_text(strip=True) in ('通知公告','政策解读','政策法规'):
                        link=urljoin(url,a['href'])
                        if allowed(link,source) and link not in sections:sections.append(link)
                for link in sections[:2]:
                    try:
                        section,_,resolved=await fetcher.get(link);pairs+=candidates(section,source,resolved)
                    except Exception:errors.append('部分栏目读取失败')
            if not pairs and not source.get('seeds'):raise ValueError('未提取到文章链接，可能需要动态网页适配')
        pairs=[(u,'') for u in source.get('seeds',[])]+pairs
        seen=set();processed=0
        for link,title in pairs:
            if link in seen:continue
            seen.add(link);count+=1
            with store.db() as c:old=c.execute('SELECT * FROM articles WHERE url=?',(link,)).fetchone()
            # 已收录政策每天检查一次；普通文章不重复请求。
            if old and not force and (old['channel']!='rules' or (datetime.now(timezone.utc)-datetime.fromisoformat(old['updated_at'])).total_seconds()<86400):continue
            if processed>=int(__import__('os').getenv('NEWS_SOURCE_BATCH','16')):break
            processed+=1
            try:
                if link in entries:
                    e=entries[link];body=BeautifulSoup(e.get('summary',''),'html.parser').get_text(' ',strip=True)
                    date=e.get('published_parsed') or e.get('updated_parsed')
                    published=datetime(*date[:6],tzinfo=timezone.utc).date().isoformat() if date else None
                    doc={'title':(source['name']+' · ' if source.get('dedicated') else '')+title,'body':body,'published_at':published,'date_basis':'订阅源时间' if date else '未知','attachments':[]}
                else:
                    article,_,resolved=await fetcher.get(link)
                    doc=extract(article,resolved)
                    if not doc['title']:doc['title']=title
                channel=category(doc['title'],doc['body'])
                if source.get('dedicated'):channel=source['channel']
                if not channel:
                    if old:
                        with store.db() as c:c.execute('UPDATE articles SET hidden=1 WHERE id=?',(old['id'],))
                    continue
                if len(doc['body'])<100 and not doc['attachments']:
                    if old:
                        with store.db() as c:c.execute('UPDATE articles SET hidden=1 WHERE id=?',(old['id'],))
                    raise ValueError('正文不足，需人工核验')
                # 附件保留来源，PDF 可提取文字时供模型结合原文分析。
                for attachment in sorted(doc['attachments'],key=lambda a:not bool(re.search('功率|风电|光伏',a['title'])))[:4]:
                    if not allowed(attachment['url'],source):continue
                    if not re.search(r'\.pdf(?:\?|$)',attachment['url'],re.I):continue
                    try:
                        raw,_,_=await fetcher.get(attachment['url'],12_000_000)
                        def pdf_text():
                            reader=PdfReader(io.BytesIO(raw));return '\n'.join((page.extract_text() or '') for page in list(reader.pages)[:60])[:30000]
                        text=await asyncio.wait_for(asyncio.to_thread(pdf_text),30)
                        text=text.encode('utf-8','replace').decode('utf-8')
                        attachment['state']='已提取文字' if len(text)>100 else '扫描件，待文字识别'
                        if len(text)>100:doc['body']+='\n附件《'+attachment['title']+'》\n'+text
                    except Exception:attachment['state']='附件提取失败，可查看原文'
                body=doc['body'][:100000];digest=hashlib.sha256(body.encode()).hexdigest();stamp=store.now()
                aid=hashlib.sha256(link.encode()).hexdigest()[:24]
                with store.db() as c:
                    duplicate=c.execute('SELECT id FROM articles WHERE body_hash=? AND id!=? AND duplicate_of IS NULL LIMIT 1',(digest,aid)).fetchone()
                    if old and old['body_hash']==digest:
                        c.execute('UPDATE articles SET updated_at=?,title=?,published_at=?,date_basis=?,channel=? WHERE id=?',(stamp,doc['title'],doc['published_at'],doc['date_basis'],channel,aid));continue
                    if old:c.execute('INSERT INTO revisions(article_id,body_hash,body,recorded_at) VALUES(?,?,?,?)',(aid,old['body_hash'],old['body'],stamp))
                    region=source.get('region','全国')
                    if region in ('全国','国际'):
                        found=re.findall('北京|天津|河北|山西|内蒙古|辽宁|吉林|黑龙江|上海|江苏|浙江|安徽|福建|江西|山东|河南|湖北|湖南|广东|广西|海南|重庆|四川|贵州|云南|西藏|陕西|甘肃|青海|宁夏|新疆',doc['title'])
                        if found:region='、'.join(dict.fromkeys(found))
                    c.execute('''INSERT INTO articles(id,source_id,url,title,published_at,date_basis,discovered_at,updated_at,channel,region,body,body_hash,excerpt,attachments,duplicate_of,score)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,published_at=excluded.published_at,date_basis=excluded.date_basis,channel=excluded.channel,body=excluded.body,body_hash=excluded.body_hash,updated_at=excluded.updated_at,attachments=excluded.attachments,summary='',ai_state='pending',facts='{}',excerpt=excluded.excerpt''',
                    (aid,sid,link,doc['title'],doc['published_at'],doc['date_basis'],stamp,stamp,channel,region,body,digest,body[:180],json.dumps(doc['attachments'],ensure_ascii=False),duplicate['id'] if duplicate else None,90 if channel=='rules' and source['tier']=='官方' else 50))
                added+=1
            except Exception as e:errors.append(safe_error(e))
            await asyncio.sleep(.3)
        with store.db() as c:c.execute('UPDATE sources SET checked_at=?,success_at=?,error=?,candidates=?,added=? WHERE id=?',(store.now(),store.now(),'；'.join(dict.fromkeys(errors))[:250] or None,count,added,sid))
    except Exception as e:
        with store.db() as c:c.execute('UPDATE sources SET checked_at=?,error=?,candidates=?,added=? WHERE id=?',(store.now(),safe_error(e),count,added,sid))
    print(f'信源 {sid} 检查完成：候选 {count}，新增或更新 {added}',flush=True)


def safe_error(error):
    if isinstance(error,httpx.HTTPStatusError):return '上游 HTTP '+str(error.response.status_code)
    if isinstance(error,(httpx.TimeoutException,asyncio.TimeoutError)):return '上游请求超时'
    if isinstance(error,ValueError):return str(error)[:150]
    return '采集异常：'+type(error).__name__
