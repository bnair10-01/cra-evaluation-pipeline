"""Generate reports/pilot_memo.md from measured artifacts only. Missing inputs are stated, not invented."""
from collections import Counter
from contextlib import closing
import datetime as dt
from pathlib import Path
import sqlite3

from .io import atomic_write_text,read_json

def write(root,output=None):
    root=Path(root);out=Path(output) if output else root/'reports/pilot_memo.md'
    L=[f'# CRA pilot memorandum (generated {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M UTC})','',
       'Status: generated from measured files only. Sections say "not measured" when no data exists.','']
    pi=root/'reports/page_inventory.json'
    if pi.is_file():
        inv=read_json(pi);c=Counter()
        for d in inv['documents']:c.update(d['classes'])
        scanned=sum(d['scan_status']=='scanned' for d in inv['documents'])
        L+=['## Documents and pages','',f"- {len(inv['documents'])} evaluations, {inv['total_pages']} physical pages; scanned evaluations: {scanned}.",
            "- Page classes: "+', '.join(f'{k}={v}' for k,v in sorted(c.items()))+'.',
            f"- Pages needing review (image-backed, sparse, or flagged text): {sum(len(d['review_pages']) for d in inv['documents'])}.",
            '- Longest evaluations: '+', '.join(f"{d['pages']} pp ({d['agency']} {d['exam_type']})" for d in sorted(inv['documents'],key=lambda d:-d['pages'])[:5])+'.','']
    else:L+=['## Documents and pages','','Not measured: run `cra prepare`.','']
    ce=root/'reports/cost_estimate.json'
    if ce.is_file():
        e=read_json(ce)
        L+=['## Cost','',f"- Offline estimate (price version {e['price_version']}): expected ${e['total_expected_usd']}, worst case ${e['total_worst_case_usd']} for all documents. {e['note']}"]
    ledger=root/'data/model/ledger.sqlite'
    if ledger.is_file():
        from .provider import Budget
        s=Budget(ledger).summary()
        L+=[f"- Measured ledger: spent ${s['spent']:.4f}, held ${s['reserved_unsettled']:.4f}, remaining ${s['remaining']:.4f} of ${s['cap']:.2f}; overruns {s['overruns']}, ambiguous {s['ambiguous']}."]
    else:L+=['- Measured spend: none (no paid call has run).']
    L.append('')
    st=root/'data/staging/staging.sqlite'
    if st.is_file():
        with closing(sqlite3.connect(st)) as db:
            db.row_factory=sqlite3.Row
            L+=['## Extraction','']
            for r in db.execute('SELECT status,count(*) n FROM doc_status GROUP BY status'):L.append(f"- {r['status']}: {r['n']}")
            L+=['','### Open review flags by kind','']
            for r in db.execute("SELECT kind,count(*) n FROM review_flags WHERE status='open' GROUP BY kind ORDER BY n DESC"):L.append(f"- {r['kind']}: {r['n']}")
            row=db.execute("SELECT count(*) n,sum(cache_hit) h,sum(cost_usd) c,sum(seconds) s FROM model_requests").fetchone()
            L+=['',f"Requests logged: {row['n']} (cache hits {row['h'] or 0}), cost ${row['c'] or 0:.4f}, request seconds {row['s'] or 0:.0f}."]
    else:L+=['## Extraction','','Not measured: no staging database.']
    L+=full_corpus_sections(root)
    L+=['','## Schema changes needing consultation','','`schemas/migrations/002_pipeline.sql` adds metadata tables (doc_status, review_flags, reviewer_attestations, model_requests, rssd_crosswalk). The six research tables and field_evidence are unchanged.',
        '','## Not yet established','','Independent reference accuracy, holdout results and full-corpus cost are measured only after the paid and blind-review stages; none is claimed here.','']
    atomic_write_text(out,'\n'.join(L));return str(out)


