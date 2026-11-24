"""One Excel workbook for non-technical analysis: readable joined tables, a data dictionary, a review list, and
the source PDFs beside it. Built from the export's SQLite file; makes no model calls."""
from contextlib import closing
import csv
from pathlib import Path
import shutil
import sqlite3

from .io import read_json
from .paths import ROOT

DICT={
 'pe_id':'Internal ID of the evaluation (one per PDF). Same ID in every table.',
 'agency':'Regulator that issued the evaluation (OCC, FDIC or FRB).',
 'institution_name':'Bank name.','agency_id':'Charter number (OCC), certificate number (FDIC) or RSSD (FRB) printed in the evaluation.',
 'exam_date':'Examination date from the PDF (YYYY-MM-DD).','eval_period_start':'Start of the period the evaluation covers.','eval_period_end':'End of the period the evaluation covers.',
 'exam_type':'small / intermediate small / large / other, from the procedure the evaluation names. Blank = the PDF does not say.',
 'exam_type_verbatim':'The exact wording the PDF uses for the exam type.',
 'rating_overall':'Overall CRA rating (Outstanding, Satisfactory, Needs to Improve, Substantial Noncompliance), as printed.',
 'rating_lending':'Lending test rating.','rating_cd':'Community development test rating.','rating_investment':'Investment test rating (large banks).','rating_service':'Service test rating (large banks).',
 'cd_test_optional_elected':'1 = a small bank elected the optional community development test; 0 = it did not; blank = not stated.',
 'prior_exam_date':'Date of the previous evaluation.','prior_rating':'Rating from the previous evaluation.',
 'total_assets_stated':'Total assets exactly as printed (units vary: thousands, millions).','as_of_date':'Date the assets figure refers to.',
 'ltd_avg':'Bank average loan-to-deposit ratio as printed.','ltd_quarters':'Number of quarters the LTD average covers.','ltd_low':'Lowest LTD ratio in the period.','ltd_high':'Highest LTD ratio in the period.',
 'hmda_status_text':'Sentence about whether the bank reports mortgage data under HMDA.','community_contact_text':'Paragraph about community contacts.','credit_needs_text':'Paragraph about identified credit needs.',
 'product':'Loan product reviewed: home mortgage, small business, small farm, consumer, other.','is_major_product':'1 = the evaluation calls it a major product; 0 = explicitly not major.',
 'weight_text':'Sentence explaining how much weight the product got.','data_source':'Where the product data came from: HMDA, CRA-reported data, complete bank records, examiner sample, unclear.',
 'data_source_verbatim':'The sentence that says so.','universe_count':'Number of loans in the whole population reviewed (as printed).','universe_dollars':'Dollar value of that population (as printed).',
 'sample_count':'Number of loans actually reviewed from a sample.','sample_dollars':'Dollar value of the sample.','loan_years':'Years of loans covered.',
 'inside_aa_count_pct':'Percent of loans (by number) made INSIDE the assessment area.','inside_aa_dollar_pct':'Percent of loan dollars made inside the assessment area.',
 'aa_name':'Assessment area (the geography the bank is judged on).','state':'State of the area.','msa_or_nonmsa':'Metropolitan area or non-metropolitan, as printed.',
 'review_scope':'full scope or limited scope review of that area.','counties':'Counties in the area.','tract_list':'Census tracts, if listed.','tract_counts_by_income':'Number of low/moderate/middle/upper income tracts (JSON text).','census_vintage':'Census/ACS source used for the area demographics.',
 'dimension':'What the row measures: borrower income, business revenue, farm revenue, or census tract income.','category':'The income (low/moderate/middle/upper/not available) or revenue class the row describes.',
 'years':'Period the table covers.','bank_count':'Number of the bank\'s loans in this category.','bank_count_pct':'Percent of the bank\'s loans (by number) in this category.',
 'bank_dollars':'Dollar amount of the bank\'s loans in this category.','bank_dollar_pct':'Percent of the bank\'s loan dollars in this category.',
 'aggregate_pct':'Percent for ALL lenders in the area (the comparison group).','demographic_pct':'Percent of the area\'s population/families/businesses in this category (the comparison base).',
 'demographic_base':'What the demographic percent counts (families, households, owner-occupied units, businesses...).','source_note':'The table\'s source line.','table_label':'Table name in the PDF (e.g. "Table 11").','page':'PDF page the row came from.',
 'criterion':'What the examiner judged (loan-to-deposit ratio, geographic distribution, borrower distribution...).','label_verbatim':'The examiner\'s exact evaluative phrase (e.g. "reflects reasonable distribution").',
 'level':'criterion = whole criterion; income category = one income group; overall assessment = a combined judgment.','benchmark_emphasis_text':'Sentence saying the examiner weighted aggregate or demographic comparisons more.','context_reasons_text':'Sentences explaining the result.',
 'location':'Peer bank location.','assets_stated':'Peer bank assets as printed.','ltd_ratio_stated':'Peer bank loan-to-deposit ratio as printed.',
 'pdf_page':'Physical page of the PDF where the evidence sits (page 1 = first page of the file, not the printed page number).','evidence_verbatim':'The exact text from that page that supports the value.',
 'value_as_printed':'The value exactly as printed (e.g. "92.6%").','table_name':'Which table the value belongs to.','record_id':'Which row it belongs to.','field_name':'Which column it supports.',
}
FRIENDLY={'pe_id':'evaluation_id'}

