"""Compare independently coded references with frozen, uncorrected predictions.

Omissions and false additions stay in the denominators; a missing holdout document or a zero
denominator yields "not evaluable" (None), never a pass."""
import argparse
from collections import Counter,defaultdict
import math
from pathlib import Path
import random

from .io import read_json,sha256_file,write_json
from .research import norm

def split(final,seed=20261102):
    rows=sorted(final['documents'],key=lambda r:r['pe_id'])
    if len(rows)!=44 or len({r['pe_id'] for r in rows})!=44:
        raise ValueError('This split requires the final 44-document pilot')
    named=set(final['development_ids'])
    candidates=[r for r in rows if r['pe_id'] not in named]
    if len(candidates)!=40 or len(named)!=4:raise ValueError('Expected four named documents')
    rng=random.Random(seed); rng.shuffle(candidates)
    for _ in range(10000):
        holdout=candidates[:12]
        if {r['agency'] for r in holdout}=={'OCC','FDIC','FRB'} and len({r['exam_type'] for r in holdout})==3 and any(r['scan_status']=='scanned' for r in holdout):
            holdout_ids={r['pe_id'] for r in holdout}
            return {'seed':seed,'development':sorted(named),'holdout':sorted(holdout_ids),
                    'calibration':sorted(r['pe_id'] for r in candidates[12:])}
        rng.shuffle(candidates)
    raise ValueError('No representative holdout found')

def same(a,b):
    if isinstance(a,(int,float)) and isinstance(b,(int,float)) and not isinstance(a,bool) and not isinstance(b,bool):
        return math.isclose(float(a),float(b),abs_tol=1e-9)
    if isinstance(a,str) and isinstance(b,str):return norm(a)==norm(b)
    return a==b

from .io import wilson

def ratio(n,d):return n/d if d else None

def index_rows(rows,holdout,label):
    dest={};seen=Counter()
    for row in rows:
        if row['pe_id'] not in holdout:raise ValueError(f'{label} includes a non-holdout evaluation')
        base=(row['pe_id'],row['table'],row['context'],row['field'])
        seen[base]+=1
        key=base if seen[base]==1 else base+(seen[base],)
        if seen[base]>1 and base in dest:
            # repeated identity: keep deterministic ordinal keys, never overwrite
            pass
        if key in dest:raise ValueError(f'Duplicate field context: {key}')
        dest[key]=row
    return dest

AGENCY_NAMES={'occ':'OCC','office of the comptroller of the currency':'OCC','comptroller of the currency':'OCC',
              'fdic':'FDIC','federal deposit insurance corporation':'FDIC','federal deposit insurance co':'FDIC',
              'frb':'FRB','federal reserve':'FRB','federal reserve board':'FRB','federal reserve system':'FRB','board of governors of the federal reserve system':'FRB'}
_INV={}
def _identity(table):
    if 'v' not in _INV:
        from .validate import inventory
        _INV['v']=inventory()['row_identity']
    return _INV['v'].get(table,[])

def canon_enum_like(field,v):
    """'Limited-Scope', 'full-scope evaluation' -> 'limited scope' / 'full scope'; other enumerated values by spelling only."""
    from .research import canonical_enum,enum_values
    n=norm(v)
    if field=='review_scope':
        if 'limited' in n and 'scope' in n:return 'limited scope'
        if 'full' in n and 'scope' in n:return 'full scope'
        return None if len(n)>30 else n
    if field in enum_values():
        c=canonical_enum(field,v);return c if c is not None else v
    return v

def canon_value(field,value):
    """Applied identically to reference and prediction so that spelling and format are not counted as disagreement."""
    if isinstance(value,str):
        v=value.strip()
        if field=='review_scope' or field in ('exam_type','data_source','product','level'):return canon_enum_like(field,v)
        if field=='agency':return AGENCY_NAMES.get(norm(v).rstrip('.'),norm(v))
        if field.endswith('_pct') or field in ('bank_count','universe_count','sample_count'):
            try:
                from .research import number_from
                return float(number_from(v))
            except ValueError:pass
        return v.rstrip('.') if field.startswith('rating') or field=='prior_rating' else v
    return value

