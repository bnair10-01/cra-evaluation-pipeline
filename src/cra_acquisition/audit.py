"""Human audit tools. They prepare sheets and turn a person's verdicts into measured numbers; they never judge anything themselves.

precision audit : a stratified random sample of extracted values; the person marks each Y (right), P (partly), N (wrong).
scanned pages   : a page-image worksheet for the evidence that rests on a scan's text layer; the person attests pages.
"""
import csv
import datetime as dt
import html
import math
import os
from pathlib import Path
import random
import sqlite3
from contextlib import closing

from .io import read_json,sha256_file,write_json
from .paths import ROOT
from .research import TABLES

QUOTAS={'table_a_exam_level':60,'table_b_products_reviewed':50,'table_c_assessment_areas':40,'table_d_distribution_measures':60,
        'table_e_examiner_conclusions':70,'ltd_peers':20}
SKIP={'page','table_label'}   # labels that say nothing about correctness
LABEL_FIELD={'table_a_exam_level':'institution_name','table_b_products_reviewed':'product','table_c_assessment_areas':'aa_name','ltd_peers':'institution_name'}

def population(db):
    """Every populated, evidenced (table, record, field) as dicts. Pure data; no sampling."""
    out=[]
    for table,(pk,refs) in TABLES.items():
        cols=[c[1] for c in db.execute(f'pragma table_info({table})')]
        ev={}
        for r in db.execute('select record_id,field_name,pdf_page,evidence_verbatim,value_as_printed from field_evidence where table_name=? order by pdf_page',(table,)):ev.setdefault((r[0],r[1]),r)
        for row in db.execute(f'select * from {table}'):
            for f in cols:
                if f in {pk,*refs} or f in SKIP or row[f] is None:continue
                e=ev.get((row[pk],f))
                if e is None:continue
                out.append(dict(table=table,record=row[pk],pe_id=row['pe_id'] if 'pe_id' in row.keys() else row[pk],field=f,value=row[f],page=e[2],quote=e[3],printed=e[4],
                                about=str(row[LABEL_FIELD[table]]) if table in LABEL_FIELD and row[LABEL_FIELD[table]] else (row['category'] if table=='table_d_distribution_measures' and row['category'] else (row['criterion'] if table=='table_e_examiner_conclusions' else ''))))
    return out

def draw_sample(pop,quotas=None,seed=20261122):
    rng=random.Random(seed);quotas=quotas or QUOTAS;by={}
    for p in pop:by.setdefault(p['table'],[]).append(p)
    sample=[]
    for table,items in sorted(by.items()):
        items=sorted(items,key=lambda p:(p['record'],p['field']));k=min(quotas.get(table,0),len(items))
        sample+=rng.sample(items,k)
    return sample,{t:len(v) for t,v in by.items()}

