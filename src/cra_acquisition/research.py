"""Validate structured extraction against page evidence and stage it transactionally.

Rules enforced here: every populated field carries a physical page and a quote that is found on that
page (after typographic normalisation); numeric values must equal the printed literal found in the
quote (never calculated); booleans need a supporting phrase, not a printed 1/0; classified fields
(exam type, product, ...) are exempt from verbatim matching; image-backed pages are allowed but
flagged for reviewer attestation (a worker's own 'image_verified' claim is ignored)."""
import argparse
from contextlib import closing
from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
import sqlite3
import unicodedata

from .__main__ import ROOT, digest
from .io import read_json, write_json

TABLES={
 'table_a_exam_level':('pe_id',()),
 'table_b_products_reviewed':('product_id',('pe_id',)),
 'table_c_assessment_areas':('aa_id',('pe_id',)),
 'table_d_distribution_measures':('distribution_id',('pe_id','aa_id','product_id')),
 'table_e_examiner_conclusions':('conclusion_id',('pe_id','aa_id','product_id')),
 'ltd_peers':('peer_id',('pe_id',)),
}
NUMERIC={'INTEGER','NUMERIC','REAL'}
BOOLEAN_FIELDS={'cd_test_optional_elected','is_major_product'}
DATE_FIELDS={'exam_date','eval_period_start','eval_period_end','prior_exam_date','as_of_date'}
CLASSIFIED={'exam_type','product','data_source','review_scope','dimension','level','category','criterion','agency'}
VERBATIM_PASSAGES={'hmda_status_text','community_contact_text','credit_needs_text','weight_text','data_source_verbatim','exam_type_verbatim','label_verbatim','benchmark_emphasis_text','context_reasons_text'}
EXEMPT_FROM_QUOTE=CLASSIFIED|{'counties','tract_list','tract_counts_by_income','state','aa_name','msa_or_nonmsa'}
IMAGE_REVIEW={'ocr_layer','image_no_text','no_text_content','sparse','ocr_review_required'}

_MAP=str.maketrans({'‘':"'",'’':"'",'“':'"','”':'"','–':'-','—':'-','−':'-',
                    ' ':' ','­':'','•':'*','·':'*','':'*'})
from .io import collapse

def norm(value):
    """Typographic normalisation used on BOTH sides of every quote comparison."""
    text=unicodedata.normalize('NFKC',value).translate(_MAP).casefold()
    text=re.sub(r'(?<=\w)-\s+(?=[a-z])','-',text)      # 'low- income' / 'Non- MSA' style line wraps
    return collapse(text)

def printed_in_quote(literal,quote):
    """A printed number must appear as a whole number (93 is not found inside 93.3 or 193)."""
    lit=norm(literal)
    if re.match(r'^[\s$(\-]*\d',lit):
        return re.search(r'(?<![\d.,])'+re.escape(lit)+r'(?!\d|[.,]\d)',quote) is not None
    return lit in quote

def ordered_words_in(value,quote):
    """All words of `value` appear in `quote` in order (wide tables print one header word per column/line)."""
    pos=0
    for w in re.findall(r"[a-z0-9]+",norm(value)):
        k=quote.find(w,pos)
        if k<0:return False
        pos=k+len(w)
    return True

ORDERED_HEADER_FIELDS={'demographic_base'}

_ENUMS={}
def enum_values(root=ROOT):
    """Allowed values of every text column constrained by CHECK (col IN (...)), read from the schema itself."""
    key=str(root)
    if key not in _ENUMS:
        sql=(Path(root)/'schemas/research_schema.sql').read_text(encoding='utf-8')
        out={}
        for col,body in re.findall(r"(\w+)\s+TEXT(?:\s+NOT NULL)?\s+CHECK\s*\(\s*\1\s+IN\s*\(([^)]*)\)\s*\)",sql):
            out[col]=[v.strip().strip("'") for v in body.split(',')]
        _ENUMS[key]=out
    return _ENUMS[key]

def canonical_enum(field,value,root=ROOT):
    """Map 'full-scope', 'Full Scope', 'full_scope' to the allowed 'full scope'; None if it is not an allowed value."""
    allowed=enum_values(root).get(field)
    if allowed is None:return value
    flat=lambda x:re.sub(r'[\s_\-]+',' ',x).strip().casefold()
    return next((a for a in allowed if flat(a)==flat(value)),None)

def columns(db,table):
    return {x[1]:x[2] for x in db.execute('PRAGMA table_info('+table+')')}