def canon_context(table,context):
    from .tasks import link_key,PRODUCT_ALIASES
    from .tables import category
    names=_identity(table)
    parts=context.split('|')
    if not names or len(parts)!=len(names):return context
    out=[]
    for name,x in zip(names,parts):
        if name=='aa_name':x=link_key(x)
        elif name=='product':x=PRODUCT_ALIASES.get(x,x)
        elif name=='category':x=category(x) or x
        elif name=='years':x=''          # period wording is too inconsistent to key on; repeated keys are matched in order
        out.append(x)
    return '|'.join(out)

def canonical_rows(rows):
    return [dict(r,value=canon_value(r['field'],r['value']),context=canon_context(r['table'],r['context'])) for r in rows]

def measure(reference,predicted,holdout,strata=None,targets=None,expected_ids=None,coverage=None):
    """coverage: {pe_id: [tables the reference coded]}. Rows of uncoded (document, table) pairs are excluded from
    both sides and reported as not evaluable instead of being counted as false additions or omissions."""
    scope=None
    if coverage is not None:
        scope={(pe,tb) for pe,tbs in coverage.items() for tb in tbs}
        reference=[r for r in reference if (r['pe_id'],r['table']) in scope];predicted=[r for r in predicted if (r['pe_id'],r['table']) in scope]
    reference=canonical_rows(reference);predicted=canonical_rows(predicted)
    ref=index_rows(reference,holdout,'reference');pred=index_rows(predicted,holdout,'prediction')
    by={};per_doc=defaultdict(Counter)
    for k in ref.keys()|pred.keys():
        a=ref.get(k);b=pred.get(k);count=by.setdefault(k[1],Counter())
        if a is None:state='false_addition'
        elif b is None:state='omission'
        elif not same(a['value'],b['value']):state='mismatch'
        else:state='exact'
        count[state]+=1;per_doc[k[0]][state]+=1
    critical=[k for k,a in ref.items() if a.get('critical')]
    hits=[k for k in critical if k in pred and same(pred[k]['value'],ref[k]['value'])]
    critical_additions=[k for k,b in pred.items() if b.get('critical') and k not in ref]
    e='table_e_examiner_conclusions'
    a={(k[:3],norm(str(r['value']))) for k,r in ref.items() if k[1]==e and k[3]=='label_verbatim' and isinstance(r['value'],str)}
    b={(k[:3],norm(str(r['value']))) for k,r in pred.items() if k[1]==e and k[3]=='label_verbatim' and isinstance(r['value'],str)}
    E_T='table_e_examiner_conclusions'
    hits_noE=[k for k in hits if k[1]!=E_T];crit_noE=[k for k in critical if k[1]!=E_T]
    out={'per_table':{t:dict(c) for t,c in by.items()},
         'table_summary':{t:dict(reference_rows=c['exact']+c['mismatch']+c['omission'],
                                 reference_coverage=ratio(c['exact']+c['mismatch'],c['exact']+c['mismatch']+c['omission']),
                                 value_agreement_when_both_present=ratio(c['exact'],c['exact']+c['mismatch']),
                                 pipeline_only_rows=c['false_addition']) for t,c in by.items()},
         'critical_exact_excluding_conclusions':ratio(len(hits_noE),len(crit_noE)),'critical_denominator_excluding_conclusions':len(crit_noE),'critical_exact':ratio(len(hits),len(critical)),'critical_denominator':len(critical),
         'critical_hits':len(hits),'critical_false_additions':len(critical_additions),
         'critical_exact_ci95':wilson(len(hits),len(critical)),
         'conclusion_precision':ratio(len(a&b),len(b)),'conclusion_recall':ratio(len(a&b),len(a)),
         'conclusion_reference_count':len(a),'conclusion_predicted_count':len(b)}
    expected=set(expected_ids if expected_ids is not None else holdout)
    covered={k[0] for k in ref}
    out['conclusions']=match_conclusions(reference,predicted)
    if scope is not None:
        from .research import TABLES
        out['coverage']={'documents':len({pe for pe,_ in scope}),'document_table_pairs_coded':len(scope),'pairs_possible':len(holdout)*len(TABLES),
                         'tables_not_coded':sorted(set(TABLES)-{tb for _,tb in scope})}
    out['documents_expected']=len(expected);out['documents_with_reference']=len(covered&expected)
    out['reference_complete']=expected<=covered
    out['documents_missing_reference']=sorted(expected-covered)
    if strata:
        keyed=[k for k in critical if k[1] not in (E_T,'table_d_distribution_measures')]   # tables whose rows can be matched by key
        kb=defaultdict(lambda:[0,0])
        for k in keyed:
            for dim in ('agency','era','exam_type','scan_status'):
                x=(dim,strata.get(k[0],{}).get(dim,'unknown'));kb[x][1]+=1;kb[x][0]+=k in hits
        out['strata_keyed_tables']={f'{d}={v}':dict(hits=h,denominator=n,exact=ratio(h,n),ci95=wilson(h,n)) for (d,v),(h,n) in sorted(kb.items())}
        buckets=defaultdict(lambda:[0,0])
        for k in critical:
            for dim in ('agency','era','exam_type','scan_status'):
                s=(dim,strata.get(k[0],{}).get(dim,'unknown'))
                buckets[s][1]+=1;buckets[s][0]+=k in hits
        out['strata']={f'{d}={v}':dict(hits=h,denominator=n,exact=ratio(h,n),ci95=wilson(h,n)) for (d,v),(h,n) in sorted(buckets.items())}
        out['uncovered_strata']=sorted(f'{d}={v}' for d in ('agency','era','exam_type','scan_status')
                                      for v in {s.get(d,'unknown') for s in strata.values()} if (d,v) not in buckets)
    if targets:
        def gate(value,target,needs_complete=True):
            if value is None or (needs_complete and not out['reference_complete']):return None
            return value>=target
        out['gates']={'critical_exact':gate(out['critical_exact'],targets['critical_exact']),
                      'conclusion_precision':gate(out['conclusion_precision'],targets['conclusion_precision']),
                      'conclusion_recall':gate(out['conclusion_recall'],targets['conclusion_recall'])}
        out['passed']=None if any(v is None for v in out['gates'].values()) else all(out['gates'].values())
    return out

