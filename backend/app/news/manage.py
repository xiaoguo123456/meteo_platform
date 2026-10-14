"""服务器内管理命令，不暴露公网写接口。"""
import argparse,json
from pathlib import Path
from .store import db,initialize,CHANNELS
p=argparse.ArgumentParser(description='资讯内容维护');p.add_argument('action',choices=['hide','restore','retry','classify','sources']);p.add_argument('id',nargs='?');p.add_argument('--channel',choices=list(CHANNELS));a=p.parse_args();initialize()
if a.action=='sources':
    active={s['id'] for s in json.loads(Path(__file__).with_name('sources.json').read_text())}
    with db() as c:
        for row in c.execute('SELECT id,name,checked_at,error FROM sources ORDER BY id'):
            if row['id'] in active:print(json.dumps(dict(row),ensure_ascii=False))
    raise SystemExit(0)
if not a.id:raise SystemExit('需要指定资讯编号')
with db() as c:
    row=c.execute('SELECT id FROM articles WHERE id=?',(a.id,)).fetchone()
    if not row:raise SystemExit('资讯不存在')
    if a.action in ('hide','restore'):c.execute('UPDATE articles SET hidden=? WHERE id=?',(int(a.action=='hide'),a.id))
    elif a.action=='retry':c.execute("UPDATE articles SET ai_state='pending',ai_error=NULL WHERE id=?",(a.id,))
    elif not a.channel:raise SystemExit('需要指定 --channel')
    else:c.execute('UPDATE articles SET channel=? WHERE id=?',(a.channel,a.id))
print('资讯已更新')
