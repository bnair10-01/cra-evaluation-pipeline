"""Durable store for HUMAN decisions: flag resolutions, page attestations, corrections, vision-check advice.

Lives in data/review.sqlite and is never rebuilt, so extraction databases can be deleted and regenerated at will.
Records are keyed by content (not by position) so a decision follows its row across a rebuild; if the thing it
was about has changed, it is shown as 're-check' instead of being applied. A CSV copy is written to
reviews/decisions/ after every change so the decisions are readable and diffable outside the database."""
import csv
from collections import Counter
import hashlib
import os
from pathlib import Path
import sqlite3

from .io import atomic_write_text
from .paths import ROOT
from .research import TABLES,norm

SCHEMA='''
CREATE TABLE IF NOT EXISTS flag_decisions (
    flag_key TEXT PRIMARY KEY, status TEXT NOT NULL CHECK (status IN ('resolved','waived')),
    note TEXT NOT NULL, reviewer TEXT NOT NULL, detail_hash TEXT NOT NULL, decided_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS attestations (
    pe_id TEXT NOT NULL, pdf_sha256 TEXT NOT NULL, pdf_page INTEGER NOT NULL CHECK (pdf_page >= 1),
    reviewer TEXT NOT NULL, reviewed_at TEXT NOT NULL, note TEXT, PRIMARY KEY (pe_id, pdf_sha256, pdf_page));
CREATE TABLE IF NOT EXISTS corrections (
    correction_id INTEGER PRIMARY KEY AUTOINCREMENT, pe_id TEXT NOT NULL, table_name TEXT NOT NULL, record_key TEXT NOT NULL,
    field_name TEXT NOT NULL, old_value TEXT, new_value TEXT, pdf_page INTEGER NOT NULL CHECK (pdf_page >= 1),
    evidence_verbatim TEXT NOT NULL, reason TEXT NOT NULL, reviewer TEXT NOT NULL, corrected_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS vision_checks (
    pe_id TEXT NOT NULL, pdf_page INTEGER NOT NULL, table_name TEXT NOT NULL, record_key TEXT NOT NULL, field_name TEXT NOT NULL,
    quote TEXT, verdict TEXT NOT NULL CHECK (verdict IN ('supported','not_found','different','unreadable')), seen_text TEXT,
    model TEXT NOT NULL, checked_at TEXT NOT NULL, PRIMARY KEY (pe_id, pdf_page, table_name, record_key, field_name));
'''
CSV_TABLES=('flag_decisions','attestations','corrections','vision_checks')

from .io import now

def detail_hash(detail):
    return hashlib.sha256((detail or '').encode('utf-8')).hexdigest()[:16]

def stable_keys(db,pe_id,table):
    """record_id -> key that survives a rebuild. Only conclusions are numbered by position (E:0001, ...);
    they are keyed by cited page, phrase and context, with an ordinal for exact repeats."""
    pk=TABLES[table][0]
    if table!='table_e_examiner_conclusions':
        return {r[0]:r[0] for r in db.execute(f'select {pk} from {table} where pe_id=?',(pe_id,))}
    seen=Counter();out={}
    for r in db.execute("""select e.conclusion_id i,e.label_verbatim l,e.criterion c,e.category g,
        (select min(pdf_page) from field_evidence f where f.record_id=e.conclusion_id and f.field_name='label_verbatim') p
        from table_e_examiner_conclusions e where e.pe_id=? order by e.conclusion_id""",(pe_id,)):
        base=f"E|p{r['p']}|{norm(r['l'] or '')}|{norm(r['c'] or '')}|{norm(r['g'] or '')}"
        seen[base]+=1;out[r['i']]=f'{base}|{seen[base]}'
    return out

def flag_key(db,flag,cache=None):
    """Identity of a flag across rebuilds: what, where (by stable row key), which field, which page."""
    cache=cache if cache is not None else {}
    rk=''
    if flag['table_name'] and flag['record_id']:
        k=(flag['pe_id'],flag['table_name'])
        if k not in cache:cache[k]=stable_keys(db,*k)
        rk=cache[k].get(flag['record_id'],flag['record_id'])
    return '|'.join(str(x if x is not None else '') for x in (flag['pe_id'],flag['kind'],flag['table_name'],rk,flag['field_name'],flag['pdf_page']))

