"""Human review states, attestation, acceptance into the research database, and freezing.

States: staged -> reviewed -> accepted. Only a person runs `review` commands. Mock runs can never
be accepted. Acceptance is atomic per evaluation, backed up first, and refuses open blocking flags."""
from contextlib import closing
import datetime as dt
from pathlib import Path
import sqlite3

from .io import fingerprint,read_json,sha256_file
from .paths import ROOT
from .research import TABLES
from . import reviewstore,runstate

# ERROR: the stored data is wrong or missing something it must have. Stops acceptance.
ERROR_KINDS={'task_failed','identity_mismatch','missing_evidence','impossible_percent','impossible_count','no_exam_facts',
             'rating_differs_from_ffiec','exam_type_differs_from_ffiec','rating_out_of_set'}
# REVIEW: the data is stored and flagged; a person should look. Travels with the data; stops only a VALIDATED label.
REVIEW_KINDS={'image_review_required','percent_sum','total_mismatch','date_inconsistent','missing_table_family','run_disagreement','critical_conflict'}
BLOCKING=ERROR_KINDS|REVIEW_KINDS   # everything that must be clear for a VALIDATED export

def flag_counts(db):
    """Open flags by level. Works on any database that has review_flags."""
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='review_flags'").fetchone():return dict(errors=0,review=0)
    k=[r[0] for r in db.execute("SELECT kind FROM review_flags WHERE status='open'")]
    return dict(errors=sum(x in ERROR_KINDS for x in k),review=sum(x in REVIEW_KINDS for x in k))

def resolve_flag(db,flag_id,status,note,store=None,reviewer=''):
    """Resolve or waive one open flag. The decision is saved in the durable review store, keyed by what the flag is
    about, so it is applied again after the extraction database is rebuilt (unless the flagged thing changed)."""
    if status not in ('resolved','waived'):raise ValueError('status must be resolved or waived')
    if not note or len(note.strip())<5:raise ValueError('A resolution note is required')
    row=db.execute("SELECT * FROM review_flags WHERE flag_id=? AND status='open'",(flag_id,)).fetchone()
    if not row:raise ValueError('No such open flag')
    own=store is None;store=store or reviewstore.open_store()
    try:store.decide(reviewstore.flag_key(db,row),status,note,reviewer,row['detail'])
    finally:
        if own:store.close()
    with db:db.execute("UPDATE review_flags SET status=?,resolution=? WHERE flag_id=?",(status,note.strip(),flag_id))

def apply_decisions(db,store,run_id=None,pe_id=None):
    """Re-apply saved decisions to freshly generated flags. A decision is applied only if the flag still looks the same;
    otherwise the flag stays open and says 're-check'. Page attestations resolve their image-review flags."""
    q="SELECT * FROM review_flags WHERE status='open'"+(' AND run_id=?' if run_id else '')+(' AND pe_id=?' if pe_id else '')
    args=[x for x in (run_id,pe_id) if x];dec=store.decisions();cache={};sha={}
    n=dict(applied=0,recheck=0,attested=0)
    for f in db.execute(q,args).fetchall():
        if f['kind']=='image_review_required':
            if f['pe_id'] not in sha:sha[f['pe_id']]=None
            continue   # handled below by page
        d=dec.get(reviewstore.flag_key(db,f,cache))
        if not d:continue
        if d['detail_hash']==reviewstore.detail_hash(f['detail']):
            with db:db.execute("UPDATE review_flags SET status=?,resolution=? WHERE flag_id=?",(d['status'],f"{d['note']} ({d['reviewer']}, {d['decided_at'][:10]})",f['flag_id']))
            n['applied']+=1
        else:
            with db:db.execute("UPDATE review_flags SET resolution=? WHERE flag_id=?",('re-check: this changed since it was decided ('+d['status']+': '+d['note']+')',f['flag_id']));n['recheck']+=1
    for pe,_ in list(sha.items()):
        shas=[r[0] for r in store.db.execute('SELECT DISTINCT pdf_sha256 FROM attestations WHERE pe_id=?',(pe,))]
        pages=set()
        for s in shas:pages|=store.attested_pages(pe,s)
        if pages:
            with db:
                for p in pages:
                    c=db.execute("UPDATE review_flags SET status='resolved',resolution='attested by a person (review store)' WHERE pe_id=? AND kind='image_review_required' AND pdf_page=? AND status='open'",(pe,p)).rowcount
                    n['attested']+=c
    return n