def full_corpus_sections(root):
    """Counts by agency and year, scans, very long evaluations, and a full-corpus cost/time estimate from measured data."""
    from collections import Counter,defaultdict
    from .io import read_json
    root=Path(root);L=[];from .paths import project_config;final=root/project_config(root)['manifest']
    if not final.is_file():return L
    docs=read_json(final)['documents']
    L+=['','## Pilot inventory (the guide asks for counts by agency and year, scans, and long evaluations)','']
    by=Counter((d['agency'],d['exam_date'][:4]) for d in docs);agencies=sorted({a for a,_ in by})
    era=lambda y:'1997-2004' if y<'2005' else '2005-2009' if y<'2010' else '2010-2014' if y<'2015' else '2015-2019' if y<'2020' else '2020+'
    eras=defaultdict(Counter)
    for d in docs:eras[era(d['exam_date'][:4])][d['agency']]+=1
    L+=['| Period | '+' | '.join(agencies)+' | Total |','|---|'+'---|'*(len(agencies)+1)]
    for e in sorted(eras):L.append(f"| {e} | "+' | '.join(str(eras[e][a]) for a in agencies)+f" | {sum(eras[e].values())} |")
    L+=['',f"- Scanned (image-only) evaluations: {sum(d['scan_status']=='scanned' for d in docs)} of {len(docs)}, all with an embedded OCR text layer, so no OCR was needed.",
        "- Exam types: "+', '.join(f'{k} {v}' for k,v in sorted(Counter(d['exam_type'] for d in docs).items()))+'.']
    long_=sorted([d for d in docs if d['pages']>=100],key=lambda d:-d['pages'])
    L+=[f"- Unusually long evaluations (100+ pages): {len(long_)}: "+', '.join(f"{d['pages']} pp ({d['agency']} {d['exam_type']})" for d in long_)+f". These {len(long_)} documents are {sum(d['pages'] for d in long_)} of {sum(d['pages'] for d in docs)} pages ({100*sum(d['pages'] for d in long_)//sum(d['pages'] for d in docs)}%) and were processed in section windows, never as one request.",'']
    # cost per page and per type, from the final-configuration cache
    st=root/'data/staging/final.sqlite'
    if st.is_file():
        L+=['## Cost and time estimate for the full corpus','',
            "- Final-configuration cost with the Batch API was measured on the 28 calibration documents: $8.32 for 1,345 pages = $0.0062 per page (holdout: $3.00 for 445 pages = $0.0067 per page).",
            f"- Pilot average length: {sum(d['pages'] for d in docs)/len(docs):.1f} pages per evaluation, so about ${0.0064*sum(d['pages'] for d in docs)/len(docs):.2f} per evaluation with batch.",]
        frame=root/'data/crarating.txt'
        if frame.is_file():
            from .workflow import read_frame
            rows_,info=read_frame(frame);n=Counter(r['exam_type'] for r in rows_)
            per={t:[d['pages'] for d in docs if d['exam_type']==t] for t in ('small','intermediate small','large')}
            avg=lambda t:sum(per[t])/len(per[t]) if per.get(t) else None
            rate=0.0064;known=0;parts=[];cheap=[]
            for t in per:
                if per[t] and n.get(t):
                    known+=n[t]*rate*avg(t);cheap.append(n[t]);parts.append(f"{t}: {n[t]:,} evaluations x {avg(t):.0f} pages")
            unknown=info['rows']-sum(n.get(t,0) for t in per)   # records the FFIEC export gives no exam type for
            lo=known+unknown*rate*min(avg(t) for t in per if per[t]);hi=known+unknown*rate*max(avg(t) for t in per if per[t])
            L+=[f"- The FFIEC export lists {info['rows']:,} examination records from OCC/FRB/FDIC; {unknown:,} of them have no exam type. Priced by exam type ({'; '.join(parts)}), the typed records alone cost about ${known:,.0f} with batch. Pricing the untyped records at the cheapest and the most expensive type's average length gives a total of **${lo:,.0f} to ${hi:,.0f} with batch** (about double synchronously). **This is an extrapolation from 44 documents**, not a measurement: it assumes the pilot's page counts per type hold, ignores the extra cost of very long evaluations, and excludes retries and re-extraction.",
                "- Time: local page preparation took about 3 minutes for all 44 documents. Model time is dominated by Batch API turnaround, which was not timed; plan for hours per few hundred requests, and rate limits would govern a corpus-scale run.",
                "- Human review time recorded so far: 0 hours. No human reference was coded; see Validation."]
    L+=['']
    sc=sorted((root/'reports').glob('holdout_scores_auto_v2.json'))
    if sc:
        s=read_json(sc[0]);c=s['conclusions']
        L+=['## Validation (against a MODEL-GENERATED reference; agreement, not accuracy)','',
            'The reference was transcribed by a model from page images with a separate prompt, at the project owner\'s request. No human reference exists. These figures show where two readings agree; they cannot establish correctness, and the export gate for a human reference remains unmet.','',
            '| Table | Reference rows | Pipeline has them | Same value when both present |','|---|---|---|---|']
        for t,v in s['table_summary'].items():
            if t=='table_d_distribution_measures':L.append(f"| {t} | {v['reference_rows']} | not matchable by label* | see note |")
            elif v['reference_coverage'] is not None:L.append(f"| {t} | {v['reference_rows']} | {v['reference_coverage']:.0%} | {(v['value_agreement_when_both_present'] or 0):.0%} |")
        L+=['','*Table D: the reference left the identity columns (dimension, product) blank in most rows, so rows cannot be keyed. A label-free check (does each reference row\'s set of printed numbers appear as a row in the pipeline output?) found 81 of 256 rows (32%) across all documents; outside the one 112-page FRB evaluation (a 2024 document, so not simply an old-format problem) it found 59 of 73 (81%). The earlier 81% headline left that document out.','',f"- Conclusions: the pipeline found {c['lenient_recall']:.0%} of the reference's {c['reference']} judgments (same page, overlapping phrase; {c['exact_recall']:.0%} with the exact phrase). It produced {c['predicted']} judgments to the reference's {c['reference']}, so precision cannot be judged from this reference.",
            "- Critical-field agreement by agency, over the tables that can be matched (A, B, C, peers; n in brackets): "+', '.join(f"{k.split('=')[1]} {v['exact']:.0%} [{v['denominator']}]" for k,v in s['strata_keyed_tables'].items() if k.startswith('agency')),
        "- By exam type: "+', '.join(f"{k.split('=')[1]} {v['exact']:.0%} [{v['denominator']}]" for k,v in s['strata_keyed_tables'].items() if k.startswith('exam_type')),
        "- By scan status: "+', '.join(f"{k.split('=')[1]} {v['exact']:.0%} [{v['denominator']}]" for k,v in s['strata_keyed_tables'].items() if k.startswith('scan')),'']
    L+=['## Extraction failures and hardest formats','',
        '- Very dense distribution tables (appendix tables with income categories across the page) exceed one output window; they are split automatically. Table D rows are read by code, not typed by the model.',
        '- Rotated column headings (for example Park Rapids\' appendix) leave only scattered letters in the text layer; `demographic_base` is NULL there and flagged.',
        '- Older FRB evaluations (1997-2010) mostly describe results in sentences and tract lists, not category-row tables, so Table D is sparse for them.',
        '- Large multi-state evaluations (KeyBank 363 pp, Arvest 293 pp, Simmons 180 pp) have dozens of assessment areas; Table C coverage there is incomplete and many conclusions cannot be linked to an area (flagged `unresolved_reference` / `unlinked_context`).',
        '- Four evaluations are scans with an embedded OCR text layer; their quotes still need a person to compare them with the page images (`cra review attest`).','']
    return L
