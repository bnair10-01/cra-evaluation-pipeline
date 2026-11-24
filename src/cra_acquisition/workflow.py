"""Build a deterministic CRA pilot or a custom acquisition run."""
import argparse
from collections import defaultdict
from datetime import date
from hashlib import sha256
import json
from contextlib import closing
from pathlib import Path
import random

from . import __main__ as acq
from .collect import ranked
from .pilot import draw, QUOTAS, TYPES

AGENCIES={'1':'OCC','2':'FRB','3':'FDIC'}
METHODS={'1':'large','2':'small','7':'intermediate small'}
RATINGS={'1':'Outstanding','2':'Satisfactory','3':'Needs to Improve','4':'Substantial Noncompliance'}

def identity(row):
    cert=str(row['agency_id'])
    return row['agency'],str(int(cert)) if cert.isdecimal() else cert,row['exam_date']

def read_frame(path):
    groups=defaultdict(list); invalid=[]; excluded=0
    raw=path.read_bytes(); checksum=sha256(raw).hexdigest()
    for line,text in enumerate(raw.decode('utf-8-sig',errors='replace').splitlines(),1):
        f=text.split('\t')
        if len(f)<9:
            invalid.append(line);continue
        if f[1] not in AGENCIES:
            excluded+=1;continue
        try:
            if not f[0].isdigit() or len(f[2])!=8 or not f[3].strip():raise ValueError()
            d=date.fromisoformat(f'{f[2][:4]}-{f[2][4:6]}-{f[2][6:]}').isoformat()
        except ValueError:
            invalid.append(line);continue
        row=dict(agency=AGENCIES[f[1]],agency_id=f[0],exam_date=d,
                 institution_name=f[3],city=f[4],state=f[5],
                 exam_type=METHODS.get(f[7]),rating=RATINGS.get(f[8]),
                 date_basis='FFIEC release-date proxy' if f[1]=='3' else 'FFIEC reported examination date',
                 source_line=line,source_sha256=checksum)
        key=identity(row)
        row['pe_id']='FRAME_'+acq.digest(json.dumps(key).encode())[:24]
        groups[key].append((tuple(f[:9]),row))
    conflicts=[]; rows=[]; duplicates=0
    for key,entries in sorted(groups.items()):
        if len({f for f,_ in entries})!=1:
            conflicts.append(dict(key=key,lines=[r['source_line'] for _,r in entries]))
            continue
        rows.append(entries[0][1]);duplicates+=len(entries)-1
    return rows,dict(sha256=checksum,input=str(path),rows=len(rows),other_agencies=excluded,
                     invalid_lines=invalid,conflicts=conflicts,duplicates=duplicates)

def custom_draw(frame, count, years, agencies, seed, exclude=(), minimum=0):
    if count<1 or years[0]>years[1] or minimum<0:raise ValueError('Invalid count, years, or type minimum')
    rng=random.Random(seed); chosen=[]; reserves=[]
    for i,a in enumerate(agencies):
        n=count//len(agencies)+(i<count%len(agencies))
        pool=sorted((r for r in frame if r['agency']==a and r['pe_id'] not in exclude
                     and years[0]<=int(r['exam_date'][:4])<=years[1]),key=lambda x:x['pe_id'])
        if len(pool)<n:raise ValueError(f'{a}: requested {n}, available {len(pool)}')
        if 3*minimum>n:raise ValueError(f'{a}: type minima exceed target {n}')
        rng.shuffle(pool); subset=[]
        for t in TYPES:
            picks=[r for r in pool if r['exam_type']==t][:minimum]
            if len(picks)<minimum:raise ValueError(f'{a}: not enough {t} evaluations')
            subset+=picks
        used={r['pe_id'] for r in subset}
        subset += [r for r in pool if r['pe_id'] not in used][:n-len(subset)]
        chosen+=subset;used={r['pe_id'] for r in subset};reserves.extend(r for r in pool if r['pe_id'] not in used)
    return chosen,reserves