def _style(ws,widths=None,wrap=()):
    from openpyxl.styles import Font,PatternFill,Alignment
    for c in ws[1]:
        c.font=Font(bold=True,color='FFFFFF');c.fill=PatternFill('solid',fgColor='305496');c.alignment=Alignment(wrap_text=True,vertical='top')
    ws.freeze_panes='A2'
    if ws.max_row>1:ws.auto_filter.ref=ws.dimensions
    for i,col in enumerate(ws.columns,1):
        width=min(60,max(10,max((len(str(c.value)) for c in list(col)[:200] if c.value is not None),default=10)+2))
        ws.column_dimensions[ws.cell(1,i).column_letter].width=(widths or {}).get(i,width)

def _put(ws,row):
    ws.append(row)
    for c in ws[ws.max_row]:
        if isinstance(c.value,str):
            if c.value[:1] in '=+-@' and not c.value.replace('.','',1).replace('-','',1).isdigit():c.data_type='s'   # text, never a formula

def status_lines(status):
    lab=status.get('label','UNVERIFIED');a=status.get('audit') or {}
    if lab=='VALIDATED':return ['STATUS: VALIDATED. Every release check passed, including an independent human reference.']
    if lab=='AUDITED':
        ci=a.get('overall_ci95_approx') or ['?','?']
        return [f"STATUS: AUDITED. A person checked a random sample of {a.get('answered')} values against the PDFs: about {100*a.get('overall_strict_precision',0):.0f}% were right (95% interval {100*ci[0]:.0f}% to {100*ci[1]:.0f}%).",
                'That measures how many extracted values are RIGHT. It does not measure values the extraction MISSED. Anything you rely on should still be checked against its PDF page.']
    return ['STATUS: UNVERIFIED. These values were extracted by an AI model from public PDFs and have NOT been checked by a person.','Use them to explore and to find evaluations worth reading, not as verified facts.']