def build_precision_sheet(db_path,manifest,out_dir,quotas=None,seed=20261122,root=ROOT):
    from openpyxl import Workbook
    from openpyxl.worksheet.datavalidation import DataValidation
    from openpyxl.styles import Font,PatternFill,Alignment
    docs={r['pe_id']:r for r in manifest['documents']}
    with closing(sqlite3.connect(Path(db_path).resolve().as_uri()+'?mode=ro',uri=True)) as db:
        db.row_factory=sqlite3.Row;pop=population(db);sample,popn=draw_sample(pop,quotas,seed)
    out=Path(out_dir);out.mkdir(parents=True,exist_ok=True)
    stamp=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S');path=out/f'precision_audit_{stamp}.xlsx'
    wb=Workbook();ws=wb.active;ws.title='Audit'
    ws.append(['audit_id','bank','year','table','what it is','field','value_stored','value_as_printed','supporting_text (from the PDF)','pdf_page','open_pdf','VERDICT (Y / P / N)','note'])
    ids=[]
    for i,s in enumerate(sample,1):
        d=docs.get(s['pe_id'],{});pdf=Path(root)/d['path'] if d.get('path') else None
        ws.append([f'A{i:04d}',d.get('institution_name'),(d.get('exam_date') or '')[:4],s['table'].replace('table_','').replace('_',' '),s['about'],s['field'],s['value'],s['printed'],s['quote'],s['page'],'open PDF',None,None])
        c=ws.cell(ws.max_row,11)
        if pdf:c.hyperlink=os.path.relpath(pdf,out);c.font=Font(color='0563C1',underline='single')
        for cell in ws[ws.max_row]:
            if isinstance(cell.value,str) and cell.value[:1] in '=+-@':cell.data_type='s'
        ids.append(dict(audit_id=f'A{i:04d}',table=s['table'],record=s['record'],field=s['field'],pe_id=s['pe_id']))
    for c in ws[1]:c.font=Font(bold=True,color='FFFFFF');c.fill=PatternFill('solid',fgColor='305496');c.alignment=Alignment(wrap_text=True)
    ws.freeze_panes='A2';ws.auto_filter.ref=ws.dimensions
    for col,w in zip('ABCDEFGHIJKLM',(9,28,6,22,26,22,22,18,70,9,11,18,30)):ws.column_dimensions[col].width=w
    dv=DataValidation(type='list',formula1='"Y,P,N"',allow_blank=True);ws.add_data_validation(dv);dv.add(f'L2:L{ws.max_row}')
    h=wb.create_sheet('HOW TO');
    for line in ('How to do the precision audit','1. For each row, click "open PDF" and go to pdf_page (page 1 = first page of the file).','2. Read the supporting_text on that page. Does the PDF really say what value_stored says, for the right bank, area, product and column?',
                 '3. Type Y = correct, P = partly correct (right idea, wrong detail), N = wrong or not in the PDF. Leave blank only if you did not check.','4. Judge the VALUE, not the formatting (23.4 vs 23.40 is fine).',
                 '5. Do not look at any other sheet or tool while doing it; the order is random on purpose.','6. Save, then run:  cra audit score --sheet <this file>'):h.append([line])
    h.column_dimensions['A'].width=140;wb.save(path)
    write_json(out/f'precision_audit_{stamp}.manifest.json',dict(sheet=path.name,seed=seed,population=popn,quotas={t:min((quotas or QUOTAS).get(t,0),n) for t,n in popn.items()},items=ids,database_sha256=sha256_file(db_path),created=stamp))
    return path

from .io import wilson

def score_precision(sheet_path,manifest_path=None):
    """Turn verdicts into precision per table (Wilson interval) and a population-weighted overall figure."""
    from openpyxl import load_workbook
    sheet_path=Path(sheet_path);mp=Path(manifest_path) if manifest_path else sheet_path.with_suffix('.manifest.json')
    man=read_json(mp);ws=load_workbook(sheet_path,data_only=True)['Audit']
    by={i['audit_id']:i for i in man['items']};per={};wrong=[];seen=0
    for row in ws.iter_rows(min_row=2,values_only=True):
        aid,verdict=row[0],(str(row[11]).strip().upper() if row[11] else '')
        if aid not in by:continue
        seen+=1
        if verdict not in ('Y','P','N'):continue
        t=by[aid]['table'];c=per.setdefault(t,dict(Y=0,P=0,N=0));c[verdict]+=1
        if verdict=='N':wrong.append(dict(audit_id=aid,bank=row[1],table=t,field=row[5],stored=row[6],page=row[9],note=row[12]))
    out=dict(sheet=sheet_path.name,items=len(man['items']),answered=sum(sum(c.values()) for c in per.values()),per_table={},wrong=wrong)
    wsum=var=0.0;N=sum(man['population'].values())
    for t,c in sorted(per.items()):
        n=sum(c.values());strict=c['Y']/n;lenient=(c['Y']+c['P'])/n
        out['per_table'][t]=dict(n=n,correct=c['Y'],partly=c['P'],wrong=c['N'],strict_precision=round(strict,4),lenient_precision=round(lenient,4),strict_ci95=wilson(c['Y'],n),population=man['population'].get(t))
        w=man['population'][t]/N;ps=(c['Y']+.5)/(n+1);wsum+=w*strict;var+=w*w*ps*(1-ps)/n
    covered=sum(man['population'][t] for t in per)/N if N else 0
    if per:out['overall_strict_precision']=round(wsum/covered,4) if covered else None;out['overall_ci95_approx']=[round(max(0,wsum/covered-1.96*math.sqrt(var)/covered),4),round(min(1,wsum/covered+1.96*math.sqrt(var)/covered),4)] if covered else None
    out['population_covered']=round(covered,3);out['note']='Precision = share of EXTRACTED values that are right. It does not measure values the pipeline missed (recall); that needs the blind coding of whole documents.'
    return out