def requested(frame, specs, development_config=None, acquisition_db=None):
    development_config=development_config or acq.ROOT/'config/development_sample.json'
    acquisition_db=acquisition_db or acq.ROOT/'data/acquisition.sqlite'
    result=[]; unresolved=[]
    for spec in specs:
        query={**spec}
        years=query.pop('years',None)
        pool=frame if not years else [r for r in frame if years[0]<=int(r['exam_date'][:4])<=years[1]]
        candidates=ranked(query,pool)
        exact=[x['record'] for x in candidates if x['name_score']==1]
        if spec.get('request_id') and development_config.is_file() and acquisition_db.is_file():
            saved=acq.manifest(development_config)
            if spec in saved:
                # Preserve previously acquired development selections by canonical key.
                import sqlite3
                with closing(sqlite3.connect(acquisition_db.as_uri()+'?mode=ro',uri=True)) as db:
                    hit=db.execute('SELECT i.agency,i.agency_id,i.exam_date FROM requests r JOIN inventory i ON i.pe_id=r.selected_pe_id WHERE r.request_id=? AND r.status=?',(spec['request_id'],'resolved')).fetchone()
                old=next((r for r in frame if hit and identity(r)==tuple(hit)),None)
                if old and old in exact:exact=[old]
        if spec.get('all_matches') and exact:
            result.extend(exact)
        elif len(exact)==1:
            result+=exact
        elif len(exact)>1 and acq.allow_first_match(spec) and (spec.get('exam_year') or spec.get('year') or spec.get('exam_date')):
            result.append({**exact[0],'selection_note':'First exact match in frozen inventory order; no location supplied'})
        else:
            unresolved.append(dict(request=spec,candidates=candidates))
    return list({r['pe_id']:r for r in result}.values()),unresolved

from .io import write_json

def make_run(args):
    frame,source=read_frame(args.ffiec)
    specs=json.loads(args.requests.read_text())['requests'] if args.requests else []
    if args.pilot:
        specs=acq.manifest(acq.ROOT/'config/development_sample.json')
    named,unresolved=requested(frame,specs)
    if args.pilot and (len(named)!=4 or unresolved):
        raise ValueError('The four development requests must resolve before drawing the pilot')
    excluded={r['pe_id'] for r in named}
    if args.pilot:
        selected,reserves=draw(frame,args.seed,excluded)
        scans=4
    elif args.count is not None:
        selected,reserves=custom_draw(frame,args.count,args.years,args.agencies,args.seed,excluded,args.minimum_per_type)
        scans=args.scans
    else:
        selected,reserves=[],[];scans=0
    if not specs and args.count is None and not args.pilot:raise ValueError('Specify --pilot, --count, or --requests')
    if not 0<=scans<=len(selected):raise ValueError('Scan target exceeds sample size')
    result=dict(source=source,seed=args.seed,pilot=args.pilot,named=named,unresolved=unresolved,
                initial_draw=selected,reserves=reserves,scan_target=scans,years=args.years,
                min_per_type=3 if args.pilot else args.minimum_per_type,
                official_quotas=QUOTAS if args.pilot else None)
    result['run_id']=acq.digest(json.dumps(result,sort_keys=True).encode())[:20]
    print(json.dumps({k:v for k,v in result.items() if k!='reserves'} | {'reserve_count':len(reserves)},indent=2))
    if args.output:
        if args.output.exists():raise ValueError('Run already exists; use the saved plan to resume')
        write_json(args.output,result)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ffiec',type=Path,default=acq.ROOT/'data/crarating.txt')
    p.add_argument('--pilot',action='store_true');p.add_argument('--requests',type=Path)
    p.add_argument('--count',type=int);p.add_argument('--years',type=int,nargs=2,default=[1997,date.today().year])
    p.add_argument('--agencies',nargs='+',choices=list(AGENCIES.values()),default=list(AGENCIES.values()))
    p.add_argument('--minimum-per-type',type=int,default=0);p.add_argument('--scans',type=int,default=0)
    p.add_argument('--seed',type=int,default=20261102);p.add_argument('--output',type=Path)
    args=p.parse_args()
    if len(set(args.agencies))!=len(args.agencies):p.error('Duplicate agencies')
    if args.pilot and (args.requests or args.count is not None):p.error('--pilot defines its own requests and count')
    try:make_run(args)
    except (OSError,ValueError,KeyError) as e:p.error(str(e))

if __name__=='__main__':main()