STOP={'the','a','an','of','and','to','in','is','are','was','were','bank','banks','that','this','with','for','by','as','its','it','be','has','have'}
def tokens(text):
    import re
    return {w for w in re.findall(r"[a-z0-9]+",norm(str(text or ''))) if w not in STOP}

def conclusion_objects(rows):
    """Group long-format rows of Table E into one object per conclusion (needs row_id; falls back to context)."""
    out={}
    for r in rows:
        if r['table']!='table_e_examiner_conclusions':continue
        o=out.setdefault((r['pe_id'],r.get('row_id') or r['context']),dict(pe_id=r['pe_id'],page=r.get('page')))
        o[r['field']]=r['value']
        if r.get('page') is not None:o['page']=r['page']
    return list(out.values())

def match_conclusions(reference,predicted,threshold=0.6):
    """One-to-one matching of conclusions per document: same cited page and phrase overlap (overlap coefficient
    on content words) >= threshold; exact phrase equality is ranked first. Returns match and error counts plus
    attribute agreement among matched pairs. Span-boundary differences ('adequate responsiveness' vs 'shows
    adequate responsiveness') match leniently but not exactly."""
    ref=conclusion_objects(reference);pred=conclusion_objects(predicted);pairs=[]
    for i,a in enumerate(ref):
        ta=tokens(a.get('label_verbatim'))
        for j,b in enumerate(pred):
            if a['pe_id']!=b['pe_id'] or a.get('page') is None or a.get('page')!=b.get('page'):continue
            tb=tokens(b.get('label_verbatim'))
            if not ta or not tb:continue
            sim=len(ta&tb)/min(len(ta),len(tb))
            exact=norm(str(a.get('label_verbatim')))==norm(str(b.get('label_verbatim')))
            if exact or sim>=threshold:pairs.append((0 if exact else 1,-sim,i,j,exact))
    pairs.sort();ur=set();up=set();matched=[]
    for _,_,i,j,exact in pairs:
        if i in ur or j in up:continue
        ur.add(i);up.add(j);matched.append((ref[i],pred[j],exact))
    n=len(matched);ex=sum(1 for *_,e in matched if e)
    def agree(field,fuzzy=False):
        hit=0
        for a,b,_ in matched:
            x,y=a.get(field),b.get(field)
            if fuzzy:
                tx,ty=tokens(x),tokens(y);hit+= bool(tx and ty and len(tx&ty)/min(len(tx),len(ty))>=0.5) or (not tx and not ty)
            else:hit+= norm(str(x or ''))==norm(str(y or ''))
        return hit/n if n else None
    r=lambda k,d:(k/d if d else None)
    return dict(reference=len(ref),predicted=len(pred),matched=n,matched_exact=ex,
                lenient_precision=r(n,len(pred)),lenient_recall=r(n,len(ref)),exact_precision=r(ex,len(pred)),exact_recall=r(ex,len(ref)),
                level_agreement=agree('level'),category_agreement=agree('category'),criterion_agreement=agree('criterion',True))