def build(export_dir,root=ROOT,copy_pdfs=True):
    from openpyxl import Workbook
    from openpyxl.styles import Font,Alignment
    export_dir=Path(export_dir);db_path=export_dir/'research.sqlite'
    manifest=read_json(export_dir/'inventory.json');status=read_json(export_dir/'RELEASE_STATUS.json')
    docs={r['pe_id']:r for r in manifest['documents']}
    wb=Workbook();ws=wb.active;ws.title='READ ME FIRST'
    text=['CRA Performance Evaluation pilot: data workbook','',
      *status_lines(status),'Every value points to the PDF page it came from (sheet "Evidence").','',
      'How to use this workbook','  1. Start with "Evaluations": one row per bank evaluation (44 in total).',
      '  2. The sheets "Exam summary", "Products", "Areas", "Distributions", "Conclusions" and "LTD peers" are the six research tables, with bank names added so you do not need the IDs.',
      '  3. Click the arrow on any column header to filter or sort. Insert > PivotTable to summarise (recipes are in README.md).',
      '  4. "Evidence" shows, for every value, the exact PDF text and page. "Phrases" counts the examiner phrases. "Needs review" lists the problems the checks found.',
      '  5. "Data dictionary" explains every column. The PDFs are in the "source_pdfs" folder next to this file.','',
      'Empty cell = the PDF does not print that value (it is NOT zero). A 0 means a zero was printed.',
      'Percentages are stored as numbers (23.4 means 23.4%).','',
      'KNOWN LIMITS (full list in README.md, Section 8): no person has checked these values; no hand-coded reference exists (only a second AI reading);',
      'older Federal Reserve evaluations have few distribution rows; very large multi-state evaluations have incomplete assessment-area lists;',
      'a blank cell can mean "not printed" or "not confirmed" (see Needs review); four evaluations are scans whose text was never compared with the page images.']
    for i,t in enumerate(text,1):
        ws.cell(i,1,t)
        if i in (1,3,6):ws.cell(i,1).font=Font(bold=(i!=3),size=14 if i==1 else 11,color='C00000' if i==3 else '000000')
    ws.column_dimensions['A'].width=150
    pdfdir=export_dir/'source_pdfs'
    if copy_pdfs:
        pdfdir.mkdir(exist_ok=True)
        for r in manifest['documents']:
            src=Path(root)/r['path'];dst=pdfdir/Path(r['path']).name
            if src.is_file() and not dst.exists():shutil.copyfile(src,dst)
    with closing(sqlite3.connect(db_path)) as db:
        db.row_factory=sqlite3.Row
        rssd={(r['agency'],r['agency_id']):r['rssd_id'] for r in db.execute("select agency,agency_id,rssd_id from rssd_crosswalk")} if db.execute("select 1 from sqlite_master where name='rssd_crosswalk'").fetchone() else {}
        name=lambda pe:docs[pe]['institution_name'] if pe in docs else pe
        w=wb.create_sheet('Evaluations');_put(w,['evaluation_id','agency','bank','city','state','exam_date_listing','exam_type_listing','rating_listing','pages','scanned','rssd_id','pdf_file (click)'])
        for r in sorted(manifest['documents'],key=lambda r:(r['agency'],r['exam_date'])):
            _put(w,[r['pe_id'],r['agency'],r['institution_name'],r.get('city'),r.get('state'),r['exam_date'],r['exam_type'],r.get('rating'),r['pages'],'yes' if r['scan_status']=='scanned' else 'no',rssd.get((r['agency'],str(r['agency_id']))),Path(r['path']).name])
            c=w.cell(w.max_row,12);c.hyperlink=f"source_pdfs/{Path(r['path']).name}";c.font=Font(color='0563C1',underline='single')
        _style(w)
        def sheet(title,sql,lead):
            rows=db.execute(sql).fetchall();w=wb.create_sheet(title)
            if not rows:_put(w,['(no rows)']);return
            _put(w,[FRIENDLY.get(k,k) for k in rows[0].keys()])
            for r in rows:_put(w,[r[k] for k in r.keys()])
            _style(w)
        base="a.institution_name as bank, a.agency, substr(a.exam_date,1,4) as year, "
        sheet('Exam summary',"select a.pe_id,a.agency,a.institution_name as bank,a.agency_id,a.exam_date,a.eval_period_start,a.eval_period_end,a.exam_type,a.exam_type_verbatim,a.rating_overall,a.rating_lending,a.rating_cd,a.rating_investment,a.rating_service,a.cd_test_optional_elected,a.prior_exam_date,a.prior_rating,a.total_assets_stated,a.as_of_date,a.ltd_avg,a.ltd_quarters,a.ltd_low,a.ltd_high,a.hmda_status_text,a.community_contact_text,a.credit_needs_text from table_a_exam_level a order by a.agency,a.exam_date",'a')
        sheet('Products',f"select {base}b.product,b.is_major_product,b.data_source,b.universe_count,b.universe_dollars,b.sample_count,b.sample_dollars,b.loan_years,b.inside_aa_count_pct,b.inside_aa_dollar_pct,b.weight_text,b.data_source_verbatim,b.eval_period_start,b.eval_period_end,b.pe_id from table_b_products_reviewed b join table_a_exam_level a using(pe_id) order by a.agency,a.exam_date,b.product",'b')
        sheet('Areas',f"select {base}c.aa_name,c.state,c.msa_or_nonmsa,c.review_scope,c.counties,c.tract_counts_by_income,c.census_vintage,c.tract_list,c.pe_id from table_c_assessment_areas c join table_a_exam_level a using(pe_id) order by a.agency,a.exam_date,c.aa_name",'c')
        sheet('Distributions',f"select {base}c.aa_name as area,b.product,d.dimension,d.category,d.years,d.bank_count,d.bank_count_pct,d.bank_dollars,d.bank_dollar_pct,d.aggregate_pct,d.demographic_pct,d.demographic_base,d.table_label,d.page as pdf_page,d.source_note,d.pe_id from table_d_distribution_measures d join table_a_exam_level a using(pe_id) left join table_c_assessment_areas c on c.aa_id=d.aa_id left join table_b_products_reviewed b on b.product_id=d.product_id order by a.agency,a.exam_date,d.page,d.distribution_id",'d')
        sheet('Conclusions',f"select {base}e.criterion,e.category,c.aa_name as area,b.product,e.years,e.label_verbatim as examiner_phrase,e.level,e.benchmark_emphasis_text,e.context_reasons_text,(select min(f.pdf_page) from field_evidence f where f.record_id=e.conclusion_id and f.field_name='label_verbatim') as pdf_page,e.pe_id from table_e_examiner_conclusions e join table_a_exam_level a using(pe_id) left join table_c_assessment_areas c on c.aa_id=e.aa_id left join table_b_products_reviewed b on b.product_id=e.product_id order by a.agency,a.exam_date,pdf_page,e.conclusion_id",'e')
        sheet('LTD peers',f"select {base}p.institution_name as peer_bank,p.location,p.assets_stated,p.ltd_ratio_stated,p.pe_id from ltd_peers p join table_a_exam_level a using(pe_id) order by a.agency,a.exam_date",'p')
        sheet('Evidence',"select a.institution_name as bank,f.table_name,f.record_id,f.field_name,f.pdf_page,f.printed_page_label,f.value_as_printed,f.evidence_verbatim,f.pe_id from field_evidence f join table_a_exam_level a using(pe_id) order by a.agency,a.exam_date,f.pdf_page",'f')
        w=wb.create_sheet('Phrases');_put(w,['agency','exam_type','examiner_phrase','times_used'])
        with (export_dir/'examiner_phrase_frequency.csv').open(newline='',encoding='utf-8') as fh:
            for r in csv.DictReader(fh):_put(w,[r['agency'],r['exam_type'],r['phrase'],int(r['count'])])
        _style(w)
        w=wb.create_sheet('Needs review');_put(w,['bank','agency','pages_in_pdf','problem','table','field','pdf_page','details','level'])
        from .review import ERROR_KINDS,REVIEW_KINDS
        import json
        for r in db.execute("select * from review_flags where status='open' order by pe_id,kind"):
            d=json.loads(r['detail'] or '{}');doc=docs.get(r['pe_id'],{})
            _put(w,[name(r['pe_id']),doc.get('agency'),doc.get('pages'),r['kind'],r['table_name'],r['field_name'],r['pdf_page'],'; '.join(f'{k}={str(v)[:80]}' for k,v in d.items()),'error' if r['kind'] in ERROR_KINDS else ('review' if r['kind'] in REVIEW_KINDS else 'info')])
        _style(w)
        w=wb.create_sheet('Data dictionary');_put(w,['column','meaning'])
        seen=set()
        for t in ('table_a_exam_level','table_b_products_reviewed','table_c_assessment_areas','table_d_distribution_measures','table_e_examiner_conclusions','ltd_peers','field_evidence'):
            for col in [c[1] for c in db.execute(f'pragma table_info({t})')]:
                if col not in seen:seen.add(col);_put(w,[col,DICT.get(col,'(identifier used to link tables)')])
        _style(w,{1:28,2:120})
        for sh in wb.worksheets[1:]:
            for row in sh.iter_rows(min_row=2):
                for c in row:
                    if isinstance(c.value,str) and len(c.value)>60:c.alignment=Alignment(wrap_text=False)
    out=export_dir/'CRA_pilot_tables.xlsx';wb.save(out);return out
