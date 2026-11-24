"""Run state, review flags, attestations and request log, stored beside the data they describe."""
import json
from pathlib import Path
import sqlite3

from .paths import ROOT

MIGRATION='002_pipeline'

from .io import now

def connect(path):
    db=sqlite3.connect(path);db.row_factory=sqlite3.Row;db.execute('PRAGMA foreign_keys=ON');return db

def init_staging(path,root=ROOT):
    """Create a staging database: the research schema plus the pipeline migration."""
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    db=connect(path)
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='table_a_exam_level'").fetchone():
        db.executescript((Path(root)/'schemas/research_schema.sql').read_text(encoding='utf-8'))
    migrate(db,root)
    return db

MIGRATIONS=[('002_pipeline','002_pipeline.sql')]

def migrate(db,root=ROOT):
    """Apply every additive migration not yet recorded. Returns True if anything was applied."""
    applied=False
    for name,file in MIGRATIONS:
        have=db.execute("SELECT 1 FROM sqlite_master WHERE name='schema_migrations'").fetchone() and db.execute('SELECT 1 FROM schema_migrations WHERE version=?',(name,)).fetchone()
        if have:continue
        db.executescript((Path(root)/'schemas/migrations'/file).read_text(encoding='utf-8'))
        with db:db.execute('INSERT OR IGNORE INTO schema_migrations VALUES (?,?)',(name,now()))
        applied=True
    return applied

def set_status(db,run_id,pe_id,status,detail=None):
    with db:
        db.execute('INSERT INTO doc_status VALUES (?,?,?,?,?) ON CONFLICT(run_id,pe_id) DO UPDATE SET status=excluded.status,detail=excluded.detail,updated_at=excluded.updated_at',
                   (run_id,pe_id,status,detail,now()))

def get_status(db,run_id,pe_id):
    row=db.execute('SELECT status FROM doc_status WHERE run_id=? AND pe_id=?',(run_id,pe_id)).fetchone()
    return row['status'] if row else 'unprocessed'

def add_flags(db,run_id,pe_id,flags):
    with db:
        db.execute("DELETE FROM review_flags WHERE run_id=? AND pe_id=? AND status='open'",(run_id,pe_id))
        for f in flags:
            f=dict(f)
            kind=f.pop('kind');table=f.pop('table',None);record=f.pop('record',None);field=f.pop('field',None)
            page=f.pop('page',None)
            db.execute('INSERT INTO review_flags(run_id,pe_id,kind,table_name,record_id,field_name,pdf_page,detail,created_at) VALUES (?,?,?,?,?,?,?,?,?)',
                       (run_id,pe_id,kind,table,record,field,page if isinstance(page,int) else None,json.dumps(f,sort_keys=True,default=str),now()))

def open_flags(db,run_id,pe_id):
    return [dict(r) for r in db.execute("SELECT * FROM review_flags WHERE run_id=? AND pe_id=? AND status='open'",(run_id,pe_id))]

def log_request(db,**kw):
    cols=['run_id','pe_id','target','window','task_key','cache_key','model','prompt_hash','schema_hash','effort','max_tokens','status','cache_hit','cost_usd','usage_json','api_request_id','raw_path','error','seconds']
    row={c:kw.get(c) for c in cols}
    row['cache_hit']=int(bool(row['cache_hit']));row['window']=str(row['window'])
    if row['usage_json'] is not None and not isinstance(row['usage_json'],str):row['usage_json']=json.dumps(row['usage_json'])
    with db:
        db.execute(f"INSERT INTO model_requests({','.join(cols)},created_at) VALUES ({','.join('?' for _ in cols)},?)",[*[row[c] for c in cols],now()])