def parse_date(text):
    for fmt in ('%Y-%m-%d','%B %d, %Y','%b %d, %Y','%B %d %Y','%m/%d/%Y','%m/%d/%y'):
        try:return datetime.strptime(collapse(text).replace('Sept.','Sep.'),fmt).date()
        except ValueError:continue
    return None

def number_from(literal):
    """Decimal from a printed literal: commas, %, $ and parenthesised negatives; no arithmetic."""
    t=collapse(literal)
    negative=(t.startswith('(') and t.endswith(')')) or t.startswith('-')
    core=re.sub(r'[()$,%\s-]','',t)
    try:v=Decimal(core)
    except InvalidOperation as e:raise ValueError(f'Unverifiable numeric value: {literal!r}') from e
    if not v.is_finite():raise ValueError('Non-finite number')
    return -v if negative else v

def check_field(table,field,sql_type,item,pages,attested=frozenset()):
    """Validate one populated field. Returns (value, evidence_dict, flags). Raises ValueError if unsupported."""
    value=item.get('value');passage=item.get('quote');page=item.get('page')
    if value is None or not isinstance(passage,str) or not collapse(passage):raise ValueError(f'Missing evidence for {field}')
    if isinstance(page,bool) or not isinstance(page,int):raise ValueError('Evidence page must be an integer')
    source=pages.get(page)
    if not source:raise ValueError('Evidence page out of range')
    quote=norm(passage)
    if quote not in norm(source['text']):raise ValueError(f'Quote not present on page {page}: {field}')
    literal=item.get('value_as_printed');flags=[]
    if field in VERBATIM_PASSAGES and isinstance(value,str) and norm(value) not in quote and norm(value) in norm(source['text']):
        passage=value;quote=norm(value)   # the whole passage is verbatim on the cited page: it is its own evidence
    if literal is not None and (not isinstance(literal,str) or not collapse(literal) or not printed_in_quote(literal,quote)):
        raise ValueError(f'Printed value not found in evidence: {field}')
    if field in BOOLEAN_FIELDS:
        if value not in (0,1) or isinstance(value,bool):raise ValueError(f'{field} must be 0 or 1 with a supporting phrase')
    elif sql_type in NUMERIC:
        if isinstance(value,bool) or type(value) not in (int,float) or sql_type=='INTEGER' and type(value)!=int:raise ValueError(f'Invalid numeric type: {field}')
        if field=='page':
            if value!=page:raise ValueError('Distribution page does not match evidence page')
        else:
            if literal is None:raise ValueError(f'Printed literal required for {field}')
            if Decimal(str(value))!=number_from(literal):raise ValueError(f'Derived or mismatched numeric value: {field}')
    else:
        if not isinstance(value,str):raise ValueError(f'Expected text: {field}')
        if field in enum_values():
            canon=canonical_enum(field,value)
            if canon is None:raise ValueError(f'Not an allowed value for {field}: {value!r}')
            value=canon
        if field in DATE_FIELDS:
            if literal is None and parse_date(value) is not None:raise ValueError(f'A date needs its printed text: {field}')
            parsed=parse_date(literal or value)
            if parsed is not None:
                if value!=parsed.isoformat():raise ValueError(f'Date must be supported by the PDF: {field}')
            elif collapse(value)!=collapse(literal or value):raise ValueError('Incomplete dates are kept as printed')
        if field in ORDERED_HEADER_FIELDS:
            if not ordered_words_in(value,quote):raise ValueError(f'Header words not found in order in evidence: {field}')
        elif field not in EXEMPT_FROM_QUOTE and field not in DATE_FIELDS and norm(value) not in quote:
            raise ValueError(f'Value not found in evidence: {field}')
    if field=='aa_name':
        from .areas import area_parts
        page_text=norm(source['text'])
        missing=[w for w in area_parts(value).base.split() if w not in page_text]
        if missing:raise ValueError(f'Area name words not printed on page {page}: {missing}')
    if source.get('page_class',source.get('status')) in IMAGE_REVIEW and page not in attested:
        flags.append(dict(kind='image_review_required',page=page,field=field))
    return value,dict(pdf_page=page,printed_page_label=item.get('printed_page_label'),evidence_verbatim=passage,value_as_printed=literal),flags

