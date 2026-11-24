"""Requested collection when --requests is supplied; random selection otherwise."""
import argparse
from difflib import SequenceMatcher
import json
from pathlib import Path
from .__main__ import ROOT, normalized, location_matches, allow_first_match
from .pilot import draw

def ranked(request,records):
    year=str(request.get('exam_year') or request.get('year') or '')
    basis='release_date' if request.get('year_basis')=='release' else 'exam_date'
    ranked=[]
    for record in records:
        if not location_matches(record,request):continue
        if request.get('agency') and record.get('agency')!=request['agency']:continue
        if request.get('exam_date') and record.get('exam_date')!=request['exam_date']:continue
        if year and (record.get(basis) or '')[:4]!=year:continue
        if any(request.get(k) and str(request[k]).casefold()!=str(record.get(k) or '').casefold() for k in ('agency_id','state','city')):continue
        score=SequenceMatcher(None,normalized(request['institution_name']),normalized(record['institution_name'])).ratio()
        if score>=0.65:ranked.append({'name_score':score,'record':record})
    return sorted(ranked,key=lambda x:-x['name_score'])

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--frame',type=Path,required=True,help='Frozen official-metadata inventory JSON');p.add_argument('--requests',type=Path);p.add_argument('--additional-random',action='store_true');p.add_argument('--seed',type=int,default=20261102);a=p.parse_args()
    records=json.loads(a.frame.read_text());requested=[];excluded=set()
    if a.requests:
        for req in json.loads(a.requests.read_text())['requests']:
            candidates=ranked(req,records)
            exact=[x for x in candidates if x['name_score']==1]
            fallback=len(exact)>1 and allow_first_match(req)
            selected=exact[0]['record'] if len(exact)==1 or fallback else None
            requested.append({'request':req,'status':'resolved' if selected else 'needs_review','selected':selected,'selection_basis':'first_exact_match' if fallback else 'unique_exact_match' if selected else None,'candidates':candidates})
            # Exclude every plausible development candidate, including unresolved
            # ones, so pilot selection cannot accidentally reuse a development PE.
            excluded.update(x['record']['pe_id'] for x in candidates)
    random_records=[];reserves=[]
    if not a.requests or a.additional_random:
        random_records,reserves=draw(records,a.seed,excluded)
    result={'seed':a.seed,'requested':requested,'random_selected':random_records,'reserves':reserves,'target_scanned':4,'scan_requirement_met':sum(r.get('scan_status')=='scanned' for r in random_records)>=4,'status':'selection_only_retrieval_requires_verified_agency_adapter'}
    out=ROOT/'reports/collection_selection.json';out.write_text(json.dumps(result,indent=2)+'\n');print(out)

if __name__=='__main__':main()
