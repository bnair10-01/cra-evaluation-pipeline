"""Conservative source-backed baseline; does not certify full extraction."""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import re
import time
from datetime import datetime

import pypdfium2 as pdfium
from cra_acquisition.research import TABLES,save,collapse
from cra_acquisition.workflow import write_json
from cra_acquisition.__main__ import ROOT

MONTH=r'(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s*\d{4}'
AGENCY={'FDIC':r'Federal Deposit Insurance Corporation',
        'OCC':r'Office of the Comptroller of the Currency|Comptroller of the Currency',
        'FRB':r'Federal Reserve Bank(?: of [^\n]+)?|Board of Governors of the Federal Reserve System'}
RATING=r'(Outstanding|High Satisfactory|Low Satisfactory|Satisfactory|Needs to Improve|Substantial Noncompliance)'
RAT_FIELDS={
 'rating_overall':r'(?:This institution is rated\s*[:\-]?\s*|(?:Institution[’\x27]s\s+CRA\s+Rating|Overall CRA Rating)\s*[:\-]\s*)',
 'rating_lending':r'\bThe Lending Test is rated\s*[:\-]?\s*',
 'rating_investment':r'\bThe Investment Test is rated\s*[:\-]?\s*',
 'rating_service':r'\bThe Service Test is rated\s*[:\-]?\s*',
 'rating_cd':r'\bThe (?:Optional )?(?:Community Development(?: \(CD\))?|CD) Test is rated\s*[:\-]?\s*',
}
PRODUCTS={'home mortgage':'home mortgage','small business':'small business','small farm':'small farm','consumer':'consumer'}

def pages_for(doc,rich=False):
    path=ROOT/doc['path']; digest=hashlib.sha256(path.read_bytes()).hexdigest()
    if digest!=doc['sha256']:raise ValueError('PDF hash mismatch')
    pages=[]
    with pdfium.PdfDocument(path) as pdf:
        for i in range(len(pdf)):
            with closing(pdf[i]) as page:
                with closing(page.get_textpage()) as layer:
                    text=layer.get_text_range().replace('\r\n','\n')
                pages.append(dict(page=i+1,text=text,
                    status=('ocr_review_required' if doc['scan_status'] in ('scanned','mixed','uncertain','likely_scanned')
                            else 'text' if collapse(text) else 'no_text')))
    if not pages:raise ValueError('No pages')
    if rich:
        import pdfplumber
        try:
            with pdfplumber.open(path) as pdf:
                for i,page in enumerate(pdf.pages):
                    pages[i].update(words=page.extract_words(),tables=page.extract_tables())
                    page.close()
        except Exception as err:
            return dict(sha256=digest,pages=pages,layout_warning=f'{type(err).__name__}: {err}')
    return dict(sha256=digest,pages=pages)

def field(value,page,quote,literal=None):
    return dict(value=value,page=page['page'],quote=quote,value_as_printed=literal)

def canonical(s):return re.sub(r'[^a-z0-9]+','',s.casefold())

def cover_matches_name(candidate,doc):
    expected=canonical(doc['institution_name']);actual=canonical(candidate)
    # Preserve the printed name; a clear abbreviated match is used only
    # to select a plausible cover line and must additionally have the ID.
    norm=lambda x:x.removeprefix('the').replace('nationalassociation','na').replace('bank','bk').replace('national','natl').replace('trustcompany','tco').replace('trco','tco')
    return actual==expected or norm(actual)==norm(expected)

