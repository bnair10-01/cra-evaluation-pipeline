"""Export reviewed pilot data. Releases need every gate; otherwise only an explicitly marked DRAFT is written."""
import argparse
from collections import Counter
from contextlib import closing
import csv
import datetime as dt
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile

from .io import read_json,sha256_file,write_json
from .paths import ROOT
from .research import TABLES,columns

NULL_TOKEN='\\N'
INDICATORS=('borrower_income_phrase_and_three_benchmarks','mortgage_data_source_identified','benchmark_receiving_greater_weight_identified')

def csv_cell(value,safe=False):
    """Lossless: NULL -> \\N, a literal string starting with \\N is escaped. safe=True adds a quote prefix to
    cells a spreadsheet would execute as formulas; never use the safe copy as data."""
    if value is None:return NULL_TOKEN
    text=str(value)
    if text.startswith('\\'):text='\\'+text
    if safe and text and text[0] in ('=','+','-','@','\t','\r') and not _is_number(text):text="'"+text
    return text

def _is_number(text):
    try:float(text.replace(',',''));return True
    except ValueError:return False

def audit(db,documents):
    errors=[]
    keys={x['pe_id'] for x in documents}
    if len(keys)!=len(documents):errors.append('Duplicate evaluation ids in the manifest')
    if len({x['sha256'] for x in documents})!=len(documents):errors.append('Duplicate document bytes')
    if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':errors.append('SQLite integrity check failed')
    if db.execute('PRAGMA foreign_key_check').fetchall():errors.append('Foreign key violations')
    exams={r[0] for r in db.execute('SELECT pe_id FROM table_a_exam_level')}
    if exams!=keys:errors.append(f'Exam coverage differs: {len(keys-exams)} missing; {len(exams-keys)} extra')
    evidence=list(db.execute('SELECT * FROM field_evidence'))
    valid=set(); datasets={}
    for t,(pk,refs) in TABLES.items():
        datasets[t]={r[pk]:dict(r) for r in db.execute(f'SELECT * FROM {t}')}
    for e in evidence:
        r=datasets.get(e['table_name'],{}).get(e['record_id'],{})
        if (r.get('pe_id')!=e['pe_id'] or r.get(e['field_name']) is None or not e['evidence_verbatim'].strip()):
            errors.append(f'Invalid evidence {e["evidence_id"]}')
        else:valid.add((e['table_name'],e['record_id'],e['field_name']))
    required={(t,key,f) for t,(pk,refs) in TABLES.items() for key,r in datasets[t].items()
              for f,v in r.items() if v is not None and f not in {pk,*refs}}
    unsupported=required-valid
    if unsupported:errors.append(f'{len(unsupported)} populated fields lack linked evidence')
    return errors,datasets,dict(required=len(required),linked=len(required&valid),evidence_rows=len(evidence))

def propose_indicators(db,pe_ids):
    """Code proposals only; a person confirms them (`reviewed_by`) before export."""
    out={}
    for pe in pe_ids:
        mort=[dict(r) for r in db.execute("SELECT product_id,data_source FROM table_b_products_reviewed WHERE pe_id=? AND product='home mortgage'",(pe,))]
        ids={m['product_id'] for m in mort}
        d_ok=False
        for r in db.execute("SELECT aa_id,product_id,category,bank_count_pct,aggregate_pct,demographic_pct FROM table_d_distribution_measures WHERE pe_id=? AND dimension='borrower income'",(pe,)):
            if r['product_id'] in ids and None not in (r['bank_count_pct'],r['aggregate_pct'],r['demographic_pct']):d_ok=True
        e_ok=bool(db.execute("SELECT 1 FROM table_e_examiner_conclusions WHERE pe_id=? AND label_verbatim IS NOT NULL AND lower(coalesce(criterion,'')) LIKE '%borrower%' AND (product_id IN (SELECT product_id FROM table_b_products_reviewed WHERE pe_id=? AND product='home mortgage') OR product_id IS NULL) LIMIT 1",(pe,pe)).fetchone())
        src=any(m['data_source'] in ('HMDA','CRA-reported data','complete bank records','examiner sample') for m in mort)
        weight=bool(db.execute("SELECT 1 FROM table_e_examiner_conclusions WHERE pe_id=? AND benchmark_emphasis_text IS NOT NULL LIMIT 1",(pe,)).fetchone())
        out[pe]={INDICATORS[0]:dict(value=bool(d_ok and e_ok),basis='proposed',note=f'evaluative term={e_ok}; D rows with bank+aggregate+demographic%={d_ok}'),
                 INDICATORS[1]:dict(value=src,basis='proposed',note=f'mortgage rows={len(mort)}'),
                 INDICATORS[2]:dict(value=weight,basis='proposed',note='benchmark_emphasis_text present' if weight else 'none extracted')}
    return out

