"""Offline cost estimate from the prepared page bundles. No network, no key, no spend."""
import argparse
from pathlib import Path

from .io import read_json,write_json
from .paths import ROOT
from .prepare import load_or_prepare
from .provider import estimate_text_tokens,load_pricing,DEFAULT_MODEL
from . import tasks as T

def estimate(manifest,ids,root=ROOT,effort_output_ratio=1.0,model=DEFAULT_MODEL):
    version,price=load_pricing(model=model);cols=T.research_columns(root);p=T.prompts()
    docs=[];total_in=total_out=0
    for rec in manifest['documents']:
        if rec['pe_id'] not in ids:continue
        bundle=load_or_prepare(root,rec);tin=tout=calls=0
        for task in T.plan(bundle):
            text=T.system_prompt(task['target'],cols,p)+T.user_content(bundle,task['pages'],task['target'])
            tin+=estimate_text_tokens(text);calls+=1
            tout+=int(T.MAX_TOKENS[task['target']]*0.35*effort_output_ratio)  # typical use; reservation is the full max_tokens
        worst=sum(T.MAX_TOKENS[t['target']] for t in T.plan(bundle))
        cost=(tin*price['input']+tout*price['output'])/1e6;worst_cost=(tin*price['input']+worst*price['output'])/1e6
        docs.append(dict(pe_id=rec['pe_id'],agency=rec['agency'],pages=bundle['page_count'],calls=calls,input_tokens=tin,
                         expected_output_tokens=tout,expected_usd=round(cost,3),worst_case_usd=round(worst_cost,3)))
        total_in+=tin;total_out+=tout
    return dict(price_version=version,model=model,documents=sorted(docs,key=lambda d:-d['expected_usd']),
                total_expected_usd=round(sum(d['expected_usd'] for d in docs),2),
                total_worst_case_usd=round(sum(d['worst_case_usd'] for d in docs),2),
                note='Expected output assumes ~35% of each call\'s max_tokens (including thinking). Worst case reserves 100%. Input uses a conservative 2.5 bytes/token bound; live calls use count_tokens. Batch API would halve both.')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--final',type=Path,default=ROOT/__import__('cra_acquisition.paths',fromlist=['x']).project_config()['manifest'])
    p.add_argument('--split',type=Path,default=ROOT/'docs/extraction_handoff/holdout_split.json')
    p.add_argument('--group',choices=['development','calibration','holdout','all'],default='all');p.add_argument('--output',type=Path)
    a=p.parse_args();m=read_json(a.final);s=read_json(a.split)
    ids={r['pe_id'] for r in m['documents']} if a.group=='all' else set(s[a.group])
    result=estimate(m,ids)
    for d in result['documents'][:8]:print(f"{d['pe_id'][-8:]} {d['agency']:4} {d['pages']:4}pp calls={d['calls']:3} expected=${d['expected_usd']:.2f} worst=${d['worst_case_usd']:.2f}")
    print(f"documents={len(result['documents'])} expected=${result['total_expected_usd']} worst-case=${result['total_worst_case_usd']}")
    if a.output:write_json(a.output,result)
if __name__=='__main__':main()
