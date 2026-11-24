"""Automated review flags over a staged document. Flags only: printed values are never changed."""
from collections import defaultdict
import re
from datetime import date
from pathlib import Path

from .io import read_json
from .paths import ROOT
from .research import TABLES

VALIDATION_KINDS={'rating_differs_from_ffiec','exam_type_differs_from_ffiec','area_heading_without_row','percent_sum','incomplete_distribution','impossible_percent','impossible_count','rating_out_of_set','date_inconsistent','date_differs_from_ffiec','identity_mismatch','missing_table_family','table_family_empty','missing_evidence','unlinked_context'}
PCT_FIELDS=('bank_count_pct','bank_dollar_pct','aggregate_pct','demographic_pct')
MAIN=('low','moderate','middle','upper')

def inventory(root=ROOT):
    return read_json(Path(root)/'config/field_inventory.json')

def rows(db,table,pe_id):
    return [dict(r) for r in db.execute(f'SELECT * FROM {table} WHERE pe_id=?',(pe_id,))]

def validate_document(db,pe_id,manifest_record=None,inv=None,tolerance=1.5):
    inv=inv or inventory();flags=[]
    def flag(kind,**kw):flags.append(dict(kind=kind,**kw))
    a=rows(db,'table_a_exam_level',pe_id)
    if not a:flag('missing_table_family',table='table_a_exam_level');return flags
    a=a[0]
    # ratings and dates
    allowed={x.casefold() for x in inv['allowed_overall_ratings']}
    if a.get('rating_overall') and ' '.join(a['rating_overall'].split()).casefold() not in allowed:
        flag('rating_out_of_set',table='table_a_exam_level',record=pe_id,field='rating_overall',value=a['rating_overall'])
    def d(x):
        try:return date.fromisoformat(x) if x else None
        except ValueError:return None
    exam,end,start,prior=d(a.get('exam_date')),d(a.get('eval_period_end')),d(a.get('eval_period_start')),d(a.get('prior_exam_date'))
    if exam and end and end>exam:flag('date_inconsistent',record=pe_id,detail='evaluation period ends after the examination date')
    if start and end and start>end:flag('date_inconsistent',record=pe_id,detail='evaluation period starts after it ends')
    if exam and prior and prior>=exam:flag('date_inconsistent',record=pe_id,detail='prior exam is not before the examination date')
    if manifest_record and exam and manifest_record.get('exam_date') and manifest_record['exam_date']!=a['exam_date']:
        flag('date_differs_from_ffiec',record=pe_id,pdf_date=a['exam_date'],ffiec_date=manifest_record['exam_date'],
             basis=manifest_record.get('date_basis'))
    pid=str(a.get('agency_id') or '');mid=str((manifest_record or {}).get('agency_id') or '')
    if pid.isdigit() and mid.isdigit() and int(pid)!=int(mid):
        flag('identity_mismatch',record=pe_id,pdf_id=pid,manifest_id=mid)
    if manifest_record:   # the regulators' own listing is a non-AI source for these fields
        fr=(manifest_record.get('rating') or '').strip().casefold();got=(a.get('rating_overall') or '').strip().casefold().rstrip('.')
        if fr and got and fr!=got:flag('rating_differs_from_ffiec',table='table_a_exam_level',record=pe_id,field='rating_overall',pdf=a['rating_overall'],ffiec=manifest_record['rating'])
        fe=(manifest_record.get('exam_type') or '').strip().casefold()
        if fe and a.get('exam_type') and fe!=a['exam_type'].strip().casefold():flag('exam_type_differs_from_ffiec',table='table_a_exam_level',record=pe_id,field='exam_type',pdf=a['exam_type'],ffiec=manifest_record['exam_type'])
    # required families
    exam_type=a.get('exam_type') or (manifest_record or {}).get('exam_type') or 'other'
    for table in inv['required_tables_by_exam_type'].get(exam_type,['table_a_exam_level']):
        if not db.execute(f'SELECT 1 FROM {table} WHERE pe_id=? LIMIT 1',(pe_id,)).fetchone():
            flag('missing_table_family',table=table,detail=f'exam type {exam_type}')
    for table in inv['expected_if_present']:
        if not db.execute(f'SELECT 1 FROM {table} WHERE pe_id=? LIMIT 1',(pe_id,)).fetchone():
            flag('table_family_empty',table=table,detail='verify the evaluation has none')
    # distributions
    groups=defaultdict(list)
    drows=rows(db,'table_d_distribution_measures',pe_id)
    # text-line tables: consecutive line numbers on one page are ONE table; a gap starts the next table on that page
    lines=sorted((int(m.group(1)),int(m.group(2)),r['distribution_id']) for r in drows for m in [re.search(r':D:p(\d+)l(\d+)$',r['distribution_id'])] if m)
    run={};prev=None;n=0
    for pg,ln,did in lines:
        if prev is None or pg!=prev[0] or ln-prev[1]>1:n+=1
        run[did]=n;prev=(pg,ln)
    for r in drows:
        for f in PCT_FIELDS:
            v=r.get(f)
            if v is not None and not 0<=v<=100:flag('impossible_percent',table='table_d_distribution_measures',record=r['distribution_id'],field=f,value=v)
        for f in ('bank_count',):
            if r.get(f) is not None and r[f]<0:flag('impossible_count',table='table_d_distribution_measures',record=r['distribution_id'],field=f,value=r[f])
        rowgroup=r['distribution_id'].rsplit(':',1)[0] if re.search(r'[rl]\d+:[^:]+$',r['distribution_id']) else ''   # one table row of an areas-down-the-side table
        groups[(r['aa_id'],r['product_id'],r['dimension'],r['years'],r['table_label'],r['page'],rowgroup,run.get(r['distribution_id']))].append(r)
    for key,members in groups.items():
        cats={m['category']:m for m in members}
        for f in PCT_FIELDS:
            vals=[m[f] for m in members if m.get(f) is not None]
            if len(vals)<2:continue
            have_main=all(c in cats and cats[c].get(f) is not None for c in MAIN)
            total=sum(vals)
            if not have_main:
                if total>100+tolerance:flag('percent_sum',table='table_d_distribution_measures',record=members[0]['distribution_id'],field=f,detail=f'partial categories already sum to {total:.1f}')
                else:flag('incomplete_distribution',table='table_d_distribution_measures',record=members[0]['distribution_id'],field=f,detail='not all of low/moderate/middle/upper were read')
            elif abs(total-100)>tolerance+ (0 if 'not available' in cats else 0):
                flag('percent_sum',table='table_d_distribution_measures',record=members[0]['distribution_id'],field=f,detail=f'sums to {total:.1f}')
    # evidence coverage
    covered={(r[0],r[1],r[2]) for r in db.execute('SELECT table_name,record_id,field_name FROM field_evidence WHERE pe_id=?',(pe_id,))}
    for table,(pk,refs) in TABLES.items():
        for r in rows(db,table,pe_id):
            for f,v in r.items():
                if v is not None and f not in {pk,*refs} and (table,r[pk],f) not in covered:
                    flag('missing_evidence',table=table,record=r[pk],field=f)
    # unlinked context when several areas / products exist
    n_aa=db.execute('SELECT count(*) FROM table_c_assessment_areas WHERE pe_id=?',(pe_id,)).fetchone()[0]
    if n_aa>1:
        for r in db.execute('SELECT conclusion_id FROM table_e_examiner_conclusions WHERE pe_id=? AND aa_id IS NULL',(pe_id,)):
            flag('unlinked_context',table='table_e_examiner_conclusions',record=r[0],detail='no assessment area link (several areas exist)')
    return flags