def attest_pages(db,pe_id,sha,pages,reviewer,note=None,store=None):
    own=store is None;store=store or reviewstore.open_store()
    try:store.attest(pe_id,sha,sorted(set(pages)),reviewer,note)
    finally:
        if own:store.close()
    with db:
        for p in pages:
            db.execute("UPDATE review_flags SET status='resolved',resolution=? WHERE pe_id=? AND kind='image_review_required' AND pdf_page=? AND status='open'",
                       (f'attested by {reviewer.strip()}',pe_id,p))

def mark_reviewed(db,run_id,pe_id,strict=False):
    if runstate.get_status(db,run_id,pe_id)!='staged':raise ValueError('Only a staged, complete evaluation can be marked reviewed')
    flags=runstate.open_flags(db,run_id,pe_id);blockers=[f for f in flags if f['kind'] in (BLOCKING if strict else ERROR_KINDS)]
    if blockers:raise ValueError(f'{len(blockers)} flags are open that must be fixed first: '+', '.join(sorted({f["kind"] for f in blockers})))
    left=sum(f['kind'] in REVIEW_KINDS for f in flags)
    runstate.set_status(db,run_id,pe_id,'reviewed','marked reviewed by a person'+(f' with {left} review flags still open' if left else ''))

def accept(staging_path,research_path,run_id,pe_id,root=ROOT,backup_dir=None,strict=False):
    if run_id.startswith('MOCK'):raise ValueError('Mock rehearsal output can never be accepted')
    research_path=Path(research_path)
    with closing(runstate.connect(staging_path)) as s:
        if runstate.get_status(s,run_id,pe_id)!='reviewed':raise ValueError('Evaluation must be marked reviewed first')
        if [f for f in runstate.open_flags(s,run_id,pe_id) if f['kind'] in (BLOCKING if strict else ERROR_KINDS)]:raise ValueError('Error-level flags are open (the data is wrong or incomplete); fix or resolve them first')
    backup=None
    if research_path.is_file():
        backup=Path(backup_dir or Path(root)/'data/backups')/f'research_{dt.datetime.now(dt.timezone.utc):%Y%m%dT%H%M%S}.sqlite'
        backup.parent.mkdir(parents=True,exist_ok=True)
        with closing(sqlite3.connect(research_path)) as src,closing(sqlite3.connect(backup)) as dst:src.backup(dst)
    with closing(runstate.connect(research_path)) as db:
        runstate.migrate(db,root)
        db.execute('ATTACH DATABASE ? AS s',(str(staging_path),))
        try:
            with db:
                db.execute('DELETE FROM field_evidence WHERE pe_id=?',(pe_id,))
                for t in reversed(TABLES):db.execute(f'DELETE FROM {t} WHERE pe_id=?',(pe_id,))
                for t in [*TABLES,'field_evidence']:
                    db.execute(f'INSERT INTO main.{t} SELECT * FROM s.{t} WHERE pe_id=?',(pe_id,))
                _store=reviewstore.open_store(root)
                for _r in _store.db.execute("SELECT * FROM attestations WHERE pe_id=?",(pe_id,)):db.execute("INSERT OR REPLACE INTO main.reviewer_attestations(pe_id,pdf_sha256,pdf_page,reviewer,reviewed_at,note) VALUES (?,?,?,?,?,?)",tuple(_r))
                _store.close()
                db.execute('DELETE FROM main.review_flags WHERE run_id=? AND pe_id=?',(run_id,pe_id))
                db.execute('INSERT INTO main.review_flags(run_id,pe_id,kind,table_name,record_id,field_name,pdf_page,detail,status,resolution,created_at) SELECT run_id,pe_id,kind,table_name,record_id,field_name,pdf_page,detail,status,resolution,created_at FROM s.review_flags WHERE run_id=? AND pe_id=?',(run_id,pe_id))
                bad=db.execute('PRAGMA foreign_key_check').fetchall()
                if bad:raise ValueError('Foreign key violations; acceptance rolled back')
                db.execute('INSERT OR REPLACE INTO main.doc_status VALUES (?,?,?,?,?)',(run_id,pe_id,'accepted','accepted into research database',runstate.now()))
        finally:
            db.execute('DETACH DATABASE s')
    with closing(runstate.connect(staging_path)) as s:runstate.set_status(s,run_id,pe_id,'accepted')
    return dict(pe_id=pe_id,backup=str(backup) if backup else None)

