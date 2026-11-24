"""MOCK rehearsal of the whole pipeline. NOT a model, NOT research output.

The mock reads the same numbered page text a real call would see and emits a few regex-derived facts,
so plumbing (page prep, windows, caching, quote checks, typed conversion, table reading, staging,
flags, rollback) can be exercised offline with zero spend. Output goes to data/rehearsal/ and can never
be accepted (the run id is prefixed MOCK and `accept` refuses it)."""
import argparse
import json
from pathlib import Path
import re

from .io import read_json
from .paths import ROOT
from .prepare import load_or_prepare

LINE=re.compile(r'^\[p(\d+)\.l(\d+)\] (.*)$')
DATE=re.compile(r'\b(January|February|March|April|May|June|July|August|September|October|November|December) \d{1,2}, \d{4}\b')

def _lines(content):
    for raw in content.split('\n'):
        m=LINE.match(raw)
        if m:yield int(m[1]),int(m[2]),m[3]

class MockProvider:
    model='mock-model'
    def __init__(self,corrupt=None):
        self.corrupt=corrupt;self.calls=0
    def call(self,system,content,schema,max_tokens,ledger,raw_dir,effort='low',label='task',extra=None):
        self.calls+=1
        if 'd_layout' in system or 'Target: locate distribution tables' in system:
            parsed=dict(tables=self._layout(content))
        else:
            parsed=dict(facts=self._facts(system,content))
        if self.corrupt:parsed=self.corrupt(parsed,system)
        return dict(parsed=parsed,cost=0.0,usage=dict(input_tokens=0,output_tokens=0),request_id='mock',raw_path='',task_key='mock',seconds=0.0,price_version='mock')
    def _facts(self,system,content):
        facts=[];rows=list(_lines(content))
        def add(rec,field,value,page,quote,printed=''):
            facts.append(dict(record=rec,field=field,value=value,page=page,quote=quote,printed=printed))
        if 'Target: Table A' in system:
            for p,l,t in rows:
                m=re.search(r'(?:Certificate|Charter) Number:?\s*(\d+)',t)
                if m and not any(f['field']=='agency_id' for f in facts):add('A','agency_id',m[1],p,t.strip(),m[1])
                d=DATE.search(t)
                if d and p==1 and not any(f['field']=='exam_date' for f in facts):
                    from .research import parse_date
                    add('A','exam_date',parse_date(d[0]).isoformat(),p,t.strip(),d[0])
                m=re.search(r'rated (Outstanding|Satisfactory|Needs to Improve|Substantial Noncompliance)',t)
                if m and not any(f['field']=='rating_overall' for f in facts):add('A','rating_overall',m[1],p,t.strip(),m[1])
                if re.search(r'small bank|intermediate small|large bank',t,re.I) and not any(f['field']=='exam_type_verbatim' for f in facts):
                    add('A','exam_type_verbatim',t.strip(),p,t.strip())
        elif 'Target: Table E' in system:
            n=0
            for p,l,t in rows:
                m=re.search(r'(reflects? (?:a )?(?:reasonable|poor|excellent|good|adequate|very poor)[^.]{0,40}distribution)',t,re.I)
                if m:
                    n+=1;add(f'E{n}','label_verbatim',m[1],p,t.strip());add(f'E{n}','level','criterion',p,t.strip())
        elif 'Target: Table C' in system:
            for p,l,t in rows:
                m=re.match(r'^([A-Z][\w\- ]+ (?:Non-MSA|MSA) Assessment Area)$',t.strip())
                if m:add(m[1],'aa_name',m[1],p,t.strip())
        return facts
    def _layout(self,content):
        out=[];run=[]
        def flush():
            if len(run)>=3:
                p=run[0][0];n=len(re.findall(r'\d[\d,.]*%?',run[0][2]))
                out.append(dict(kind='category_rows',page=p,first_line=run[0][1],last_line=run[-1][1],table_index=0,first_row=0,last_row=0,table_label='',title='',aa_ref='',product_ref='',
                                dimension='borrower income',years='',demographic_base='',source_note='',
                                columns=[dict(meaning='bank_count_pct' if i==0 else 'ignore',category='',header='') for i in range(n)]))
        for p,l,t in _lines(content):
            if re.match(r'^(Low|Moderate|Middle|Upper)\b.*\d',t.strip()) and len(re.findall(r'\d',t))>=2:
                if run and (run[-1][0]!=p or l!=run[-1][1]+1):flush();run.clear()
                run.append((p,l,t))
            else:flush();run.clear()
        flush();return out

def rehearse(manifest,ids,out_dir,root=ROOT):
    from . import runstate,pipeline,tasks as T
    from .provider import Budget
    out_dir=Path(out_dir);out_dir.mkdir(parents=True,exist_ok=True)
    db=runstate.init_staging(out_dir/'staging.sqlite',root);ledger=Budget(out_dir/'ledger.sqlite',25)
    cols=T.research_columns(root);run_id='MOCK-'+manifest['run_id'][:8]
    dirs={k:out_dir/k for k in ('cache','raw','proposals')}
    for d in dirs.values():d.mkdir(exist_ok=True)
    report=[]
    for rec in manifest['documents']:
        if rec['pe_id'] not in ids:continue
        bundle=load_or_prepare(root,rec)
        r=pipeline.run_document(rec,bundle,MockProvider(),ledger,dirs,cols,db,run_id)
        report.append(dict(pe_id=rec['pe_id'],status=r['status'],rows=r['detail'].get('rows') if isinstance(r['detail'],dict) else None,
                           flags=len(r['flags']),calls=r['stats']['calls']))
    db.close();return dict(run_id=run_id,mock=True,documents=report)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--final',type=Path,default=ROOT/__import__('cra_acquisition.paths',fromlist=['x']).project_config()['manifest'])
    p.add_argument('--split',type=Path,default=ROOT/'docs/extraction_handoff/holdout_split.json')
    p.add_argument('--output',type=Path,default=ROOT/'data/rehearsal')
    a=p.parse_args()
    ids=set(read_json(a.split)['development'])
    print(json.dumps(rehearse(read_json(a.final),ids,a.output),indent=1))
if __name__=='__main__':main()