def stage(db,pe_id,bundle,proposal,strict=True,attested=frozenset(),flags=None):
    """Validate a complete proposal. strict=False drops unsupported fields (to NULL) and records why
    instead of rejecting the whole document; structural problems always raise."""
    flags=flags if flags is not None else []
    pages={x['page']:x for x in bundle['pages']}
    if proposal['sha256']!=bundle['sha256']:raise ValueError('Proposal has a different PDF checksum')
    raw=proposal['tables']
    if set(raw)!=set(TABLES):raise ValueError('Expected all six tables; include empty child lists')
    if len(raw['table_a_exam_level'])!=1:raise ValueError('Exactly one exam row required')
    selected={}; evidence=[]; seen=set()
    for table,(pk,refs) in TABLES.items():
        allowed=columns(db,table);selected[table]=[]
        for item in raw[table]:
            ids=item['ids']; fields=item['fields']
            if not set(ids)<={pk,*refs} or not set(fields)<=set(allowed)-{pk,*refs}:raise ValueError(f'Unexpected field in {table}')
            ident=ids[pk]
            if not isinstance(ident,str) or not ident or (table,ident) in seen:raise ValueError('Missing or duplicate record ID')
            seen.add((table,ident))
            if (ident if table=='table_a_exam_level' else ids.get('pe_id'))!=pe_id:raise ValueError('Cross-document record')
            row=dict(ids)
            for field,entry in fields.items():
                if entry is None:continue
                try:value,ev,fl=check_field(table,field,allowed[field],entry,pages,attested)
                except (ValueError,KeyError,TypeError,InvalidOperation) as e:
                    if strict:raise ValueError(str(e)) from e
                    flags.append(dict(kind='field_rejected',table=table,record=ident,field=field,reason=str(e)));continue
                row[field]=value
                for f in fl:flags.append(dict(f,table=table,record=ident))
                key=digest(f"{table}|{ident}|{field}|{ev['pdf_page']}|{ev['evidence_verbatim']}".encode())
                evidence.append(dict(evidence_id=key,pe_id=pe_id,table_name=table,record_id=ident,field_name=field,**ev))
            selected[table].append(row)
    # drop child rows whose parent links did not survive field rejection only when linkage is explicit
    return selected,evidence

def save(db,pe_id,bundle,proposal,strict=True,attested=frozenset(),flags=None):
    db.execute('PRAGMA foreign_keys=ON')
    rows,evidence=stage(db,pe_id,bundle,proposal,strict,attested,flags)
    with db:
        db.execute('DELETE FROM field_evidence WHERE pe_id=?',(pe_id,))
        for table in reversed(TABLES):
            db.execute(f'DELETE FROM {table} WHERE pe_id=?',(pe_id,))
        for table,records in [*rows.items(),('field_evidence',evidence)]:
            for row in records:
                names=list(row)
                db.execute(f'INSERT INTO {table} ({",".join(names)}) VALUES ({",".join("?" for _ in names)})',[row[k] for k in names])
    return dict(rows={k:len(v) for k,v in rows.items()},evidence=len(evidence))

def page_bundle(pdf,expected_hash,use_ocr=False):
    """Compatibility wrapper: the single preparation path lives in prepare.py."""
    from .prepare import prepare_pdf
    return prepare_pdf(pdf,expected_hash)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['prepare','commit'])
    p.add_argument('--final',type=Path,required=True);p.add_argument('--pe-id',required=True)
    p.add_argument('--pages',type=Path,required=True);p.add_argument('--proposal',type=Path)
    p.add_argument('--database',type=Path,default=ROOT/'data/research.sqlite')
    p.add_argument('--ocr',action='store_true',help='accepted for compatibility; OCR is queued by page class')
    a=p.parse_args()
    manifest=read_json(a.final)
    record=next((r for r in manifest['documents'] if r['pe_id']==a.pe_id),None)
    if not record or record.get('status')!='verified':p.error('A verified evaluation from the final manifest is required')
    pdf=ROOT/record['path']
    if a.command=='prepare':
        write_json(a.pages,page_bundle(pdf,record['sha256']));return
    if not a.proposal:p.error('--proposal is required')
    from .prepare import parser_info
    pages=read_json(a.pages)
    # bundle must come from this PDF and this parser version; the PDF itself is re-hashed
    from .io import sha256_file
    if sha256_file(pdf)!=record['sha256'] or pages.get('sha256')!=record['sha256']:p.error('Page bundle does not match the verified PDF')
    if pages.get('parser',{}).get('fingerprint')!=parser_info()['fingerprint']:p.error('Page bundle parser version differs; rerun prepare')
    if not a.database.is_file():p.error('Create the database with the research schema first')
    with closing(sqlite3.connect(a.database)) as db:
        print(json.dumps(save(db,a.pe_id,pages,read_json(a.proposal))))

if __name__=='__main__':main()