def proposal(doc,bundle):
    tables={t:[] for t in TABLES};a={};pe=doc['pe_id']
    tables['table_a_exam_level']=[dict(ids={'pe_id':pe},fields=a)]
    pages=bundle['pages']
    for page in pages[:3]:
        text=page['text']; lines=[s.strip() for s in text.splitlines() if s.strip()]
        if not re.search(r'PUBLIC DISCLOSURE',text,re.I) or not re.search(r'PERFORMANCE\s+EVALUATION',text,re.I):continue
        matches=re.search(r'(?:charter\s*(?:number|no\.?|#)|certificate\s*(?:number|no\.?|#)|RSSD\s*(?:ID|No\.?)?|Bank ID)\s*[:#]?\s*(\d+)',text,re.I)
        if matches and int(matches[1])==int(doc['agency_id']):
            a['agency_id']=field(matches[1],page,matches[0],matches[1])
        agency=re.search(AGENCY[doc['agency']],text,re.I)
        if agency:a['agency']=field(doc['agency'],page,agency[0],agency[0])
        disclosure=re.search(r'PUBLIC DISCLOSURE\s+('+MONTH+r')',text,re.I)
        if disclosure:
            printed=disclosure[1]; normal=re.sub(r',\s*',', ',collapse(printed))
            for fmt in ('%B %d, %Y','%b %d, %Y'):
                try:parsed=datetime.strptime(normal,fmt).date().isoformat();break
                except ValueError:parsed=None
            if parsed:a['exam_date']=field(parsed,page,disclosure[0],printed)
        for line in lines:
            if cover_matches_name(line,doc) and (a.get('agency_id') or canonical(line)==canonical(doc['institution_name'])):
                a['institution_name']=field(line,page,line,line);break
        if 'institution_name' not in a and a.get('agency_id'):
            for i,line in enumerate(lines):
                if re.search(r'^(?:Charter|Certificate|RSSD|Bank ID)',line,re.I) and i>0:
                    candidate=lines[i-1]
                    if re.search(r'\b(bank|association|company|savings|trust|bancorp)\b',candidate,re.I) and not re.search(r'^(performance|community reinvestment)',candidate,re.I):
                        a['institution_name']=field(candidate,page,candidate,candidate)
                        break
        break
    for page in pages[:12]:
        s=collapse(page['text'])
        for column,prefix in RAT_FIELDS.items():
            if column in a:continue
            m=re.search(prefix+RATING+r'\b',s,re.I)
            if m:a[column]=field(m[1].title().replace('To','to'),page,m[0],m[1])
        if 'exam_type' not in a:
            m=re.search(r'\b(Intermediate Small|Large|Small) (?:Bank|Institution)(?: CRA)? Examination Procedures\b',s,re.I)
            if m:
                a['exam_type']=field(m[1].lower(),page,m[0],m[0])
                a['exam_type_verbatim']=field(m[0],page,m[0],m[0])
        if 'cd_test_optional_elected' not in a:
            m=re.search(r'\b(?:The )?Optional (?:Community Development(?: \(CD\))?|CD) Test is rated\s*:\s*'+RATING,s,re.I)
            if m:
                # The schema stores the boolean as an integer. No numeric
                # literal exists, so do not infer a reported value here.
                pass
        if not tables['table_b_products_reviewed']:
            m=re.search(r'(?:major product lines (?:are|consist of)|primary products to be)\s+([^.;]{8,140})[.;]',s,re.I)
            if m:
                for term,code in PRODUCTS.items():
                    match=re.search(r'\b'+term+r'(?: loans?)?\b',m[1],re.I)
                    if match:
                        tables['table_b_products_reviewed'].append(dict(ids=dict(pe_id=pe,product_id=f'{pe}:{code}'),
                             fields={'product':field(code,page,m[0],match[0])}))
    return {'sha256':bundle['sha256'],'tables':tables}

def start(root, manifest, split, mode, reviewed=None):
    reviewed=reviewed or {}
    root.mkdir(parents=True,exist_ok=True)
    for k in ('pages','proposals'):(root/k).mkdir(exist_ok=True)
    dbpath=root/'draft_research.sqlite'
    with sqlite3.connect(dbpath) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='table_a_exam_level'").fetchone():
            db.executescript((ROOT/'schemas/research_schema.sql').read_text())
        documents=manifest['documents'];selected=split['development'] if mode=='development' else split['development']+split['calibration']+split['holdout']
        status={}
        report=root/'draft_status.json'
        if report.exists():status=json.loads(report.read_text())['documents']
        for doc in documents:
            key=doc['pe_id']
            if key not in selected:continue
            t=time.monotonic()
            try:
                # Rich layout extraction is an initial four-document diagnostic.
                bundle=pages_for(doc,key in split['development'])
                raw=proposal(doc,bundle)
                write_json(root/'pages'/f'{key}.json',bundle)
                write_json(root/'proposals'/f'{key}.json',raw)
                staged=json.loads(json.dumps(raw));review_count=0
                indexed={p['page']:p for p in bundle['pages']}
                for rows in staged['tables'].values():
                    for row in rows:
                        for k,x in list(row['fields'].items()):
                            if indexed[x['page']]['status']=='ocr_review_required':
                                match=reviewed.get(key,{}).get(k,{})
                                approved=(x['page']==match.get('page') and x['value']==match.get('value')
                                          and bundle['sha256']==match.get('sha256')
                                          and 'pe_id' in row['ids'] and row['ids']['pe_id']==key)
                                if approved:
                                    x['image_verified']=True
                                else:
                                    del row['fields'][k];review_count+=1
                # Keep unverified OCR fields out of the draft database.
                detail=save(db,key,bundle,staged)
                status[key]={'status':'draft_partial','ocr_fields_for_review':review_count,
                             'native_text_pages':sum(x['status']=='text' for x in bundle['pages']),
                             'ocr_layer_pages':sum(x['status']=='ocr_review_required' and bool(x['text'].strip()) for x in bundle['pages']),
                             'no_text_pages':[x['page'] for x in bundle['pages'] if not x['text'].strip()],
                             'pages':len(bundle['pages']),'seconds':time.monotonic()-t,**detail}
            except Exception as e:
                status[key]={'status':'failed','reason':f'{type(e).__name__}: {e}'}
            print(doc['agency'],doc['agency_id'],status[key],flush=True)
            write_json(report,{'stage':'partial draft: no full-field extraction or independent score','documents':status})
        return status

def main():
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['development','all']);p.add_argument('out',type=Path)
    p.add_argument('--split',type=Path,required=True)
    p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--reviewed',type=Path)
    a=p.parse_args()
    manifest=json.loads(a.manifest.read_text())
    status=start(a.out,manifest,json.loads(a.split.read_text()),a.mode,
                 json.loads(a.reviewed.read_text()) if a.reviewed else None)
    if any(r['status']=='failed' for r in status.values()):raise SystemExit(1)
if __name__=='__main__':main()
