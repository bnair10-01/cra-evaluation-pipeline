"""Resolve and acquire saved CRA selections, with resumable reserve decisions."""
import argparse
import datetime as dt
import json
from pathlib import Path
import re
import tempfile
from urllib.error import HTTPError
from urllib.parse import urlencode, urljoin

from . import __main__ as acq
from .pilot import ERAS
from .workflow import identity, write_json

FED='https://www.federalreserve.gov/apps/CRAPubWeb/CRA/BankRatingResult'

def federal_rows(body, url=FED):
    parser=acq.Rows();parser.feed(body.decode(errors='replace'))
    rows=[]
    for cells,links in parser.rows:
        if len(cells)<5:continue
        pdf=next((urljoin(url,x) for x in links if 'downloadpdf/' in x.lower()),None)
        identifier=re.search(r'\s-\s(\d+)',cells[0])
        exam=re.search(r'[A-Za-z]{3,9} \d{1,2}, \d{4}',cells[2])
        if not identifier or not exam:continue
        exam_date=dt.datetime.strptime(exam[0],'%b %d, %Y').date().isoformat()
        rows.append(dict(agency='FRB',agency_id=identifier[1],exam_date=exam_date,pdf_url=pdf,rating=cells[1]))
    return rows

def month_links(body,url):
    return sorted({urljoin(url,x) for x in re.findall(r'''href=["']([^"']+)''',body.decode(errors='replace'),re.I)
                   if re.search(r'cra-performance-evaluations-[a-z]+-\d{4}\.html$',x,re.I)})

class Resolver:
    def __init__(self,root,config,client,imports=None):
        self.root=root;self.config=config;self.client=client;self.imports=imports or {}
        self.cache={}
    def get(self,url,data=None):
        key=(url,data)
        if key not in self.cache:
            body,final,status,_=self.client.fetch(url,data)
            snap=self.client.snapshot(url,body,dict(kind='official_listing',final_url=final,status=status,
                                                     payload=data.decode() if data else None))
            self.cache[key]=body,final,snap
        return self.cache[key]
    def find(self,record):
        agency,cert,exam=identity(record)
        if agency=='FRB':
            imported=self.imports.get(record['pe_id'])
            if imported:
                body=Path(imported['listing']).read_bytes()
                snap=self.client.snapshot(FED,body,dict(kind='browser_saved_listing'))
                return self.pick(record,[(federal_rows(body),FED,snap)],imported.get('pdf'))
            form=urlencode(dict(SearchClick='T',NameID=cert,ExamYears=exam[:4],btnSearch='Search')).encode()
            body,url,snap=self.get(FED,form)
            return self.pick(record,[(federal_rows(body,url),url,snap)])
        if agency=='FDIC':
            cfg=self.config['agencies'][agency]
            body,url,snap=self.get(cfg['search_endpoint'],json.dumps({'cert':cert}).encode())
            rows=acq.fdic_rows(body,url,cfg['pdf_base'])
            for row in rows:
                row['exam_date']=row['release_date'] # matched to the frozen FFIEC proxy below
            return self.pick(record,[(rows,url,snap)])
        cfg=self.config['agencies']['OCC']
        for year in range(int(exam[:4]),min(int(exam[:4])+2,dt.date.today().year)+1):
            index=cfg['year_listing_template'].format(year=year)
            try:body,url,_=self.get(index)
            except HTTPError as e:
                if e.code==404:continue
                raise
            links=month_links(body,url)
            if not links:raise ValueError('OCC year page contains no recognized monthly listings')
            sources=[]
            for link in links:
                body,url,snap=self.get(link)
                sources.append((acq.occ_rows(body,url),url,snap))
            result=self.pick(record,sources)
            if result:return result
        return None
    def pick(self,record,sources,local=None):
        hits={}
        for rows,url,snap in sources:
            for row in rows:
                if identity(row)==identity(record) and row.get('pdf_url'):
                    if row.get('rating') and record.get('rating') and row['rating']!=record['rating']:
                        raise ValueError('Official listing and FFIEC ratings disagree')
                    hits[row['pdf_url']]=dict(url=row['pdf_url'],listing=url,snapshot=snap,imported_pdf=local)
        if len(hits)>1:raise ValueError('Multiple distinct official PDF links for exact examination')
        return next(iter(hits.values()),None)

