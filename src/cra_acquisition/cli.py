"""`cra` command line. Every paid action goes through the persistent ledger and needs explicit flags."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sys

from .io import read_json,write_json,write_json_new
from .paths import ROOT

from .paths import project_config
PROJECT=project_config(ROOT)
FINAL=PROJECT['manifest']
SPLIT=PROJECT['split']

def ids_for(group,manifest,split,explicit):
    if explicit:
        known={r['pe_id'] for r in manifest['documents']}
        bad=[i for i in explicit if i not in known]
        if bad:raise SystemExit(f'Unknown pe_id: {bad}')
        return set(explicit)
    if group=='all':return {r['pe_id'] for r in manifest['documents']}
    if group=='devcal':return set(split['development'])|set(split['calibration'])   # everything except the holdout
    return set(split[group])

def parse_efforts(items):
    out={}
    for it in items:
        k,_,v=it.partition('=')
        if k not in ('a','b','c','e','peers','d') or v not in ('low','medium','high','xhigh','max'):raise SystemExit(f'Bad --effort-for {it!r}; use TARGET=LEVEL')
        out[k]=v
    return out

def paid_ledger():
    """The shared ledger, with attempts counted per command run (a new run gets a fresh allowance)."""
    import datetime as dt
    from .provider import Budget
    b=Budget(ROOT/'data/model/ledger.sqlite');b.run=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%f');return b

def show(rows):
    for r in rows:print(('OK   ' if r['ok'] else 'FAIL ')+r['name']+(': '+r['detail'] if r['detail'] else ''))
    return 0 if all(r['ok'] for r in rows) else 1

def main(argv=None):
    p=argparse.ArgumentParser(prog='cra',description=__doc__)
    p.add_argument('--final',default=str(ROOT/FINAL));p.add_argument('--split',default=str(ROOT/SPLIT))
    sub=p.add_subparsers(dest='cmd',required=True)
    s=sub.add_parser('preflight');s.add_argument('--online',action='store_true');s.add_argument('--probe',action='store_true',help='one tiny paid structured-output call')
    s=sub.add_parser('prepare');s.add_argument('--pe-id',action='append');s.add_argument('--force',action='store_true')
    s=sub.add_parser('estimate');s.add_argument('--group',default='all',choices=['development','calibration','holdout','all'])
    s=sub.add_parser('extract')
    s.add_argument('--group',choices=['development','calibration','devcal','holdout','all']);s.add_argument('--pe-id',action='append')
    s.add_argument('--run-id',required=True);s.add_argument('--staging',default=str(ROOT/'data/staging/staging.sqlite'))
    s.add_argument('--effort',default='low');s.add_argument('--effort-for',action='append',default=[],metavar='TARGET=LEVEL',help='per-target effort, e.g. e=medium (targets: a b c e peers d)');s.add_argument('--freeze');s.add_argument('--clean-test',action='store_true',help='holdout discipline: require a frozen configuration (use for an out-of-sample test)');s.add_argument('--retry-failed',action='store_true',help='re-request tasks whose stored result was a refusal, truncation or malformed output');s.add_argument('--yes-spend',action='store_true',help='required: confirms paid calls under the ledger cap')
    s.add_argument('--limit',type=int,default=0,help='process at most N documents')
    s.add_argument('--replicate',type=int,default=0,help='fresh independent extraction number N (separate cache entries); needs its own --staging file')
    s.add_argument('--with-category-columns',action='store_true',help='also extract tables whose income categories run across the page (older FRB evaluations); an extra paid step, off by default')
    s.add_argument('--max-pages',type=int,default=0,help='skip documents longer than N pages (run the very long ones last, once prompts are settled)')
    s.add_argument('--cache-only',action='store_true',help='reprocess cached model output only: no key, no spend, any cache miss is an error')
    s.add_argument('--batch',action='store_true',help='use the Batch API (half price, asynchronous) to fill the cache first')
    s=sub.add_parser('freeze');s.add_argument('--output',required=True);s.add_argument('--note',required=True);s.add_argument('--effort',default='low');s.add_argument('--effort-for',action='append',default=[],metavar='TARGET=LEVEL')
    s=sub.add_parser('validate');s.add_argument('--run-id',required=True);s.add_argument('--staging',default=str(ROOT/'data/staging/staging.sqlite'));s.add_argument('--pe-id',action='append')
    s=sub.add_parser('flags');s.add_argument('--run-id',required=True);s.add_argument('--staging',default=str(ROOT/'data/staging/staging.sqlite'));s.add_argument('--pe-id');s.add_argument('--all',action='store_true')
    s=sub.add_parser('review')
    s.add_argument('action',choices=['resolve','attest','mark-reviewed','accept','submit-reference','progress','correct'])
    s.add_argument('--run-id');s.add_argument('--staging',default=str(ROOT/'data/staging/staging.sqlite'));s.add_argument('--database',default=str(ROOT/'data/research.sqlite'))
    s.add_argument('--pe-id');s.add_argument('--flag-id',type=int);s.add_argument('--status',default='resolved');s.add_argument('--note')
    s.add_argument('--pages',help='e.g. 1-5,9');s.add_argument('--reviewer')
    s.add_argument('--strict',action='store_true',help='mark-reviewed/accept: also require every review-level flag to be cleared');s.add_argument('--table');s.add_argument('--record');s.add_argument('--field');s.add_argument('--value');s.add_argument('--page',type=int);s.add_argument('--quote')
    s.add_argument('--forms');s.add_argument('--write-coverage',help='progress: write a DRAFT coverage file from the tables that have rows (you must check each is complete)');s.add_argument('--coverage',help='JSON file {pe_id: [table names you coded]}; omit to declare every table of every document coded');s.add_argument('--started');s.add_argument('--finished');s.add_argument('--attest-blind',action='store_true')
    s=sub.add_parser('packet');s.add_argument('--group',default='holdout');s.add_argument('--output',required=True);s.add_argument('--no-images',action='store_true')
    s=sub.add_parser('predictions');s.add_argument('--database',required=True);s.add_argument('--group',default='holdout');s.add_argument('--output',required=True)
    s=sub.add_parser('score');s.add_argument('--reference',required=True);s.add_argument('--predictions',required=True);s.add_argument('--output',required=True)
    s=sub.add_parser('export');s.add_argument('--database',default=str(ROOT/'data/research.sqlite'));s.add_argument('--scores');s.add_argument('--indicators');s.add_argument('--output',default=str(ROOT/'exports'))
    s=sub.add_parser('indicators');s.add_argument('--database',required=True);s.add_argument('--output',required=True)
    s=sub.add_parser('rssd');s.add_argument('--database',required=True);s.add_argument('--csv')
    s=sub.add_parser('status');s.add_argument('--run-id');s.add_argument('--staging',default=str(ROOT/'data/staging/staging.sqlite'))
    s=sub.add_parser('batches');s.add_argument('--collect');s.add_argument('--staging',default=str(ROOT/'data/staging/staging.sqlite'));s.add_argument('--run-id',default='batch-collect')
    s=sub.add_parser('ledger');s.add_argument('--set-cap',type=float,help='set the spending ceiling in dollars (needs --reason); recorded in the ledger');s.add_argument('--release-reserved',action='store_true',help='settle never-sent reservations at $0 (only after `cra batches` shows nothing is in flight)');s.add_argument('--reason')
    s=sub.add_parser('compare');s.add_argument('--a',required=True);s.add_argument('--b',required=True);s.add_argument('--group',default='development')
    s=sub.add_parser('autocode');s.add_argument('--group',default='holdout');s.add_argument('--yes-spend',action='store_true');s.add_argument('--output',default=str(ROOT/'reviews/auto_coding'));s.add_argument('--limit',type=int,default=0)
    s=sub.add_parser('workbook');s.add_argument('--export',help='export folder; default: the newest in exports/');s.add_argument('--no-pdfs',action='store_true')
    s=sub.add_parser('audit');s.add_argument('action',choices=['sample','score','scans','attest-sheet']);s.add_argument('--staging',default=str(ROOT/'data/staging/final.sqlite'));s.add_argument('--output',default=str(ROOT/'reviews/audit'))
    s.add_argument('--sheet');s.add_argument('--csv');s.add_argument('--reviewer');s.add_argument('--seed',type=int,default=20261122)
    s=sub.add_parser('visioncheck');s.add_argument('--staging',default=str(ROOT/'data/staging/final.sqlite'));s.add_argument('--yes-spend',action='store_true');s.add_argument('--limit-pages',type=int,default=0);s.add_argument('--output',default=str(ROOT/'reviews/audit/vision'))
    s=sub.add_parser('corrections');s.add_argument('action',choices=['list','apply']);s.add_argument('--staging',default=str(ROOT/'data/staging/final.sqlite'));s.add_argument('--output')
    sub.add_parser('rehearse')
    sub.add_parser('memo')
    a=p.parse_args(argv)
    final=Path(a.final);split_path=Path(a.split)
    if a.cmd=='preflight':
        from . import preflight
        rc=show(preflight.offline(ROOT,final.relative_to(ROOT) if final.is_absolute() and ROOT in final.parents else final))
        if a.online:rc|=show(preflight.online(ROOT,a.probe))
        return rc
    manifest=read_json(final) if final.is_file() else None;split=read_json(split_path) if split_path.is_file() else None
    if a.cmd=='prepare':
        from .prepare import inventory
        m=dict(manifest,documents=[r for r in manifest['documents'] if not a.pe_id or r['pe_id'] in a.pe_id])
        inv=inventory(ROOT,m,a.force,lambda i:print('preparing',i,flush=True))
        if not a.pe_id:write_json(ROOT/'reports/page_inventory.json',inv)
        print(json.dumps({k:v for k,v in inv.items() if k!='documents'},indent=1));return 0
    if a.cmd=='estimate':
        from .estimate import estimate
        r=estimate(manifest,ids_for(a.group,manifest,split,None))
        print(f"expected ${r['total_expected_usd']}  worst-case ${r['total_worst_case_usd']}  ({r['note']})");return 0
    if a.cmd=='extract':
        from .provider import Anthropic,Budget
        from .pipeline import extract_group
        from . import preflight,review
        ids=ids_for(a.group,manifest,split,a.pe_id)
        extra=dict(replicate=a.replicate) if a.replicate else None;efforts=parse_efforts(a.effort_for)
        targets=('a','b','c','e','peers','d')+(('dc',) if a.with_category_columns else ())
        if a.replicate and Path(a.staging).resolve()==(ROOT/'data/staging/staging.sqlite').resolve():raise SystemExit('--replicate needs its own --staging file so the primary extraction is never overwritten')
        if a.max_pages:
            long_ids={r['pe_id'] for r in manifest['documents'] if r['pages']>a.max_pages};skipped=ids&long_ids;ids=ids-long_ids
            print(f'--max-pages {a.max_pages}: skipping {len(skipped)} longer documents',flush=True)
        if a.cache_only:
            from .pipeline import CacheOnlyProvider
            out=extract_group(manifest,ids,CacheOnlyProvider(),Budget(ROOT/'data/model/ledger.sqlite'),a.staging,a.run_id,ROOT,a.effort,targets=targets,extra=extra,efforts=efforts)
            print(json.dumps(dict(documents=out,note='cache-only: no model calls made'),indent=1));return 0
        if not a.yes_spend:raise SystemExit('Refusing to spend: re-run with --yes-spend after reviewing `cra estimate`')
        if a.clean_test and not a.freeze:raise SystemExit('--clean-test needs --freeze FILE (made with `cra freeze` before the run)')
        if ids&set(split['holdout']) and not a.freeze:print('note: holdout documents without a frozen configuration; fine for exploring, but this is not a clean out-of-sample test (use --clean-test --freeze FILE)',file=sys.stderr)
        rows=preflight.offline(ROOT)
        if not all(r['ok'] for r in rows if r['name']!='tesseract (optional)'):show(rows);raise SystemExit('Offline preflight failed')
        try:provider=Anthropic();provider.preflight()
        except Exception as e:raise SystemExit(f'Provider check failed: {type(e).__name__}: {e}')
        if a.freeze:review.verify_freeze(a.freeze,provider,a.effort,ROOT,efforts)
        ledger=paid_ledger()
        if a.limit:ids=set(sorted(ids)[:a.limit])
        if a.batch:
            from .batch import warm_cache
            print(json.dumps(warm_cache(manifest,ids,provider,ledger,a.staging,a.run_id,ROOT,a.effort,targets=targets,extra=extra,efforts=efforts,retry_failed=a.retry_failed)))
        out=extract_group(manifest,ids,provider,ledger,a.staging,a.run_id,ROOT,a.effort,targets=targets,extra=extra,efforts=efforts,retry_failed=a.retry_failed)
        print(json.dumps(dict(documents=out,budget=ledger.summary()),indent=1));return 0
    if a.cmd=='freeze':
        from .provider import Anthropic
        from . import review
        import os
        os.environ.setdefault('ANTHROPIC_API_KEY','unused-for-freeze')
        prov=Anthropic(client=object())
        print(json.dumps(review.freeze(a.output,prov,a.effort,a.note,ROOT,parse_efforts(a.effort_for)),indent=1));return 0
    if a.cmd=='review' and a.action=='progress':
        import csv
        forms=Path(a.forms or ROOT/'reviews/my_coding');tables=['table_a_exam_level','table_b_products_reviewed','table_c_assessment_areas','table_d_distribution_measures','table_e_examiner_conclusions','ltd_peers']
        short={'table_a_exam_level':'A','table_b_products_reviewed':'B','table_c_assessment_areas':'C','table_d_distribution_measures':'D','table_e_examiner_conclusions':'E','ltd_peers':'peers'}
        counts={}
        for t in tables:
            f=forms/f'{t}.csv'
            if not f.is_file():continue
            with f.open(newline='',encoding='utf-8') as fh:
                for r in csv.DictReader(fh):
                    if any((v or '').strip() for v in r.values()):counts.setdefault((r.get('pe_id') or '').strip(),{}).setdefault(t,0);counts[(r.get('pe_id') or '').strip()][t]+=1
        hold=set(split['holdout']);mine=[d for d in manifest['documents'] if d['pe_id'] in hold]   # only the 12 holdout documents belong in the reference
        print('your coded rows (blank = nothing yet).  Columns: '+'  '.join(short[t] for t in tables))
        for d in sorted(mine,key=lambda r:r['pages']):
            row=counts.get(d['pe_id'],{});print(f"{d['pe_id'][-8:]} {d['agency']:4}{d['pages']:4}pp  "+'  '.join(f"{row.get(t,0) or '.':>5}" for t in tables))
        unknown=[p for p in counts if p not in hold]
        if unknown:print('WARNING: rows whose pe_id is not one of the 12 holdout documents (the scorer will reject them):',unknown)
        if a.write_coverage:
            cov={pe:sorted(t) for pe,t in ((pe,list(r)) for pe,r in counts.items() if pe in {d['pe_id'] for d in mine})}
            print(write_json_new(a.write_coverage,cov));print('wrote a DRAFT coverage file; delete any table you have not finished for that document before submitting')
        return 0
    if a.cmd in ('validate','flags','status','review') and a.cmd!='review' or a.cmd=='review' and a.action!='submit-reference':
        from . import runstate,validate
        with closing(runstate.connect(a.staging)) as db:
            if a.cmd=='validate':
                from . import review,reviewstore
                store=reviewstore.open_store(ROOT)
                docs={r['pe_id']:r for r in manifest['documents']}
                for pe in (a.pe_id or [r[0] for r in db.execute('SELECT pe_id FROM table_a_exam_level')]):
                    f=validate.validate_document(db,pe,docs.get(pe))
                    if pe in docs:
                        from .prepare import load_or_prepare
                        f+=validate.completeness(db,pe,load_or_prepare(ROOT,docs[pe]))
                    keep=[x for x in runstate.open_flags(db,a.run_id,pe) if x['kind'] not in validate.VALIDATION_KINDS]   # a re-run replaces validation flags; extraction flags stay
                    runstate.add_flags(db,a.run_id,pe,[dict(**{k:v for k,v in json.loads(x['detail'] or '{}').items()},kind=x['kind'],table=x['table_name'],record=x['record_id'],field=x['field_name'],page=x['pdf_page']) for x in keep]+f)
                    n=review.apply_decisions(db,store,a.run_id,pe)
                    print(pe[-8:],len(f),'validation flags',f"(saved decisions applied: {n['applied']}, re-check: {n['recheck']}, attested pages: {n['attested']})" if any(n.values()) else '')
                return 0
            if a.cmd=='flags':
                q="SELECT kind,count(*) n FROM review_flags WHERE run_id=? AND status='open'"+(" AND pe_id=?" if a.pe_id else '')+' GROUP BY kind'
                for r in db.execute(q,(a.run_id,*([a.pe_id] if a.pe_id else []))):print(f"{r['kind']:28} {r['n']}")
                if a.all and a.pe_id:
                    for r in db.execute("SELECT flag_id,kind,table_name,record_id,field_name,pdf_page,detail FROM review_flags WHERE run_id=? AND pe_id=? AND status='open'",(a.run_id,a.pe_id)):print(dict(r))
                return 0
            if a.cmd=='status':
                q='SELECT pe_id,status,updated_at FROM doc_status'+(' WHERE run_id=?' if a.run_id else '')
                for r in db.execute(q,((a.run_id,) if a.run_id else ())):print(r['pe_id'],r['status'],r['updated_at'])
                try:
                    from .provider import Budget
                    print(json.dumps(Budget(ROOT/'data/model/ledger.sqlite').summary()))
                except Exception:pass
                return 0
            from . import review
            if a.action=='resolve':review.resolve_flag(db,a.flag_id,a.status,a.note or '',reviewer=a.reviewer or '');print('ok (saved in data/review.sqlite; survives a rebuild)');return 0
            if a.action=='attest':
                rec=next(r for r in manifest['documents'] if r['pe_id']==a.pe_id)
                pages=set()
                for part in (a.pages or '').split(','):
                    lo,_,hi=part.partition('-');pages.update(range(int(lo),int(hi or lo)+1))
                review.attest_pages(db,a.pe_id,rec['sha256'],pages,a.reviewer or '',a.note);print(f'attested {len(pages)} pages');return 0
            if a.action=='correct':
                from .prepare import load_or_prepare
                rec=next(r for r in manifest['documents'] if r['pe_id']==a.pe_id)
                review.add_correction(db,load_or_prepare(ROOT,rec),a.pe_id,a.table,a.record or a.pe_id,a.field,a.value,a.page,a.quote,a.note or '',a.reviewer or '');print('correction recorded (the extraction itself is unchanged; run `cra corrections apply`)');return 0
            if a.action=='mark-reviewed':review.mark_reviewed(db,a.run_id,a.pe_id,a.strict);print('reviewed');return 0
            if a.action=='accept':print(json.dumps(review.accept(a.staging,a.database,a.run_id,a.pe_id,ROOT,strict=a.strict)));return 0
    if a.cmd=='review' and a.action=='submit-reference':
        from . import packet
        ids=set(split['holdout'])
        print(json.dumps(packet.submit_reference(a.forms,ROOT/'reviews/submissions',a.reviewer,a.started,a.finished,a.attest_blind,ids,ROOT,read_json(a.coverage) if a.coverage else None),indent=1));return 0
    if a.cmd=='packet':
        from . import packet
        print(json.dumps(packet.build_packet(manifest,ids_for(a.group,manifest,split,None),a.output,not a.no_images,ROOT),indent=1)[:600]);return 0
    if a.cmd=='predictions':
        import sqlite3
        from . import score,validate
        with closing(sqlite3.connect(Path(a.database).resolve().as_uri()+'?mode=ro',uri=True)) as db:
            db.row_factory=sqlite3.Row
            rows=score.predictions_from_db(db,ids_for(a.group,manifest,split,None),validate.inventory())
        print(len(rows),'rows ->',write_json_new(a.output,dict(rows=rows,source=str(a.database))));return 0
    if a.cmd=='score':
        from . import score,validate
        from .io import sha256_file
        ref=read_json(a.reference);pred=read_json(a.predictions);inv=validate.inventory()
        if not ref.get('rows'):raise SystemExit('This reference file has no coded rows; it cannot be scored. Submit your filled forms with `cra review submit-reference` first.')
        result=score.measure(ref['rows'],pred['rows'],set(split['holdout']),score.strata_from(manifest),inv['targets'],coverage=ref.get('coverage'))
        result.update(reference_sha256=sha256_file(a.reference),prediction_sha256=sha256_file(a.predictions),reference_kind=ref.get('reference_kind','human'))
        if result['reference_kind']!='human':
            result['passed']=None;result['gates']={k:None for k in result.get('gates',{})}
            result['label']='AGREEMENT WITH A MODEL-GENERATED REFERENCE: not accuracy, not validation, cannot pass'
        log=ROOT/'reports/holdout_log.json'
        history=read_json(log) if log.is_file() else []
        history.append(dict(reference=result['reference_sha256'],predictions=result['prediction_sha256'],at=__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()))
        write_json(log,history);write_json_new(a.output,result)
        print(json.dumps({k:result[k] for k in ('critical_exact','conclusion_precision','conclusion_recall','reference_complete','passed') if k in result}));return 0
    if a.cmd=='indicators':
        import sqlite3
        from . import handoff
        with closing(sqlite3.connect(Path(a.database).resolve().as_uri()+'?mode=ro',uri=True)) as db:
            db.row_factory=sqlite3.Row
            print(write_json_new(a.output,handoff.propose_indicators(db,[r['pe_id'] for r in manifest['documents']])))
        print('proposals written; edit each indicator to add "reviewed_by" once you have checked it');return 0
    if a.cmd=='export':
        import sqlite3
        from . import handoff,review
        with closing(sqlite3.connect(Path(a.database).resolve().as_uri()+'?mode=ro',uri=True)) as db:
            db.row_factory=sqlite3.Row
            import glob
            ar=sorted(glob.glob(str(ROOT/'reports/audit_precision_*.json')));audit=read_json(ar[-1]) if ar else None
            pi=ROOT/'reports/page_inventory.json'
            res=handoff.export(db,manifest,a.output,split,read_json(a.scores) if a.scores else None,read_json(a.indicators) if a.indicators else None,ROOT,read_json(pi) if pi.is_file() else None,audit)
        try:   # the package should open without technical help: add the Excel workbook, the PDFs and the plain-language guide
            from . import workbook
            import shutil
            workbook.build(Path(res['path']),ROOT)
            for name in ('README.md',):
                if (ROOT/name).is_file():shutil.copyfile(ROOT/name,Path(res['path'])/name)
        except Exception as e:print(f'(workbook not added: {type(e).__name__}: {e})')
        print(json.dumps(res,indent=1));return 0 if res['release'] else 2
    if a.cmd=='rssd':
        from . import rssd,runstate
        with closing(runstate.connect(a.database)) as db:
            runstate.migrate(db);rssd.store(db,rssd.build(manifest,rssd.fetch_snapshot(ROOT)))
        return 0
    if a.cmd=='batches':
        from . import batch,runstate
        from .provider import Anthropic,Budget
        dirs={'cache':ROOT/'data/model/cache','batches':ROOT/'data/model/batches'}
        local=batch.pending_batches(dirs)
        print(f'local batch records not yet collected: {len(local)}')
        for r in local:print(f"  {r['batch_id']}  requests={len(r['requests'])}  run={r['run_id']}")
        try:provider=Anthropic()
        except Exception as e:
            print(f'(remote status unavailable: {e})');provider=None
        if provider:
            known={r['batch_id'] for r in local}
            for b in provider.client.messages.batches.list(limit=20):
                rc=getattr(b,'request_counts',None)
                print(f"  remote {b.id} {b.processing_status} {'(tracked locally)' if b.id in known else '(not tracked by this project)'} counts={rc.model_dump() if hasattr(rc,'model_dump') else rc} created={getattr(b,'created_at','')}")
        if a.collect:
            if not provider:raise SystemExit('A key is needed to collect a batch')
            with closing(runstate.connect(a.staging)) as db:
                runstate.migrate(db)
                resplit=batch.collect_round(provider,Budget(ROOT/'data/model/ledger.sqlite'),a.collect,dirs,db,a.run_id)
            print(f'collected; {len(resplit)} truncated tasks would be split on the next `cra extract --batch`')
        return 0
    if a.cmd=='ledger':
        from . import batch
        from .provider import Budget
        led=Budget(ROOT/'data/model/ledger.sqlite')
        if a.set_cap is not None:
            if not a.reason:raise SystemExit('--reason is required to change the ceiling')
            led.raise_cap(a.set_cap,a.reason)
        print(json.dumps(led.summary(),indent=1))
        pend=batch.pending_batches({'cache':ROOT/'data/model/cache','batches':ROOT/'data/model/batches'})
        protected={r['reservation'] for b in pend for r in b['requests']}
        stale=[u for u in led.unsettled() if u['status']=='reserved' and u['id'] not in protected]
        print(f"unsettled reservations: {len(led.unsettled())}; never-sent candidates for release: {len(stale)}; protected by an uncollected batch: {len(protected)}")
        if a.release_reserved:
            if not a.reason:raise SystemExit('--reason is required')
            for u in stale:led.release(u['id'],a.reason)
            print(f'released {len(stale)} reservations at $0');print(json.dumps(led.summary(),indent=1))
        return 0
    if a.cmd=='autocode':
        from . import autocode
        from .provider import Anthropic,Budget
        if not a.yes_spend:raise SystemExit('Refusing to spend: add --yes-spend. This makes vision calls on every page of the selected documents; output is a MODEL-GENERATED reference, not a human one.')
        ids=ids_for(a.group,manifest,split,None)
        if a.limit:ids=set(sorted(ids)[:a.limit])
        provider=Anthropic();provider.preflight();ledger=paid_ledger()
        facts=autocode.run(manifest,ids,provider,ledger,a.output,ROOT)
        forms=autocode.write_forms(facts,a.output,ROOT)
        res=autocode.submit(forms,Path(a.output)/'submissions',provider.model,ids,ROOT);res['pages_not_transcribed']={k[-8:]:v for k,v in getattr(autocode.run,'untranscribed',{}).items() if v}
        print(json.dumps(res,indent=1));print(json.dumps(ledger.summary()));return 0
    if a.cmd=='compare':
        from . import validate,runstate
        from .research import TABLES
        with closing(runstate.connect(a.a)) as A,closing(runstate.connect(a.b)) as B:
            import collections
            tot={};diff=collections.Counter();ex={}
            for pe in sorted(ids_for(a.group,manifest,split,None)):
                if not A.execute('select 1 from table_a_exam_level where pe_id=?',(pe,)).fetchone() or not B.execute('select 1 from table_a_exam_level where pe_id=?',(pe,)).fetchone():continue
                for t in TABLES:
                    na=A.execute(f'select count(*) from {t} where pe_id=?',(pe,)).fetchone()[0];nb=B.execute(f'select count(*) from {t} where pe_id=?',(pe,)).fetchone()[0]
                    tot.setdefault(t,[0,0]);tot[t][0]+=na;tot[t][1]+=nb
                for d in validate.compare_runs(A,B,pe):
                    diff[(d['table'],'row only in one run' if 'field' not in d else 'field differs')]+=1;ex.setdefault((d['table'],d.get('field')),d)
        e=dict(matched=0,only_a=0,only_b=0)
        with closing(runstate.connect(a.a)) as A2,closing(runstate.connect(a.b)) as B2:
            for pe in sorted(ids_for(a.group,manifest,split,None)):
                if A2.execute('select 1 from table_a_exam_level where pe_id=?',(pe,)).fetchone() and B2.execute('select 1 from table_a_exam_level where pe_id=?',(pe,)).fetchone():
                    for k,v in validate.compare_conclusions(A2,B2,pe).items():e[k]+=v
        print('rows per table (run A, run B):',{k:tuple(v) for k,v in tot.items()})
        print('conclusions by (page, phrase):',e)
        import sqlite3
        from . import score
        def long_rows(path):
            d=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True);d.row_factory=sqlite3.Row
            try:return score.predictions_from_db(d,[p for p in sorted(ids_for(a.group,manifest,split,None)) if d.execute('select 1 from table_a_exam_level where pe_id=?',(p,)).fetchone()],validate.inventory())
            finally:d.close()
        mm=score.match_conclusions(long_rows(a.a),long_rows(a.b))
        print('conclusion agreement (run A as reference, run B as prediction):')
        for k in ('reference','predicted','matched','matched_exact','lenient_precision','lenient_recall','exact_precision','exact_recall','level_agreement','category_agreement','criterion_agreement'):
            v=mm[k];print(f'  {k:20}',round(v,3) if isinstance(v,float) else v)
        for k,v in sorted(diff.items()):print(f'{v:5}  {k[0]}  {k[1]}')
        return 0
    if a.cmd=='workbook':
        from . import workbook
        folder=Path(a.export) if a.export else max((p for p in (ROOT/'exports').iterdir() if p.is_dir()),key=lambda p:p.stat().st_mtime)
        print(workbook.build(folder,ROOT,not a.no_pdfs));return 0
    if a.cmd=='audit':
        from . import audit,runstate
        if a.action=='sample':print('written:',audit.build_precision_sheet(a.staging,manifest,a.output,seed=a.seed,root=ROOT));return 0
        if a.action=='score':
            r=audit.score_precision(a.sheet);write_json(ROOT/'reports'/('audit_precision_'+Path(a.sheet).stem+'.json'),r)
            print(json.dumps({k:v for k,v in r.items() if k!='wrong'},indent=1));print(len(r['wrong']),'values marked wrong (listed in the report)');return 0
        if a.action=='scans':print(json.dumps(audit.build_scan_worksheet(a.staging,manifest,Path(a.output)/'scans',ROOT)));return 0
        with closing(runstate.connect(a.staging)) as db:print(audit.attest_from_sheet(db,manifest,a.csv,a.reviewer or ''),'pages attested');return 0
    if a.cmd=='visioncheck':
        from . import visioncheck
        from .provider import Anthropic,Budget
        if not a.yes_spend:raise SystemExit('Refusing to spend: add --yes-spend (one vision call per scanned page, about $1-2 in total). Results are advice for your worksheet, never an attestation.')
        provider=Anthropic();provider.preflight();led=paid_ledger()
        print(json.dumps(visioncheck.run(a.staging,manifest,provider,led,a.output,ROOT,limit_pages=a.limit_pages)));print(json.dumps(led.summary()));return 0
    if a.cmd=='corrections':
        from . import review,reviewstore
        store=reviewstore.open_store(ROOT)
        if a.action=='list':
            for r in store.corrections():print(r['correction_id'],r['table_name'],r['record_key'][-30:],r['field_name'],repr(r['old_value']),'->',repr(r['new_value']),'p',r['pdf_page'],r['reviewer'],'|',r['reason'][:60])
            return 0
        out=a.output or str(ROOT/'data/staging/final_corrected.sqlite');res=review.apply_corrections(a.staging,out,store)
        print(f"applied {res['applied']} to a copy: {out}; re-check (value changed since): {res['recheck']}; row no longer exists: {res['orphans']}");return 0
    if a.cmd=='rehearse':
        from .rehearse import rehearse
        print(json.dumps(rehearse(manifest,set(split['development']),ROOT/'data/rehearsal'),indent=1));return 0
    if a.cmd=='memo':
        from . import memo
        print(memo.write(ROOT));return 0
    return 1

if __name__=='__main__':sys.exit(main())