# ---------- scanned pages ----------
def build_scan_worksheet(db_path,manifest,out_dir,root=ROOT,max_edge=1500):
    from .prepare import render_page_png
    docs={r['pe_id']:r for r in manifest['documents']};out=Path(out_dir);out.mkdir(parents=True,exist_ok=True);rows=[]
    with closing(sqlite3.connect(db_path)) as db:
        db.row_factory=sqlite3.Row
        pages=db.execute("select pe_id,pdf_page from review_flags where kind='image_review_required' and status='open' order by pe_id,pdf_page").fetchall()
        from . import reviewstore
        st=reviewstore.open_store(root);vis=st.vision();st.close();kcache={}
        def vget(pe,pg,it):
            k=(pe,it['table_name'])
            if k not in kcache:kcache[k]=reviewstore.stable_keys(db,*k)
            return vis.get((pe,pg,it['table_name'],kcache[k].get(it['record_id'],it['record_id']),it['field_name']),('',''))
        by={}
        for p in pages:by.setdefault(p['pe_id'],[]).append(p['pdf_page'])
        for pe,plist in by.items():
            d=docs[pe];folder=out/f"{d['agency']}_{pe[-8:]}";folder.mkdir(exist_ok=True);parts=[]
            for pg in plist:
                png,_=render_page_png(Path(root)/d['path'],pg,max_edge);name=f'p{pg:04d}.png';(folder/name).write_bytes(png)
                items=db.execute('select table_name,record_id,field_name,evidence_verbatim,value_as_printed from field_evidence where pe_id=? and pdf_page=? order by table_name,record_id,field_name',(pe,pg)).fetchall()
                trs=[]
                for it in items:
                    v=vget(pe,pg,it)
                    trs.append(f"<tr><td>{html.escape(it['table_name'][6:20])}</td><td>{html.escape(it['field_name'])}</td><td>{html.escape(str(it['value_as_printed'] or ''))}</td><td>{html.escape(it['evidence_verbatim'][:200])}</td><td>{html.escape(v[0])}</td><td>{html.escape(v[1][:80])}</td></tr>")
                parts.append(f"<section><h2>PDF page {pg}</h2><img src='{name}' style='max-width:100%;border:1px solid #999'><table><tr><th>table</th><th>field</th><th>value</th><th>text the pipeline relied on</th><th>vision check</th><th>vision saw</th></tr>{''.join(trs)}</table></section>")
                rows.append([pe,d['institution_name'],d['agency'],pg,len(items),sum(1 for it in items if vget(pe,pg,it)[0]=='supported'),''])
            (folder/'index.html').write_text(f"<!doctype html><meta charset='utf-8'><title>{html.escape(d['institution_name'])}</title><style>body{{font-family:sans-serif;max-width:1100px;margin:1em auto}}table{{border-collapse:collapse;width:100%;font-size:13px}}td,th{{border:1px solid #bbb;padding:3px 6px;vertical-align:top}}th{{background:#305496;color:#fff}}</style><h1>{html.escape(d['institution_name'])} ({d['agency']}, {d['pages']} pages)</h1><p>For each page: compare the text the pipeline relied on with the image. If every value is right, mark the page verified in <b>pages_to_attest.csv</b>.</p>{''.join(parts)}",encoding='utf-8')
    with (out/'pages_to_attest.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.writer(f);w.writerow(['pe_id','bank','agency','pdf_page','values_on_page','vision_supported','verified (Y)']);w.writerows(rows)
    return dict(documents=len(by),pages=len(rows),folder=str(out))

def attest_from_sheet(db,manifest,csv_path,reviewer,store=None):
    from . import review
    docs={r['pe_id']:r for r in manifest['documents']};by={}
    with open(csv_path,newline='',encoding='utf-8') as f:
        for r in csv.DictReader(f):
            if (r.get('verified (Y)') or '').strip().upper() in ('Y','YES','OK') and r['pe_id'] in docs:by.setdefault(r['pe_id'],[]).append(int(r['pdf_page']))
    n=0
    for pe,pgs in by.items():review.attest_pages(db,pe,docs[pe]['sha256'],pgs,reviewer,'attested from the scanned-page worksheet',store);n+=len(pgs)
    return n