def gates(db,manifest,split,scores,reviewed,flags):
    docs=manifest['documents'];g=[]
    errors,datasets,counts=audit(db,docs)
    g.append(('database_audit',not errors,'; '.join(errors) or f"{counts['linked']}/{counts['required']} fields linked"))
    g.append(('no_open_errors',flags['errors']==0,f"{flags['errors']} open (wrong or missing data)"))
    g.append(('review_flags_cleared',flags['review']==0,f"{flags['review']} open (a person should look)"))
    extra=[d for d in docs if d['pe_id'] not in set(manifest.get('development_ids',[]))]
    from .paths import project_config
    q=project_config()['scan_quota'];g.append(('scan_quota',sum(d['scan_status']=='scanned' for d in extra)>=q,f'at least {q} scanned documents among the additional ones'))
    try:
        from .score import split as make_split
        expected=sorted(make_split(manifest)['holdout']);match=split is not None and sorted(split['holdout'])==expected
    except ValueError:match=False
    g.append(('split_matches_frozen',match,'holdout ids regenerate from the seed and equal the frozen split'))
    if scores is None:g.append(('independent_scores',False,'no frozen score file'))
    else:
        g.append(('reference_complete',bool(scores.get('reference_complete')),f"{scores.get('documents_with_reference')}/{scores.get('documents_expected')} documents"))
        g.append(('human_reference',scores.get('reference_kind','human')=='human','the reference must be an independent human coding'))
        g.append(('accuracy_targets',scores.get('passed') is True and scores.get('reference_kind','human')=='human',json.dumps(scores.get('gates'))))
    ok=bool(reviewed) and all(pe in reviewed and all(i in reviewed[pe] and isinstance(reviewed[pe][i].get('value'),bool) and reviewed[pe][i].get('reviewed_by') for i in INDICATORS) for pe in (d['pe_id'] for d in docs))
    g.append(('mortgage_indicators_confirmed',ok,'every document, three indicators, reviewed_by set'))
    return g,counts

def write_tables(db,out,safe_dir=None):
    for t in [*TABLES,'field_evidence']:
        names=list(columns(db,t))
        for target,safe in ((out,False),(safe_dir,True)):
            if target is None:continue
            with (Path(target)/f'{t}.csv').open('w',newline='',encoding='utf-8') as f:
                w=csv.writer(f);w.writerow(names)
                for row in db.execute(f'SELECT * FROM {t} ORDER BY 1'):w.writerow([csv_cell(v,safe) for v in row])
        try:
            import pyarrow as pa,pyarrow.parquet as pq
            rows=[dict(r) for r in db.execute(f'SELECT * FROM {t} ORDER BY 1')]
            pq.write_table(pa.Table.from_pylist(rows) if rows else pa.table({n:[] for n in names}),Path(out)/f'{t}.parquet')
        except ImportError:pass

def export_label(validated,audit,flags,gate_list):
    """VALIDATED: every gate passed. AUDITED: a person checked a random sample (100+ values) and nothing is wrong or missing.
    UNVERIFIED: otherwise. The export is always written; the label says how far to trust it."""
    if validated:return 'VALIDATED'
    if audit and audit.get('answered',0)>=100 and flags['errors']==0:return 'AUDITED'
    return 'UNVERIFIED'

def write_evaluation_view(db,docs,csv_path):
    """One row per evaluation joined to its RSSD (a view in the exported database plus a CSV); no research table is changed."""
    have=db.execute("SELECT 1 FROM sqlite_master WHERE name='rssd_crosswalk'").fetchone()
    cross={}
    if have:
        for agency,aid,rssd,status in db.execute('SELECT agency,agency_id,rssd_id,status FROM rssd_crosswalk'):cross[(agency,str(aid))]=(rssd,status)
        db.execute('DROP VIEW IF EXISTS v_evaluations_rssd')
        db.execute('''CREATE VIEW v_evaluations_rssd AS SELECT a.pe_id,a.agency_id,a.exam_date,a.exam_type,a.rating_overall,x.rssd_id,x.status AS rssd_status
                      FROM table_a_exam_level a LEFT JOIN rssd_crosswalk x ON x.agency_id=a.agency_id''')
        db.commit()
    with Path(csv_path).open('w',newline='',encoding='utf-8') as f:
        w=csv.writer(f);w.writerow(['pe_id','agency','agency_id','institution','exam_date_listing','rssd_id','rssd_status'])
        for pe,d in sorted(docs.items()):
            rssd,status=cross.get((d.get('agency'),str(d.get('agency_id'))),(None,'not looked up'))
            w.writerow([pe,d.get('agency'),d.get('agency_id'),d.get('institution_name'),d.get('exam_date'),'' if rssd is None else rssd,status or ''])