def compare_runs(db_a,db_b,pe_id):
    """Field-level disagreement between two independent extractions of one document."""
    out=[]
    for table,(pk,refs) in TABLES.items():
        A={r[pk]:r for r in rows(db_a,table,pe_id)};B={r[pk]:r for r in rows(db_b,table,pe_id)}
        for key in A.keys()|B.keys():
            ra,rb=A.get(key),B.get(key)
            if ra is None or rb is None:
                out.append(dict(kind='run_disagreement',table=table,record=key,detail='row present in one run only'));continue
            for f in ra:
                if f not in {pk,*refs} and ra[f]!=rb.get(f):
                    out.append(dict(kind='run_disagreement',table=table,record=key,field=f,a=ra[f],b=rb.get(f)))
    return out


def compare_conclusions(db_a,db_b,pe_id):
    """Table E agreement by (cited page, normalised phrase), independent of positional ids."""
    from collections import Counter
    from .research import norm
    def keys(db):
        c=Counter()
        for r in db.execute("""select e.label_verbatim l,(select pdf_page from field_evidence f where f.record_id=e.conclusion_id and f.field_name='label_verbatim') p
                               from table_e_examiner_conclusions e where e.pe_id=?""",(pe_id,)):c[(r['p'],norm(r['l'] or ''))]+=1
        return c
    a,b=keys(db_a),keys(db_b)
    return dict(matched=sum((a&b).values()),only_a=sum((a-b).values()),only_b=sum((b-a).values()))


AREA_HEADING=re.compile(r"^[A-Z][\w .,'/\-\u2013]{2,55}\s(?:MA|MSA|Non-MSA|Multistate MSA|Counties|County)\s*$")

NOT_AN_AREA=re.compile(r'\b(table|summary|poverty|demographic|information|distribution|investments?|loans?|by|for|total)\b|[-\u2013]\s',re.I)   # a table title, not an area heading

def completeness(db,pe_id,bundle):
    """Assessment-area headings printed in the PDF that have no Table C row (a completeness check; informational)."""
    from .areas import area_parts,same_area
    have=[area_parts(r[0]) for r in db.execute('select aa_name from table_c_assessment_areas where pe_id=? and aa_name is not null',(pe_id,))]
    flags=[];seen=set()
    for p in bundle['pages']:
        for line in p['lines'][:6]:
            if AREA_HEADING.match(line.strip()) and not NOT_AN_AREA.search(line) and len(line.split())>=2 and line.strip().split()[0].upper() not in ('CITY','MSA','MA'):
                k=area_parts(line)
                if k.base and (k.base,k.states) not in seen and not any(same_area(k,h) for h in have):
                    seen.add((k.base,k.states));flags.append(dict(kind='area_heading_without_row',page=p['page'],name=line.strip()[:70],detail='an assessment-area heading is printed here but Table C has no such area'))
    return flags