def era(year):
    y=int(year)
    return '1997-2004' if y<2005 else '2005-2009' if y<2010 else '2010-2014' if y<2015 else '2015-2019' if y<2020 else '2020+'

def strata_from(manifest):
    return {r['pe_id']:dict(agency=r['agency'],era=era(r['exam_date'][:4]),exam_type=r['exam_type'],scan_status=r['scan_status'])
            for r in manifest['documents']}

def predictions_from_db(db,pe_ids,inv):
    """Long-format rows from a staged/accepted database, using the same context scheme as reference forms."""
    from .research import TABLES
    rows=[];critical=inv['critical_fields']
    for pe in sorted(pe_ids):
        aa={r[0]:r[1] for r in db.execute('SELECT aa_id,aa_name FROM table_c_assessment_areas WHERE pe_id=?',(pe,))}
        prod={r[0]:r[1] for r in db.execute('SELECT product_id,product FROM table_b_products_reviewed WHERE pe_id=?',(pe,))}
        for table,(pk,refs) in TABLES.items():
            for r in db.execute(f'SELECT * FROM {table} WHERE pe_id=? ORDER BY {pk}',(pe,)):
                r=dict(r);r['aa_name']=r.get('aa_name') if table=='table_c_assessment_areas' else aa.get(r.get('aa_id'))
                if table!='table_b_products_reviewed':r['product']=r.get('product') or prod.get(r.get('product_id'))
                ident=[norm(str(r.get(i) or '')) for i in inv['row_identity'][table]]
                context='|'.join(ident) or 'row'
                page=None
                if table=='table_e_examiner_conclusions':
                    ev=db.execute("select pdf_page from field_evidence where record_id=? and field_name='label_verbatim'",(r[pk],)).fetchone();page=ev[0] if ev else None
                for f,v in r.items():
                    if v is None or f in {pk,*refs,'aa_name','product'} and table not in ('table_b_products_reviewed','table_c_assessment_areas'):continue
                    if f.endswith('_id') or f=='page' or f=='pe_id':continue
                    rows.append(dict(pe_id=pe,table=table,context=context,field=f,value=v,critical=f in critical.get(table,[]),row_id=r[pk],page=page))
    return rows

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['split','score'])
    p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--reference',type=Path);p.add_argument('--predicted',type=Path)
    p.add_argument('--final',type=Path,help='final manifest, for strata');p.add_argument('--freeze',type=Path)
    a=p.parse_args();data=read_json(a.input)
    if a.output.exists():p.error('Refusing to overwrite a frozen result')
    if a.command=='split':result=split(data)
    else:
        if not a.reference or not a.predicted:p.error('A frozen reference and uncorrected prediction are required')
        from .validate import inventory
        inv=inventory();ref=read_json(a.reference);pred=read_json(a.predicted)
        manifest=read_json(a.final) if a.final else None
        result=measure(ref['rows'] if isinstance(ref,dict) else ref,pred['rows'] if isinstance(pred,dict) else pred,set(data['holdout']),
                       strata_from(manifest) if manifest else None,inv['targets'])
        result['reference_sha256']=sha256_file(a.reference);result['prediction_sha256']=sha256_file(a.predicted)
    write_json(a.output,result)
if __name__=='__main__':main()
