"""RSSD crosswalk from the FDIC BankFind institutions API (CERT, CHARTER, FED_RSSD, ACTIVE).

Federal Reserve evaluations already carry an RSSD as their agency id. OCC charters and FDIC
certificates are matched through one bounded, cached snapshot. Unmatched or conflicting rows
are recorded as such, never guessed. FFIEC NIC bulk files returned HTTP 403 to scripts; they can be
imported manually with --csv (columns: agency_id,agency,rssd_id)."""
import argparse
import csv
from contextlib import closing
import json
from pathlib import Path
import time
import urllib.parse
import urllib.request

from .io import atomic_write_bytes,read_json,sha256_bytes
from .paths import ROOT
from . import runstate

API='https://api.fdic.gov/banks/institutions'
FIELDS='CERT,NAME,FED_RSSD,CHARTER,ACTIVE,INACTIVE,CITY,STALP'
AGENT='CRAResearchAcquisition/0.2'

def fetch_snapshot(root,page_size=10000,fetch=None,sleep=2.0):
    """Download all institutions once (active and closed) and store the raw pages. `fetch` is injectable."""
    root=Path(root);snap=root/'data/source_snapshots/rssd_bankfind.json'
    if snap.is_file():return read_json(snap)
    def default_fetch(url):
        req=urllib.request.Request(url,headers={'User-Agent':AGENT,'Accept':'application/json'})
        with urllib.request.urlopen(req,timeout=60) as r:return json.loads(r.read())
    fetch=fetch or default_fetch
    rows=[];offset=0;total=None;pages=[]
    while True:
        q=urllib.parse.urlencode(dict(fields=FIELDS,limit=page_size,offset=offset,sort_by='CERT',sort_order='ASC'))
        data=fetch(f'{API}?{q}')
        batch=[d['data'] for d in data.get('data',[])]
        total=data.get('meta',{}).get('total',total)
        if not batch:break
        rows+=batch;pages.append(len(batch));offset+=len(batch)
        if total is not None and offset>=total:break
        time.sleep(sleep)
    if total is not None and len(rows)!=total:raise ValueError(f'Incomplete enumeration: got {len(rows)} of {total}')
    body=dict(source=API,fields=FIELDS,total=total,rows=rows,pages=pages)
    atomic_write_bytes(snap,json.dumps(body).encode())
    return body

def build(manifest,snapshot,extra=None):
    """Rows for the rssd_crosswalk table: one per final-manifest institution."""
    by_cert={str(r['CERT']):r for r in snapshot['rows'] if r.get('CERT') is not None}
    by_charter={}
    for r in snapshot['rows']:
        c=r.get('CHARTER')
        if c not in (None,'','0',0):by_charter.setdefault(str(c).lstrip('0'),[]).append(r)
    out=[];sha=sha256_bytes(json.dumps(snapshot['rows'],sort_keys=True).encode())
    for rec in manifest['documents']:
        agency,aid=rec['agency'],str(rec['agency_id'])
        base=dict(agency=agency,agency_id=aid,institution_name=rec['institution_name'],source='FDIC BankFind',source_sha256=sha)
        if agency=='FRB':
            out.append(dict(base,rssd_id=aid,fdic_cert=None,occ_charter=None,active=None,source='Federal Reserve evaluation id',status='matched'));continue
        if extra and (agency,aid) in extra:
            out.append(dict(base,rssd_id=extra[(agency,aid)],fdic_cert=None,occ_charter=None,active=None,source='manual import',status='matched'));continue
        hits=[by_cert[aid]] if agency=='FDIC' and aid in by_cert else by_charter.get(aid.lstrip('0'),[]) if agency=='OCC' else []
        hits=[h for h in hits if h.get('FED_RSSD') not in (None,'','0',0)]
        if not hits:out.append(dict(base,rssd_id=None,fdic_cert=None,occ_charter=None,active=None,status='unmatched'))
        elif len({str(h['FED_RSSD']) for h in hits})>1:out.append(dict(base,rssd_id=None,fdic_cert=None,occ_charter=None,active=None,status='conflict'))
        else:
            h=hits[0];out.append(dict(base,rssd_id=str(h['FED_RSSD']),fdic_cert=str(h['CERT']),occ_charter=str(h.get('CHARTER') or '') or None,
                                      active=h.get('ACTIVE'),status='matched'))
    return out

def store(db,rows):
    with db:
        for r in rows:
            db.execute('INSERT OR REPLACE INTO rssd_crosswalk VALUES (:agency,:agency_id,:rssd_id,:fdic_cert,:occ_charter,:institution_name,:active,:source,:source_sha256,:status)',r)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--final',type=Path,required=True);p.add_argument('--database',type=Path,required=True)
    p.add_argument('--csv',type=Path,help='manual NIC import: agency_id,agency,rssd_id');p.add_argument('--offline',action='store_true')
    a=p.parse_args()
    manifest=read_json(a.final);snap=ROOT/'data/source_snapshots/rssd_bankfind.json'
    if a.offline and not snap.is_file():p.error('No cached snapshot; run without --offline once')
    snapshot=fetch_snapshot(ROOT)
    extra={}
    if a.csv:
        with a.csv.open(newline='',encoding='utf-8') as f:
            for r in csv.DictReader(f):extra[(r['agency'].strip(),r['agency_id'].strip())]=r['rssd_id'].strip()
    rows=build(manifest,snapshot,extra)
    with closing(runstate.connect(a.database)) as db:
        runstate.migrate(db);store(db,rows)
    from collections import Counter
    print(json.dumps(Counter(r['status'] for r in rows)))
if __name__=='__main__':main()
