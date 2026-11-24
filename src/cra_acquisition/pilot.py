"""Deterministic pilot selection from a frozen official-metadata inventory."""
import argparse
import hashlib
import json
from pathlib import Path
import random
from .__main__ import ROOT, now

ERAS=[(1997,2004),(2005,2009),(2010,2014),(2015,2019),(2020,2026)]
QUOTAS={'OCC':[3,3,2,3,2],'FDIC':[3,2,3,2,3],'FRB':[2,3,3,3,3]}
TYPES=('small','intermediate small','large')

def draw(records,seed=20261102,exclude=(),attempts=10000):
    ids=[r['pe_id'] for r in records]
    if len(ids)!=len(set(ids)):raise ValueError('Duplicate evaluation IDs in sampling frame')
    pools={}
    for agency,quotas in QUOTAS.items():
        for i,(start,end) in enumerate(ERAS):
            pool=sorted([r for r in records if r['pe_id'] not in exclude and r.get('agency')==agency and r.get('exam_type') in TYPES and r.get('exam_date') and start<=int(r['exam_date'][:4])<=end],key=lambda r:r['pe_id'])
            if len(pool)<quotas[i]:raise ValueError(f'Insufficient frame: {agency} {start}-{end}: {len(pool)} available, {quotas[i]} required')
            pools[agency,i]=pool
    rng=random.Random(seed)
    for _ in range(attempts):
        selected=[];reserves=[]
        for (agency,i),pool in pools.items():
            shuffled=pool.copy();rng.shuffle(shuffled);q=QUOTAS[agency][i]
            selected.extend(shuffled[:q]);reserves.extend(shuffled[q:])
        if all(sum(r['agency']==a and r['exam_type']==t for r in selected)>=3 for a in QUOTAS for t in TYPES):
            return selected,reserves
    raise ValueError('No selection satisfies type minima; expand the frame or explicitly revise quotas')

def replace(selected,reserves,failed_id,reason):
    old=next(r for r in selected if r['pe_id']==failed_id)
    year=int(old['exam_date'][:4]);era=next(e for e in ERAS if e[0]<=year<=e[1])
    used={r['pe_id'] for r in selected}
    for r in reserves:
        if r['pe_id'] not in used and r['agency']==old['agency'] and r['exam_type']==old['exam_type'] and era[0]<=int(r['exam_date'][:4])<=era[1] and (reason!='scan_quota' or r.get('scan_status')=='scanned'):
            return r
    raise ValueError('No matching reserve; requirements must not be silently relaxed')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--frame',type=Path,required=True);p.add_argument('--seed',type=int,default=20261102);p.add_argument('--exclude',type=Path);a=p.parse_args()
    raw=a.frame.read_bytes();records=json.loads(raw)
    exclude=json.loads(a.exclude.read_text()) if a.exclude else []
    selected,reserves=draw(records,a.seed,exclude)
    run_id=hashlib.sha256(raw+str(a.seed).encode()+json.dumps(sorted(exclude)).encode()).hexdigest()[:24]
    out=ROOT/'reports'/('pilot_'+run_id+'.json')
    result={'run_id':run_id,'created_at':now(),'seed':a.seed,'frame_sha256':hashlib.sha256(raw).hexdigest(),'excluded_ids':exclude,'selected':selected,'reserves':reserves,'scan_requirement':4,'scan_requirement_met':sum(r.get('scan_status')=='scanned' for r in selected)>=4,'status':'drawn_not_verified','replacements':[]}
    if not out.exists():out.write_text(json.dumps(result,indent=2)+'\n')
    manifest={'requests':[{'request_id':r['pe_id'],'agency':r['agency'],'institution_name':r['institution_name'],'exam_date':r['exam_date'],**({'agency_id':r['agency_id']} if r.get('agency_id') else {})} for r in selected]}
    (ROOT/'config'/('pilot_'+run_id+'.json')).write_text(json.dumps(manifest,indent=2)+'\n')
    print(out)

if __name__=='__main__':main()