# ---------- freeze ----------
def freeze_state(provider,effort,root=ROOT,efforts=None):
    from . import tasks as T,pipeline
    from .prepare import parser_info
    cols=T.research_columns(root);p=T.prompts()
    return dict(model=provider.model,price_version=provider.price_version,effort=effort,efforts=dict(sorted((efforts or {}).items())),
                prompts={k:v['hash'] for k,v in p.items() if k!='d_columns'},   # the opt-in categories-across step is not part of the default configuration
                schemas={t:fingerprint(T.schema_for(t,cols)) for t in ('a','b','c','e','peers','d')},
                max_tokens={k:v for k,v in T.MAX_TOKENS.items() if k not in T.OPTIONAL_TARGETS},max_chars=T.MAX_CHARS,code=pipeline.code_version(),parser=parser_info()['fingerprint'],
                field_inventory=sha256_file(Path(root)/'config/field_inventory.json'),
                research_schema=sha256_file(Path(root)/'schemas/research_schema.sql'))

FROZEN_KEYS=('model','effort','efforts','prompts','schemas','max_tokens','max_chars','parser')   # what changes the model's output or its inputs

def freeze(path,provider,effort,note,root=ROOT,efforts=None):
    """Record the configuration. Only FROZEN_KEYS are enforced later; the code version is recorded for information, so
    fixing merge or validation code never invalidates a freeze."""
    from .io import write_json_new
    state=freeze_state(provider,effort,root,efforts);state['frozen_at']=runstate.now();state['note']=note;state['frozen_keys']=list(FROZEN_KEYS)
    state['freeze_hash']=fingerprint({k:state[k] for k in FROZEN_KEYS})
    state['path']=str(write_json_new(path,state));return state

def verify_freeze(path,provider,effort,root=ROOT,efforts=None):
    saved=read_json(path);now=freeze_state(provider,effort,root,efforts)
    diff=[k for k in FROZEN_KEYS if saved.get(k)!=now[k]]
    if diff:raise ValueError('The model-facing configuration differs from the frozen one: '+', '.join(diff))
    return saved