def validate_and_classify(path):
    import pdfplumber
    text_count=image_count=unknown=0
    with pdfplumber.open(path) as doc:
        if not doc.pages:raise ValueError('PDF contains no pages')
        for page in doc.pages:
            w=page.width;h=page.height
            large=any(abs(i['x1']-i['x0'])*abs(i['bottom']-i['top'])>=0.65*w*h for i in page.images)
            n=sum(ch.isalnum() for ch in (page.extract_text() or ''))
            if large:image_count+=1
            elif n>=20:text_count+=1
            elif n or page.images:unknown+=1
        status=('mixed' if image_count and text_count else 'likely_scanned' if image_count
                else 'uncertain' if unknown or not text_count else 'text_based')
        if unknown and status!='mixed':status='uncertain'
        return dict(scan_status=status,pages=len(doc.pages),image_pages=image_count,text_pages=text_count,
                    uncertain_pages=unknown)

def acquire(root,record,resolver):
    cache=root/'data/pilot_cache';cache.mkdir(parents=True,exist_ok=True)
    basename=acq.filename(record)
    path=cache/basename
    import os
    import sqlite3
    existing_db=root/'data/acquisition.sqlite'
    if existing_db.exists():
        agency,cert,exam=identity(record)
        with sqlite3.connect(f"{existing_db.as_uri()}?mode=ro",uri=True) as db:
            db.row_factory=sqlite3.Row
            old=db.execute("SELECT * FROM inventory WHERE agency=? AND agency_id=? AND exam_date=? AND download_status='downloaded'",(agency,cert,exam)).fetchall()
        if len(old)==1:
            row=old[0];prior=root/row['local_path']
            if prior.is_file() and not prior.stat().st_mode&0o222 and acq.digest(prior.read_bytes())==row['sha256']:
                result=dict(status='verified',sha256=row['sha256'],bytes=prior.stat().st_size,path=row['local_path'],
                            url=row['pdf_url'],listing=row['source_url'],snapshot=row['snapshot_path'],retrieval='verified_existing')
                return result|validate_and_classify(prior)
    official=resolver.find(record)
    if not official:return dict(status='unavailable',reason='No PDF link for exact examination')
    url=official['url'];resolver.client.check_url(url)
    imported=official.pop('imported_pdf')
    if imported:
        body=Path(imported).read_bytes();final=url
    else:
        body,final,_,_=resolver.client.fetch(url)
    if not body.startswith(b'%PDF-') or b'%%EOF' not in body[-4096:]:raise ValueError('Invalid or incomplete PDF')
    sha=acq.digest(body)
    if path.exists() and acq.digest(path.read_bytes())!=sha:raise ValueError('Existing cached bytes differ')
    fd,tmpname=tempfile.mkstemp(dir=cache,suffix='.part')
    try:
        with os.fdopen(fd,'wb') as tmp:
            tmp.write(body);tmp.flush();os.fsync(tmp.fileno())
        scan=validate_and_classify(Path(tmpname))
        if not path.exists():
            os.chmod(tmpname,0o444)
            os.replace(tmpname,path)   # atomic move: the published file never shares an inode with the temp file
    finally:
        if os.path.exists(tmpname):
            try:os.chmod(tmpname,0o666);os.unlink(tmpname)
            except OSError:pass
    return dict(status='verified',sha256=sha,bytes=len(body),path=str(path.relative_to(root)),final_url=final,
                retrieval='browser_import' if imported else 'script',**official,**scan)

def slot_group(r,plan):
    year=int(r['exam_date'][:4])
    era=next((x for x in ERAS if x[0]<=year<=x[1]),None) if plan['pilot'] else tuple(plan['years'])
    return r['agency'],era,r['exam_type']

