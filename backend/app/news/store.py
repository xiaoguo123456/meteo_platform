"""单机资讯存储；采集独立进程写入，接口只读结果。"""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(os.getenv('NEWS_DATA_DIR', str(Path(__file__).resolve().parents[3]/'data/news')))
CHANNELS = {'rules':'两个细则','forecast':'功率预测','market':'电力交易','ai':'气象大模型'}


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


@contextmanager
def db():
    ROOT.mkdir(parents=True,exist_ok=True)
    connection=sqlite3.connect(ROOT/'news.sqlite',timeout=15)
    connection.row_factory=sqlite3.Row
    connection.execute('PRAGMA journal_mode=WAL')
    connection.execute('PRAGMA busy_timeout=15000')
    try:
        yield connection
        connection.commit()
    finally:connection.close()


def initialize():
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY,name TEXT,url TEXT,kind TEXT,region TEXT,tier TEXT,
          checked_at TEXT,success_at TEXT,error TEXT,candidates INTEGER DEFAULT 0,added INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS articles(id TEXT PRIMARY KEY,source_id TEXT,url TEXT UNIQUE,title TEXT,
          published_at TEXT,date_basis TEXT,discovered_at TEXT,updated_at TEXT,channel TEXT,region TEXT,
          body TEXT,body_hash TEXT,excerpt TEXT,summary TEXT DEFAULT '',ai_state TEXT DEFAULT 'pending',
          ai_error TEXT,score INTEGER DEFAULT 0,tags TEXT DEFAULT '[]',facts TEXT DEFAULT '{}',
          attachments TEXT DEFAULT '[]',duplicate_of TEXT,hidden INTEGER DEFAULT 0);
        CREATE INDEX IF NOT EXISTS articles_channel ON articles(channel,published_at);
        CREATE INDEX IF NOT EXISTS articles_body_hash ON articles(body_hash);
        CREATE TABLE IF NOT EXISTS revisions(id INTEGER PRIMARY KEY,article_id TEXT,body_hash TEXT,body TEXT,recorded_at TEXT);
        CREATE TABLE IF NOT EXISTS usage(day TEXT PRIMARY KEY,calls INTEGER DEFAULT 0,reserved_tokens INTEGER DEFAULT 0,
          actual_tokens INTEGER DEFAULT 0,failures INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY,value TEXT);
        CREATE TABLE IF NOT EXISTS policy_documents(
          id TEXT PRIMARY KEY,title TEXT NOT NULL,area_type TEXT NOT NULL DEFAULT 'province',
          region TEXT NOT NULL,province TEXT NOT NULL DEFAULT '',document_type TEXT NOT NULL DEFAULT '两个细则',
          status TEXT NOT NULL DEFAULT '有效',issuer TEXT NOT NULL DEFAULT '',issued_at TEXT,
          effective_at TEXT,scope TEXT NOT NULL DEFAULT '',summary TEXT NOT NULL DEFAULT '',
          url TEXT NOT NULL,attachment_url TEXT NOT NULL DEFAULT '',tags TEXT NOT NULL DEFAULT '[]',
          updated_at TEXT NOT NULL,version_type TEXT NOT NULL DEFAULT 'current',
          supersedes_id TEXT NOT NULL DEFAULT '',preview_url TEXT NOT NULL DEFAULT '',
          ai_summary TEXT NOT NULL DEFAULT '',ai_points TEXT NOT NULL DEFAULT '[]',
          ai_state TEXT NOT NULL DEFAULT 'pending'
        );
        CREATE INDEX IF NOT EXISTS policy_documents_region ON policy_documents(region,province,status);
        ''')
        # 兼容已部署的旧 SQLite，资料库字段随版本增量迁移。
        existing={r[1] for r in c.execute('PRAGMA table_info(policy_documents)').fetchall()}
        for name,definition in {
            'version_type':"TEXT NOT NULL DEFAULT 'current'",
            'supersedes_id':"TEXT NOT NULL DEFAULT ''",
            'preview_url':"TEXT NOT NULL DEFAULT ''",
            'ai_summary':"TEXT NOT NULL DEFAULT ''",
            'ai_points':"TEXT NOT NULL DEFAULT '[]'",
            'ai_state':"TEXT NOT NULL DEFAULT 'pending'",
        }.items():
            if name not in existing:c.execute(f'ALTER TABLE policy_documents ADD COLUMN {name} {definition}')
        policy_path = Path(__file__).with_name('policies.json')
        if policy_path.exists():
            stamp = now()
            for item in json.loads(policy_path.read_text()):
                c.execute('''INSERT INTO policy_documents
                  (id,title,area_type,region,province,document_type,status,issuer,issued_at,effective_at,scope,summary,url,attachment_url,tags,updated_at,version_type,supersedes_id,preview_url,ai_summary,ai_points,ai_state)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                  ON CONFLICT(id) DO UPDATE SET title=excluded.title,area_type=excluded.area_type,
                  region=excluded.region,province=excluded.province,document_type=excluded.document_type,
                  status=excluded.status,issuer=excluded.issuer,issued_at=excluded.issued_at,
                  effective_at=excluded.effective_at,scope=excluded.scope,summary=excluded.summary,
                  url=excluded.url,attachment_url=excluded.attachment_url,tags=excluded.tags,updated_at=excluded.updated_at,
                  version_type=excluded.version_type,supersedes_id=excluded.supersedes_id,preview_url=excluded.preview_url,
                  ai_summary=CASE WHEN excluded.ai_summary!='' THEN excluded.ai_summary ELSE policy_documents.ai_summary END,
                  ai_points=CASE WHEN excluded.ai_points!='[]' THEN excluded.ai_points ELSE policy_documents.ai_points END,
                  ai_state=CASE WHEN excluded.ai_summary!='' THEN excluded.ai_state ELSE policy_documents.ai_state END''',
                  (item['id'],item['title'],item.get('area_type','province'),item['region'],item.get('province',''),
                   item.get('document_type','两个细则'),item.get('status','有效'),item.get('issuer',''),item.get('issued_at'),
                   item.get('effective_at'),item.get('scope',''),item.get('summary',''),item['url'],item.get('attachment_url',''),
                   json.dumps(item.get('tags',[]),ensure_ascii=False),stamp,item.get('version_type','current'),item.get('supersedes_id',''),
                   item.get('preview_url') or item.get('attachment_url') or '',item.get('ai_summary',''),
                   json.dumps(item.get('ai_points',[]),ensure_ascii=False),item.get('ai_state','pending')))


def reserve_call(tokens):
    day=now()[:10]
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        c.execute('INSERT OR IGNORE INTO usage(day) VALUES(?)',(day,))
        u=c.execute('SELECT * FROM usage WHERE day=?',(day,)).fetchone()
        call_limit=int(os.getenv('NEWS_LLM_DAILY_CALLS','0'))
        token_limit=int(os.getenv('NEWS_LLM_DAILY_TOKENS','0'))
        if (call_limit>0 and u['calls']>=call_limit) or (token_limit>0 and u['reserved_tokens']+tokens>token_limit):return False
        c.execute('UPDATE usage SET calls=calls+1,reserved_tokens=reserved_tokens+? WHERE day=?',(tokens,day))
    return True


def state(key,value):
    with db() as c:c.execute('INSERT OR REPLACE INTO state VALUES(?,?)',(key,json.dumps(value,ensure_ascii=False)))


def public_article(row,detail=False):
    v=dict(row)
    for name in ['tags','facts','attachments']:v[name]=json.loads(v[name])
    # 正文只作内部提取、核验；公开页面不转载全文。
    for name in ['body','body_hash','ai_error']:v.pop(name,None)
    if not detail:v.pop('facts',None);v.pop('attachments',None)
    return v


def public_policy(row,detail=False):
    value=dict(row)
    value['tags']=json.loads(value.get('tags') or '[]')
    value['ai_points']=json.loads(value.get('ai_points') or '[]')
    if not detail:
        value.pop('attachment_url',None)
    return value