# ---------- corrections (adjudication): the original extraction is never overwritten ----------
def add_correction(db,bundle,pe_id,table,record_id,field,new_value,page,quote,reason,reviewer,store=None):
    """Record a person's correction in the review store. The new value must be supported by a quote on the cited page,
    like any extracted value; reason and reviewer are mandatory. The extraction itself is untouched."""
    from .research import TABLES,check_field,columns
    if table not in TABLES:raise ValueError('Unknown table')
    pk,refs=TABLES[table]
    if field in {pk,*refs}:raise ValueError('Identifier columns cannot be corrected')
    if not reviewer or not reviewer.strip():raise ValueError('Reviewer name required')
    if not reason or len(reason.strip())<10:raise ValueError('A written reason (10+ characters) is required')
    cols=columns(db,table)
    if field not in cols:raise ValueError('Unknown field')
    row=db.execute(f'SELECT * FROM {table} WHERE {pk}=? AND pe_id=?',(record_id,pe_id)).fetchone() if table!='table_a_exam_level' else db.execute(f'SELECT * FROM {table} WHERE pe_id=?',(pe_id,)).fetchone()
    if row is None:raise ValueError('No such record in this evaluation')
    old=row[field]
    value=new_value
    if new_value is not None and cols[field] in ('INTEGER','NUMERIC','REAL'):
        from .research import number_from
        n=number_from(new_value);value=int(n) if cols[field]=='INTEGER' else float(n)
    if value is not None:
        item=dict(value=value,page=page,quote=quote,value_as_printed=new_value if cols[field] in ('INTEGER','NUMERIC','REAL') else None)
        value,_,_=check_field(table,field,cols[field],item,{p['page']:p for p in bundle['pages']},frozenset({page}))   # same evidence rules; the person vouches for image pages
    own=store is None;store=store or reviewstore.open_store()
    try:
        key=reviewstore.stable_keys(db,pe_id,table).get(record_id,record_id)
        store.add_correction(pe_id,table,key,field,None if old is None else str(old),None if value is None else str(value),page,quote,reason.strip(),reviewer.strip())
    finally:
        if own:store.close()

def apply_corrections(src_path,dst_path,store=None):
    """Write a COPY of the database with the saved corrections applied (latest wins) and their evidence replaced.
    A correction is applied only if the row still exists and its value is what the person saw (or already their value);
    otherwise it is reported for re-check. Returns dict(applied, recheck, orphans)."""
    from .research import TABLES,columns
    dst_path=Path(dst_path)
    if dst_path.exists():raise FileExistsError(str(dst_path))
    own=store is None;store=store or reviewstore.open_store()
    with closing(sqlite3.connect(src_path)) as s,closing(sqlite3.connect(dst_path)) as d:s.backup(d)
    out=dict(applied=0,recheck=[],orphans=[])
    try:
        with closing(runstate.connect(dst_path)) as db:
            cols_of={t:columns(db,t) for t in TABLES};maps={}
            for c in store.corrections():
                t=c['table_name'];k=(c['pe_id'],t)
                if k not in maps:maps[k]={v:i for i,v in reviewstore.stable_keys(db,*k).items()}
                rid=maps[k].get(c['record_key'])
                if rid is None:out['orphans'].append(c['correction_id']);continue
                pk,_=TABLES[t];typ=cols_of[t][c['field_name']]
                where,arg=(f"{pk}=?",rid) if t!='table_a_exam_level' else ('pe_id=?',c['pe_id'])
                cur=db.execute(f"SELECT {c['field_name']} FROM {t} WHERE {where}",(arg,)).fetchone()[0]
                cur_s=None if cur is None else str(cur)
                if cur_s not in (c['old_value'],c['new_value']):out['recheck'].append(c['correction_id']);continue
                v=c['new_value']
                if v is not None and typ=='INTEGER':v=int(float(v))
                elif v is not None and typ in('NUMERIC','REAL'):v=float(v)
                with db:
                    db.execute(f"UPDATE {t} SET {c['field_name']}=? WHERE {where}",(v,arg))
                    db.execute('DELETE FROM field_evidence WHERE table_name=? AND record_id=? AND field_name=?',(t,rid,c['field_name']))
                    if v is not None:
                        from .__main__ import digest
                        db.execute('INSERT INTO field_evidence(evidence_id,pe_id,table_name,record_id,field_name,pdf_page,printed_page_label,evidence_verbatim,value_as_printed) VALUES (?,?,?,?,?,?,?,?,?)',
                                   (digest(f"corr|{c['correction_id']}".encode()),c['pe_id'],t,rid,c['field_name'],c['pdf_page'],None,c['evidence_verbatim'],c['new_value']))
                out['applied']+=1
    finally:
        if own:store.close()
    return out