def execute(root,plan,progress,resolver,confirmed,limit=0):
    slots=progress.setdefault('slots',list(plan['initial_draw']))
    results=progress.setdefault('results',{})
    history=progress.setdefault('replacements',[])
    progress['run_id']=plan['run_id']
    state=root/'reports'/f"progress_{plan['run_id']}.json"
    calls=0
    frozen=(root/'reports'/f"final_{plan['run_id']}.json").exists()
    for key,val in confirmed.items():
        entry=results.get(key)
        if (not entry or entry.get('status')!='verified' or val.get('sha256')!=entry['sha256']
                or not val.get('review_note')):
            raise ValueError(f'Scan confirmation requires matching verified file and review note: {key}')
        entry.update(scan_status='scanned',scan_confirmation=val)
    official_names={r['pe_id'] for r in plan['named']}
    def check(row):
        nonlocal calls
        key=row['pe_id']; prior=results.get(key)
        if prior and prior['status']=='verified':
            path=root/prior['path']
            if path.is_file() and not path.stat().st_mode&0o222 and acq.digest(path.read_bytes())==prior['sha256']:
                return prior
            results[key]=dict(status='invalid_file',reason='Previously verified file missing, writable, or changed')
            write_json(state,progress)
            return results[key]
        if prior and prior['status'] not in ('retryable','access_denied'):return prior
        if limit and calls>=limit:return dict(status='pending_limit')
        calls+=1
        try:
            out=acquire(root,row,resolver)
            if out['status']=='verified' and any(k!=key and v.get('sha256')==out['sha256'] for k,v in results.items() if v['status']=='verified'):
                out=dict(status='invalid_file',reason='Duplicate PDF bytes',sha256=out['sha256'])
        except HTTPError as e:
            out=dict(status='access_denied' if e.code in (401,403) else 'unavailable' if e.code in (404,410) else 'retryable',reason=str(e))
        except OSError as e:
            out=dict(status='retryable',reason=str(e))
        except Exception as e:
            out=dict(status='invalid_file',reason=f'{type(e).__name__}: {e}')
        results[key]=out;write_json(state,progress)
        print(key,out['status'],out.get('reason',''),flush=True)
        return out
    def replace_at(i,new,reason):
        old=slots[i];slots[i]=new
        history.append(dict(old=old['pe_id'],new=new['pe_id'],reason=reason))
        write_json(state,progress)
    old_slots={x['old'] for x in history}
    for row in plan['named']:check(row)
    for i in range(len(slots)):
        while True:
            row=slots[i];out=check(row)
            if frozen or out['status'] in ('verified','pending_limit','access_denied','retryable'):break
            used=official_names|old_slots|{r['pe_id'] for r in slots}
            repl=next((r for r in plan['reserves'] if r['pe_id'] not in used and slot_group(r,plan)==slot_group(row,plan)),None)
            if not repl:break
            old_slots.add(row['pe_id']);replace_at(i,repl,out['status'])
    # Only visually confirmed, checksum-bound scans may replace a verified non-scan.
    for row in plan['reserves'] if not frozen and all(results.get(x['pe_id'],{}).get('status')=='verified' for x in slots) else ():
        if sum(results.get(x['pe_id'],{}).get('scan_status')=='scanned' for x in slots)>=plan['scan_target']:break
        if row['pe_id'] in old_slots or row['pe_id'] in {x['pe_id'] for x in slots}:continue
        i=next((i for i,x in enumerate(slots) if slot_group(x,plan)==slot_group(row,plan)
                and results.get(x['pe_id'],{}).get('status')=='verified'
                and results[x['pe_id']].get('scan_status')=='text_based'),None)
        if i is None:continue
        # Screen in bounded batches, keeping reserves out of the final sample.
        if not limit:break
        if calls>=limit:break
        out=check(row)
        if out.get('scan_status')=='scanned':
            old_slots.add(slots[i]['pe_id']);replace_at(i,row,'scan_quota')
    final=plan['named']+slots
    verified=[r for r in final if results.get(r['pe_id'],{}).get('status')=='verified']
    scans=sum(results.get(r['pe_id'],{}).get('scan_status')=='scanned' for r in slots)
    complete=len(verified)==len(final) and scans>=plan['scan_target'] and not plan['unresolved']
    progress.update(verified_count=len(verified),target_count=len(final),confirmed_scans=scans,complete=complete)
    write_json(state,progress)
    if complete:
        output=root/'reports'/f"final_{plan['run_id']}.json"
        if not output.exists():write_json(output,dict(run_id=plan['run_id'],development_ids=[r['pe_id'] for r in plan['named']],documents=[{**r,**results[r['pe_id']]} for r in final]))
    print(f"{len(verified)}/{len(final)} verified, scans {scans}/{plan['scan_target']}, complete={complete}")

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('plan',type=Path);p.add_argument('--imports',type=Path);p.add_argument('--confirmed-scans',type=Path)
    p.add_argument('--limit',type=int,required=True,help='Maximum new retrieval attempts per invocation')
    a=p.parse_args()
    if a.limit<1:p.error('--limit must be positive')
    root=acq.ROOT;plan=json.loads(a.plan.read_text());state=root/'reports'/f"progress_{plan['run_id']}.json"
    config=json.loads((root/'config/sources.json').read_text());client=acq.Client(root,config)
    from filelock import FileLock
    with FileLock(str(state.with_suffix('.lock')), timeout=0):
        execute(root,plan,json.loads(state.read_text()) if state.exists() else {},
                Resolver(root,config,client,json.loads(a.imports.read_text()) if a.imports else None),
                json.loads(a.confirmed_scans.read_text()) if a.confirmed_scans else {},a.limit)

if __name__=='__main__':main()