class Store:
    def __init__(self,db,mirror_dir=None):
        self.db=db;self.mirror_dir=Path(mirror_dir) if mirror_dir else None
    def close(self):self.db.close()
    def _changed(self):
        self.db.commit()
        if self.mirror_dir:self.export_csv(self.mirror_dir)
    # attestations: a person compared a page's text layer with its image
    def attest(self,pe_id,sha,pages,reviewer,note=None):
        if not reviewer or not reviewer.strip():raise ValueError('Reviewer name required')
        for p in pages:
            self.db.execute('INSERT OR REPLACE INTO attestations VALUES (?,?,?,?,?,?)',(pe_id,sha,int(p),reviewer.strip(),now(),note))
        self._changed()
    def attested_pages(self,pe_id,sha):
        return {r[0] for r in self.db.execute('SELECT pdf_page FROM attestations WHERE pe_id=? AND pdf_sha256=?',(pe_id,sha))}
    # flag decisions
    def decide(self,key,status,note,reviewer,detail):
        if status not in ('resolved','waived'):raise ValueError('status must be resolved or waived')
        if not note or len(note.strip())<5:raise ValueError('A resolution note is required')
        if not reviewer or not reviewer.strip():raise ValueError('Reviewer name required')
        self.db.execute('INSERT OR REPLACE INTO flag_decisions VALUES (?,?,?,?,?,?)',(key,status,note.strip(),reviewer.strip(),detail_hash(detail),now()))
        self._changed()
    def decisions(self):
        return {r['flag_key']:dict(r) for r in self.db.execute('SELECT * FROM flag_decisions')}
    # corrections
    def add_correction(self,pe_id,table,record_key,field,old,new,page,quote,reason,reviewer):
        self.db.execute('INSERT INTO corrections(pe_id,table_name,record_key,field_name,old_value,new_value,pdf_page,evidence_verbatim,reason,reviewer,corrected_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                        (pe_id,table,record_key,field,old,new,page,quote,reason,reviewer,now()));self._changed()
    def corrections(self):
        return [dict(r) for r in self.db.execute('SELECT * FROM corrections ORDER BY correction_id')]
    # vision advice (never an attestation)
    def save_vision(self,rows):
        for r in rows:self.db.execute('INSERT OR REPLACE INTO vision_checks VALUES (?,?,?,?,?,?,?,?,?,?)',(r['pe_id'],r['pdf_page'],r['table_name'],r['record_key'],r['field_name'],(r.get('quote') or '')[:300],r['verdict'],(r.get('seen_text') or '')[:300],r['model'],now()))
        self._changed()
    def vision(self):
        return {(r['pe_id'],r['pdf_page'],r['table_name'],r['record_key'],r['field_name']):(r['verdict'],r['seen_text']) for r in self.db.execute('SELECT * FROM vision_checks')}
    def export_csv(self,folder):
        folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
        for t in CSV_TABLES:
            cur=self.db.execute(f'SELECT * FROM {t}');names=[c[0] for c in cur.description]
            import io as _io
            buf=_io.StringIO();w=csv.writer(buf,lineterminator='\n');w.writerow(names);w.writerows(cur.fetchall())
            atomic_write_text(folder/f'{t}.csv',buf.getvalue())

def store_path(root=ROOT):
    return Path(os.environ['CRA_REVIEW_DB']) if os.environ.get('CRA_REVIEW_DB') else Path(root)/'data/review.sqlite'

def open_store(root=ROOT):
    path=store_path(root);path.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(path);db.row_factory=sqlite3.Row;db.executescript(SCHEMA)
    mirror=None if os.environ.get('CRA_REVIEW_DB') else Path(root)/'reviews/decisions'
    return Store(db,mirror)