def export(db,manifest,out_root,split=None,scores=None,reviewed=None,root=ROOT,page_inventory=None,audit=None):
    from .review import flag_counts
    out_root=Path(out_root);out_root.mkdir(parents=True,exist_ok=True)
    flags=flag_counts(db)
    g,counts=gates(db,manifest,split,scores,reviewed,flags)
    release=all(ok for _,ok,_ in g)
    label=export_label(release,audit,flags,g)
    stamp=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S')
    existing=[int(p.name[1:]) for p in out_root.glob('v[0-9]*') if p.name[1:].isdigit()]
    name=f'v{max(existing,default=0)+1}' if release else f'{label}-{stamp}'
    tmp=Path(tempfile.mkdtemp(dir=out_root,prefix='.export-'))
    try:
        (tmp/'safe_for_spreadsheets').mkdir()
        write_tables(db,tmp,tmp/'safe_for_spreadsheets')
        docs={r['pe_id']:r for r in manifest['documents']}
        freq=Counter((docs[r['pe_id']]['agency'],docs[r['pe_id']]['exam_type'],r['label_verbatim'])
                     for r in db.execute('SELECT pe_id,label_verbatim FROM table_e_examiner_conclusions WHERE label_verbatim IS NOT NULL'))
        with (tmp/'examiner_phrase_frequency.csv').open('w',newline='',encoding='utf-8') as f:
            w=csv.writer(f);w.writerow(['agency','exam_type','phrase','count']);w.writerows([*k,v] for k,v in sorted(freq.items()))
        with closing(sqlite3.connect(tmp/'research.sqlite')) as dst:
            db.backup(dst)
            write_evaluation_view(dst,docs,tmp/'evaluations_rssd.csv')
        write_json(tmp/'mortgage_indicators.json',reviewed or {})
        write_json(tmp/'validation.json',dict(scores=scores,evidence=counts))
        write_json(tmp/'inventory.json',manifest)
        if page_inventory:write_json(tmp/'page_inventory.json',page_inventory)
        for doc in ('research_data_dictionary.md','coding_handbook.md','edge_case_coverage.md'):
            src=Path(root)/'docs'/doc
            if src.is_file():shutil.copyfile(src,tmp/doc)
        for rep in ('pilot_memo.md','error_log.md','cost_estimate.json','holdout_scores_auto_v1.json','holdout_scores_auto_v2.json','freeze_v1.json','freeze_v2.json'):
            src=Path(root)/'reports'/rep
            if src.is_file():shutil.copyfile(src,tmp/rep)
        (tmp/'NULL_CONVENTION.md').write_text("# CSV conventions\n\nNULL is written as `\\N`. An empty string is an empty cell. A text value that begins with a backslash is written with one extra leading backslash. `safe_for_spreadsheets/` additionally prefixes formula-looking text with an apostrophe and must not be used as data.\n",encoding='utf-8')
        write_json(tmp/'RELEASE_STATUS.json',dict(release=release,label=label,open_flags=flags,audit=audit and {k:audit.get(k) for k in ('answered','overall_strict_precision','overall_ci95_approx','per_table')},gates=[dict(name=n,passed=ok,detail=d) for n,ok,d in g],created=stamp))
        sums={str(p.relative_to(tmp)):sha256_file(p) for p in sorted(tmp.rglob('*')) if p.is_file()}
        write_json(tmp/'CHECKSUMS.json',sums)
        final=out_root/name;k=1
        while final.exists():k+=1;final=out_root/f'{name}-{k}'   # two exports in one second never collide
        os.replace(tmp,final)   # atomic publication of a complete directory
    except BaseException:
        shutil.rmtree(tmp,ignore_errors=True);raise
    return dict(path=str(final),release=release,label=label,gates=[dict(name=n,passed=ok,detail=d) for n,ok,d in g])

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--database',type=Path,default=ROOT/'data/research.sqlite');p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--output',type=Path,default=ROOT/'exports');p.add_argument('--split',type=Path);p.add_argument('--scores',type=Path)
    p.add_argument('--indicators',type=Path)
    a=p.parse_args()
    with closing(sqlite3.connect(a.database.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        db.row_factory=sqlite3.Row
        res=export(db,read_json(a.manifest),a.output,read_json(a.split) if a.split else None,read_json(a.scores) if a.scores else None,
                   read_json(a.indicators) if a.indicators else None)
    print(json.dumps(res,indent=1))
if __name__=='__main__':main()
