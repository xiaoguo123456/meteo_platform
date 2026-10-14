"""部署服务器上实测栏目和相关文章；仅供服务器命令行维护。"""
import argparse,asyncio,json
from pathlib import Path
import feedparser,httpx
from bs4 import BeautifulSoup
from .collector import Fetcher,candidates,category,extract,safe_error,allowed

async def audit(sources):
    sem=asyncio.Semaphore(3)
    async with httpx.AsyncClient(timeout=25,headers={'User-Agent':'QingchuanNews/1.0'}) as client:
        async def check(source):
            async with sem:
                result={'id':source['id'],'url':source['url'],'samples':[],'error':None}
                try:
                    fetcher=Fetcher(client)
                    data,_,url=await fetcher.get(source['url'])
                    if source['kind']=='rss':
                        feed=feedparser.parse(data)
                        for e in feed.entries:
                            body=BeautifulSoup(e.get('summary',''),'html.parser').get_text(' ',strip=True)
                            if allowed(e.link,source) and len(body)>=100 and (source.get('dedicated') or category(e.title,body)):
                                result['samples'].append({'title':e.title,'url':e.link,'length':len(body)})
                                if len(result['samples'])>=2:break
                    else:
                        pairs=candidates(data,source,url)
                        # 只验栏目实际发现的链接，固定种子不作为栏目可用证据。
                        for link,title in pairs[:8]:
                            try:
                                raw,_,resolved=await fetcher.get(link);doc=extract(raw,resolved)
                                if not doc['title']:doc['title']=title
                                if len(doc['body'])>=100 and category(doc['title'],doc['body']):
                                    result['samples'].append({'title':doc['title'],'url':resolved,'length':len(doc['body'])})
                                    if len(result['samples'])>=2:break
                            except Exception:continue
                    if not result['samples']:result['error']='本轮未取得有效相关文章'
                except Exception as e:result['error']=safe_error(e)
                print(json.dumps(result,ensure_ascii=False),flush=True)
                return result
        return await asyncio.gather(*(check(s) for s in sources))

if __name__=='__main__':
    p=argparse.ArgumentParser(description='信源可用性验收');p.add_argument('--config',default=str(Path(__file__).with_name('sources.json')));p.add_argument('--output',required=True);a=p.parse_args()
    Path(a.output).write_text(json.dumps(asyncio.run(audit(json.loads(Path(a.config).read_text()))),ensure_ascii=False,indent=2))
