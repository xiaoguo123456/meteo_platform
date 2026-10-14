from fastapi import APIRouter, HTTPException, Query
from .store import db, initialize, public_article, public_policy, CHANNELS
router=APIRouter(prefix='/api/news')

@router.get('')
def listing(channel:str='',region:str='',q:str=Query('',max_length=100),sort:str='latest',page:int=Query(1,ge=1),limit:int=Query(20,ge=1,le=50)):
    initialize()
    where=['a.hidden=0','a.duplicate_of IS NULL'];args=[]
    if channel:
        if channel not in CHANNELS:raise HTTPException(400,'频道无效')
        where.append('a.channel=?');args.append(channel)
    if region:where.append('a.region LIKE ?');args.append('%'+region+'%')
    if q:
        where.append('(a.title LIKE ? OR a.summary LIKE ? OR a.excerpt LIKE ?)');args.extend(['%'+q+'%']*3)
    condition=' AND '.join(where)
    order='a.score DESC,' if sort=='selected' else ''
    with db() as c:
        total=c.execute('SELECT count(*) FROM articles a WHERE '+condition,args).fetchone()[0]
        rows=c.execute('SELECT a.*,s.name source_name,s.tier source_tier FROM articles a JOIN sources s ON s.id=a.source_id WHERE '+condition+' ORDER BY '+order+"coalesce(a.published_at,'') DESC,a.discovered_at DESC LIMIT ? OFFSET ?",args+[limit,(page-1)*limit]).fetchall()
        regions=[r[0] for r in c.execute("SELECT DISTINCT region FROM articles WHERE hidden=0 AND region!='' ORDER BY region")]
    return {'items':[public_article(r) for r in rows],'total':total,'page':page,'regions':regions,'channels':CHANNELS}


@router.get('/policies')
def policies(region:str='',province:str='',status:str='',version_type:str='',q:str=Query('',max_length=100),page:int=Query(1,ge=1),limit:int=Query(30,ge=1,le=50)):
    """两个细则资料库；资料配置由服务器维护，公开接口只读。"""
    initialize()
    where=['1=1'];args=[]
    if region:where.append('(region=? OR province=?)');args.extend([region,region])
    if province:where.append('province=?');args.append(province)
    if status:where.append('status=?');args.append(status)
    if version_type:where.append('version_type=?');args.append(version_type)
    if q:
        where.append('(title LIKE ? OR summary LIKE ? OR scope LIKE ? OR tags LIKE ?)')
        args.extend(['%'+q+'%']*4)
    condition=' AND '.join(where)
    with db() as c:
        total=c.execute('SELECT count(*) FROM policy_documents WHERE '+condition,args).fetchone()[0]
        rows=c.execute('SELECT * FROM policy_documents WHERE '+condition+
                       ' ORDER BY CASE status WHEN \'正式执行\' THEN 0 WHEN \'修订实施\' THEN 1 WHEN \'征求意见\' THEN 2 ELSE 3 END,coalesce(effective_at,issued_at) DESC LIMIT ? OFFSET ?',
                       args+[limit,(page-1)*limit]).fetchall()
        regions=[r[0] for r in c.execute("SELECT DISTINCT region FROM policy_documents ORDER BY region")]
        provinces=[r[0] for r in c.execute("SELECT DISTINCT province FROM policy_documents WHERE province!='' ORDER BY province")]
        statuses=[r[0] for r in c.execute("SELECT DISTINCT status FROM policy_documents ORDER BY status")]
        version_types=[r[0] for r in c.execute("SELECT DISTINCT version_type FROM policy_documents ORDER BY version_type")]
    return {'items':[public_policy(r) for r in rows],'total':total,'page':page,'regions':regions,'provinces':provinces,'statuses':statuses,'version_types':version_types}

@router.get('/{article_id}')
def article(article_id:str):
    initialize()
    with db() as c:
        row=c.execute('SELECT a.*,s.name source_name,s.tier source_tier FROM articles a JOIN sources s ON s.id=a.source_id WHERE a.id=? AND a.hidden=0',(article_id,)).fetchone()
        if not row:raise HTTPException(404,'资讯不存在')
        related=c.execute('SELECT id,title,url FROM articles WHERE duplicate_of=? AND hidden=0',(article_id,)).fetchall()
        revisions=c.execute('SELECT recorded_at FROM revisions WHERE article_id=? ORDER BY id DESC',(article_id,)).fetchall()
    return {**public_article(row,True),'related':[dict(r) for r in related],'revisions':[r[0] for r in revisions]}


@router.get('/policies/{policy_id}')
def policy(policy_id:str):
    initialize()
    with db() as c:
        row=c.execute('SELECT * FROM policy_documents WHERE id=?',(policy_id,)).fetchone()
    if not row:raise HTTPException(404,'政策资料不存在')
    return public_policy(row,True)
