"""Acquisition only: never parse PDF contents."""
import argparse
import datetime as dt
import hashlib
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sqlite3
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser

from .paths import ROOT
AGENT = 'CRAResearchAcquisition/0.1'

from .io import now

def digest(data):
    return hashlib.sha256(data).hexdigest()

def date(value):
    if not value:
        return None
    for fmt in ('%m/%d/%Y', '%Y-%m-%d'):
        try:
            return dt.datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    return None

def normalized(value):
    return re.sub(r'[^a-z0-9]', '', value.lower().removeprefix('the '))

def location_matches(row, request):
    location=request.get('location')
    if not location:
        return True
    city,separator,state=location.rpartition(',')
    if not separator or not city.strip() or not re.fullmatch(r'[A-Za-z]{2}',state.strip()):
        raise ValueError('location must use City, ST format')
    return (city.strip().casefold()==(row.get('city') or '').strip().casefold()
            and state.strip().casefold()==(row.get('state') or '').strip().casefold())

def allow_first_match(request):
    return not any(request.get(k) for k in ('location','city','state'))

def matches(row, request):
    if row['agency'] != request['agency'] or not location_matches(row,request):
        return False
    if normalized(row['institution_name']) != normalized(request['institution_name']):
        return False
    for key in ('agency_id', 'city', 'state'):
        if request.get(key) and str(row.get(key) or '').casefold() != str(request[key]).casefold():
            return False
    if request.get('exam_date') and row.get('exam_date') != request['exam_date']:
        return False
    if request.get('exam_year') and (row.get('exam_date') or '')[:4] != str(request['exam_year']):
        return False
    return True

class Rows(HTMLParser):
    def __init__(self):
        super().__init__(); self.rows=[]; self.cells=None; self.text=None; self.links=[]; self.row_links=[]
    def handle_starttag(self, tag, attrs):
        if tag=='tr': self.cells=[]; self.row_links=[]
        if tag in ('td','th') and self.cells is not None: self.text=[]
        if tag=='a' and self.cells is not None:
            href=dict(attrs).get('href')
            if href: self.row_links.append(href)
    def handle_data(self, data):
        if self.text is not None: self.text.append(data)
    def handle_endtag(self, tag):
        if tag in ('td','th') and self.text is not None:
            self.cells.append(' '.join(''.join(self.text).split())); self.text=None
        if tag=='tr' and self.cells is not None:
            self.rows.append((self.cells,self.row_links)); self.cells=None

def occ_rows(body, url):
    parser=Rows(); parser.feed(body.decode('utf-8', errors='replace')); result=[]
    for cells, links in parser.rows:
        if len(cells)<7 or not cells[0].isdigit() or not date(cells[4]): continue
        pdf=next((urllib.parse.urljoin(url,x) for x in links if urllib.parse.urlparse(x).path.lower().endswith('.pdf')),None)
        result.append(dict(agency='OCC',agency_id=cells[0],institution_name=cells[1],city=cells[2],state=cells[3],exam_date=date(cells[4]),release_date=None,rating=cells[5],pdf_url=pdf,raw_metadata_json=json.dumps({'cells':cells,'links':links})))
    if not result: raise ValueError('No OCC evaluation rows parsed; layout may have changed')
    return result

def fdic_rows(body, url, pdf_base):
    data=json.loads(body)
    if data.get('status')!='success' or not isinstance(data.get('data'),list): raise ValueError('Unexpected FDIC response')
    if len(data['data'])>=500: raise ValueError('FDIC result cap reached; narrow the search')
    result=[]
    for x in data['data']:
        # The public API exposes publication date, not examination date.
        # Do not infer the examination date from the PDF filename.
        filename=x.get('SYS_EXTRN_FILE_ID')
        result.append(dict(agency='FDIC',agency_id=str(x['ORG_CERT_NUM']),institution_name=x['INST_FIN_LGL_NME'],city=x.get('LOCN_PHY_CTY_NME'),state=x.get('LOCN_ST_ABBV_NME'),exam_date=None,release_date=date(x.get('EXM_CRA_PUB_DTE')),rating=x.get('EXM_RTG_FULL_DESC'),pdf_url=urllib.parse.urljoin(pdf_base,filename) if filename else None,raw_metadata_json=json.dumps(x)))
    return result

def fdic_ffiec_dates(path):
    """Index FDIC records by certificate and FFIEC reported date."""
    content=path.read_bytes()
    index={}
    for number,line in enumerate(content.decode('utf-8-sig',errors='replace').splitlines(),1):
        fields=line.split('\t')
        if len(fields)<9 or fields[1].strip()!='3':
            continue
        cert,raw_date=fields[0].strip(),fields[2].strip()
        try:
            reported=dt.datetime.strptime(raw_date,'%Y%m%d').date().isoformat()
        except ValueError:
            continue
        if cert.isdigit():
            index.setdefault((str(int(cert)),reported),[]).append((number,fields[:9]))
    if not index:
        raise ValueError(f'No FDIC records in FFIEC file: {path}')
    return index,digest(content)

def use_fdic_ffiec_date(row,lookup):
    index,sha=lookup
    cert=row['agency_id']
    if not cert.isdigit():
        return
    hits=index.get((str(int(cert)),row['release_date']),[])
    if len(hits)!=1:
        return
    line,fields=hits[0]
    row['exam_date']=dt.datetime.strptime(fields[2].strip(),'%Y%m%d').date().isoformat()
    metadata=json.loads(row['raw_metadata_json'])
    metadata['ffiec_date_source']={
        'file_sha256':sha,'line':line,'reported_date':fields[2],
        'match_basis':'FDIC certificate and release date',
        'verified_against_pdf':False,
    }
    row['raw_metadata_json']=json.dumps(metadata)

class Client:
    def __init__(self, root, config):
        self.root=root; self.config=config; self.last={}; self.robots={}
    def check_url(self,url):
        u=urllib.parse.urlparse(url)
        if u.scheme!='https' or u.hostname not in self.config['allowed_hosts']:
            raise ValueError('Only configured official HTTPS hosts permitted: '+url)
    def snapshot(self,url,body,metadata):
        path=self.root/'data/source_snapshots'/ (digest(body)+'.bin')
        if not path.exists():
            from .io import atomic_write_bytes
            atomic_write_bytes(path,body)
        meta=path.with_suffix('.'+digest(json.dumps(metadata,sort_keys=True).encode())[:12]+'.json')
        if not meta.exists():
            from .io import atomic_write_text
            atomic_write_text(meta,json.dumps(dict(url=url,retrieved_at=now(),**metadata),indent=2)+'\n')
        return str(path.relative_to(self.root))
    def raw(self,url,data=None):
        self.check_url(url)
        client=self
        class Redirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                client.check_url(newurl)
                # Do not follow a redirect into an unreviewed path or host.
                client.policy(newurl); client.wait(newurl)
                return super().redirect_request(req,fp,code,msg,headers,newurl)
        self.wait(url)
        headers={'User-Agent': AGENT}
        if data is not None:
            path=urllib.parse.urlparse(url).path
            headers['Content-Type']=('application/x-www-form-urlencoded'
                                     if path.endswith('/CRA/BankRatingResult') else 'application/json')
        req=urllib.request.Request(url,data=data,headers=headers)
        with urllib.request.build_opener(Redirect()).open(req,timeout=45) as r:
            content=r.read(100*1024*1024+1)
            if len(content)>100*1024*1024: raise ValueError('Response exceeds 100 MB bound')
            return content,r.geturl(),r.status,dict(r.headers)
    def wait(self,url):
        host=urllib.parse.urlparse(url).hostname
        delay=max(2,float(self.config.get('request_interval_seconds',2)),self.robots.get(host,(None,0))[1])
        time.sleep(max(0,delay-(time.monotonic()-self.last.get(host,0))))
        self.last[host]=time.monotonic()
    def policy(self,url):
        self.check_url(url); u=urllib.parse.urlparse(url); host=u.hostname
        if host not in self.robots:
            # Seed to avoid recursion if robots redirects.
            self.robots[host]=(None,0)
            robots_url=f'https://{host}/robots.txt'
            try:
                body,final,status,headers=self.raw(robots_url)
                self.snapshot(robots_url,body,{'kind':'robots','status':status,'final_url':final})
                text=body.decode('utf-8',errors='replace')
                if '<html' in text.lower() or '<!doctype html' in text.lower():
                    if host not in self.config.get('robots_html_reviewed',[]): raise ValueError('robots returned HTML; needs review: '+host)
                    parser=None
                else:
                    parser=urllib.robotparser.RobotFileParser(); parser.parse(text.splitlines())
                delay=parser.crawl_delay(AGENT) or parser.crawl_delay('*') or 0 if parser else 0
                self.robots[host]=(parser,delay)
            except urllib.error.HTTPError as e:
                if e.code!=404:
                    self.robots.pop(host,None); raise
                self.robots[host]=(None,0)
            except Exception:
                self.robots.pop(host,None); raise
        parser,_=self.robots[host]
        if parser and not parser.can_fetch(AGENT,url): raise PermissionError('robots disallows '+url)
    def fetch(self,url,data=None):
        self.policy(url)
        for attempt in range(3):
            try: return self.raw(url,data)
            except urllib.error.HTTPError as e:
                if e.code not in (429,500,502,503,504) or attempt==2: raise
                value=e.headers.get('Retry-After')
                try: delay=float(value)
                except (TypeError,ValueError):
                    try:
                        from email.utils import parsedate_to_datetime
                        delay=max(0,(parsedate_to_datetime(value)-dt.datetime.now(dt.timezone.utc)).total_seconds())
                    except Exception: delay=2**(attempt+1)
                # Avoid long blocking retries: return the delay as an actionable error.
                if delay>60: raise RuntimeError(f'Retry deferred: server requires {delay:.0f}s') from e
                time.sleep(max(delay,2**(attempt+1)))
            except (urllib.error.URLError,TimeoutError):
                if attempt==2: raise
                time.sleep(2**(attempt+1))

def connect(root):
    c=sqlite3.connect(root/'data/acquisition.sqlite'); c.row_factory=sqlite3.Row
    c.executescript((root/'schemas/acquisition_schema.sql').read_text()); return c

def manifest(path):
    requests=json.loads(path.read_text())['requests']
    ids=[x['request_id'] for x in requests]
    if len(ids)!=len(set(ids)): raise ValueError('Duplicate request_id')
    for r in requests:
        if not r.get('institution_name') or r.get('agency') not in ('OCC','FDIC','FRB','OTS'): raise ValueError('Invalid request')
        if not (r.get('exam_year') or r.get('exam_date')): raise ValueError('A bounded examination year/date is required')
    return requests

def discover(root,c,client,requests,config,ffiec_file=None):
    lookup=None
    if any(r['agency']=='FDIC' for r in requests):
        lookup=fdic_ffiec_dates(ffiec_file or root/'data/crarating.txt')
    for r in requests:
        rid=r['request_id']; criteria=json.dumps(r,sort_keys=True)
        c.execute('INSERT INTO requests VALUES (?,?,?,NULL,NULL,?) ON CONFLICT(request_id) DO UPDATE SET criteria_json=excluded.criteria_json,status=excluded.status,selected_pe_id=NULL,error=NULL,updated_at=excluded.updated_at',(rid,criteria,'searching',now()))
        c.execute('DELETE FROM candidates WHERE request_id=?',(rid,)); c.commit()
        try:
            agency=config['agencies'][r['agency']]
            if r['agency']=='FDIC':
                query={'instName':r['institution_name']}
                for k,field in [('agency_id','cert'),('city','city'),('state','state')]:
                    if r.get(k): query[field]=str(r[k])
                inputs=[(agency['search_endpoint'],json.dumps(query).encode())]
            elif r['agency']=='OCC':
                urls=r.get('listing_urls')
                if not urls:
                    year=r.get('exam_year') or int(r['exam_date'][:4])
                    index=agency['year_listing_template'].format(year=year)
                    body,final,status,_=client.fetch(index)
                    client.snapshot(index,body,{'kind':'year_listing','status':status,'final_url':final})
                    urls=sorted(set(urllib.parse.urljoin(index,html.unescape(x)) for x in re.findall(r'href=[\"\']([^\"\']+)',body.decode(),re.I) if re.search(r'cra-performance-evaluations-[a-z]+-\d{4}\.html$',x)))
                    if not urls: raise ValueError('No monthly listings found; supply listing_urls')
                inputs=[(u,None) for u in urls]
            else: raise NotImplementedError('Agency discovery adapter not yet implemented')
            for url,payload in inputs:
                body,final,status,_=client.fetch(url,payload)
                snap=client.snapshot(url,body,{'kind':'search_results','payload':payload.decode() if payload else None,'status':status,'final_url':final})
                rows=occ_rows(body,url) if r['agency']=='OCC' else fdic_rows(body,url,agency['pdf_base'])
                for row in rows:
                    # Keep name-matching candidate histories, not unrelated listing records.
                    if normalized(row['institution_name'])!=normalized(r['institution_name']): continue
                    # Keep the existing FDIC ID stable when adding the FFIEC date.
                    key='|'.join(str(row.get(k) or '') for k in ('agency','agency_id','exam_date','release_date','pdf_url'))
                    if row['agency']=='FDIC':
                        use_fdic_ffiec_date(row,lookup)
                    row.update(pe_id='PE_'+digest(key.encode())[:24],source_url=url,snapshot_path=snap,retrieved_at=now())
                    old=c.execute('SELECT * FROM inventory WHERE pe_id=?',(row['pe_id'],)).fetchone()
                    check=('institution_name','rating','pdf_url') if row['agency']=='FDIC' else ('institution_name','exam_date','rating','pdf_url')
                    if old and any(old[k]!=row.get(k) for k in check): raise ValueError('Metadata changed; review source snapshot before updating')
                    if old and row['agency']=='FDIC':
                        if old['exam_date'] and old['exam_date']!=row['exam_date']:
                            raise ValueError('Previously matched FFIEC date no longer resolves; review source data')
                        c.execute('UPDATE inventory SET exam_date=?,raw_metadata_json=?,snapshot_path=?,retrieved_at=? WHERE pe_id=?',
                                  (row['exam_date'],row['raw_metadata_json'],snap,row['retrieved_at'],row['pe_id']))
                    if not old:
                        cols=list(row); c.execute(f'INSERT INTO inventory ({",".join(cols)}) VALUES ({",".join("?" for _ in cols)})',[row[k] for k in cols])
                    c.execute('INSERT OR IGNORE INTO candidates VALUES (?,?,?)',(rid,row['pe_id'],int(matches(row,r))))
            matched=c.execute('SELECT pe_id FROM candidates WHERE request_id=? AND matches_criteria=1 ORDER BY rowid',(rid,)).fetchall()
            fallback=len(matched)>1 and allow_first_match(r)
            selected=matched[0][0] if len(matched)==1 or fallback else None
            status='resolved' if selected else 'ambiguous' if matched else 'unresolved'
            note='No location supplied; selected first exact match in source order' if fallback else None
            c.execute('UPDATE requests SET status=?,selected_pe_id=?,error=?,updated_at=? WHERE request_id=?',(status,selected,note,now(),rid));c.commit()
            print(f'{rid}: {status} ({len(matched)} exact matches)'+(f' — {note}' if note else ''))
        except Exception as e:
            c.execute('UPDATE requests SET status=?,error=?,updated_at=? WHERE request_id=?',('error',str(e),now(),rid));c.commit(); print(f'{rid}: error: {e}')

def filename(row):
    if row['agency'] not in ('OCC','FDIC','FRB','OTS') or not re.fullmatch(r'[A-Za-z0-9-]+',row['agency_id'] or ''): raise ValueError('Missing or unsafe agency identifier')
    if not row['exam_date'] or date(row['exam_date'])!=row['exam_date']: raise ValueError('A source examination date is required; FDIC requires a unique FFIEC match')
    return f'{row["agency"]}_{row["agency_id"]}_{row["exam_date"]}.pdf'

def download(root,c,client,requests):
    for req in requests:
        saved=c.execute('SELECT criteria_json FROM requests WHERE request_id=?',(req['request_id'],)).fetchone()
        if saved and saved[0]!=json.dumps(req,sort_keys=True):
            print(req['request_id']+': manifest changed; run discover before downloading'); continue
        row=c.execute('SELECT i.* FROM requests r JOIN inventory i ON r.selected_pe_id=i.pe_id WHERE r.request_id=? AND r.status=?',(req['request_id'],'resolved')).fetchone()
        if row is None: print(req['request_id']+': no resolved selection; skipped'); continue
        attempt=dict(pe_id=row['pe_id'],timestamp=now(),requested_url=row['pdf_url'],status='failed')
        tmp=None
        try:
            if not row['pdf_url']: raise ValueError('No official PDF URL')
            target=root/'data/raw'/row['agency']/filename(row)
            if target.exists():
                sha=digest(target.read_bytes())
                if not row['sha256'] or sha!=row['sha256']: raise ValueError('Existing file checksum collision; preserved unchanged')
                target.chmod(0o444); attempt.update(status='skipped',local_path=str(target.relative_to(root)),sha256=sha,bytes=target.stat().st_size)
            else:
                body,final,status,headers=client.fetch(row['pdf_url']); attempt.update(final_url=final,http_status=status)
                if not body.startswith(b'%PDF-'): raise ValueError('Response lacks PDF signature; not saved')
                sha=digest(body)
                with tempfile.NamedTemporaryFile(dir=root/'data',delete=False) as f:
                    tmp=Path(f.name); f.write(body)
                target.parent.mkdir(parents=True,exist_ok=True)
                # Hard-link publication refuses to overwrite existing files atomically.
                import os
                os.link(tmp,target); tmp.unlink(); tmp=None; target.chmod(0o444)
                attempt.update(status='downloaded',local_path=str(target.relative_to(root)),sha256=sha,bytes=len(body))
            c.execute('UPDATE inventory SET download_status=?,local_path=?,sha256=?,bytes=? WHERE pe_id=?',('downloaded',attempt['local_path'],attempt['sha256'],attempt['bytes'],row['pe_id']))
        except Exception as e:
            attempt['error']=str(e)
            if isinstance(e,urllib.error.HTTPError): attempt['http_status']=e.code
            c.execute('UPDATE inventory SET download_status=? WHERE pe_id=?',('failed',row['pe_id']))
        finally:
            if tmp and tmp.exists(): tmp.unlink()
            cols=list(attempt);c.execute(f'INSERT INTO download_attempts ({",".join(cols)}) VALUES ({",".join("?" for _ in cols)})',list(attempt.values()));c.commit()
        print(req['request_id']+': '+attempt['status']+(' — '+attempt['error'] if attempt.get('error') else ''))

def report(root,c,requests):
    result=[]
    for r in requests:
        request=c.execute('SELECT * FROM requests WHERE request_id=?',(r['request_id'],)).fetchone()
        candidates=[dict(x) for x in c.execute('SELECT i.*,c.matches_criteria FROM candidates c JOIN inventory i ON i.pe_id=c.pe_id WHERE c.request_id=?',(r['request_id'],))]
        result.append({'request':dict(request) if request else r,'candidates':candidates})
    (root/'reports/inventory.json').write_text(json.dumps(result,indent=2)+'\n')
    summary={}
    for entry in result:
        for row in entry['candidates']:
            key=(row['agency'],(row['exam_date'] or 'unknown')[:4])
            group=summary.setdefault(key,{});group[row['pe_id']]=row
    selected={e['request'].get('selected_pe_id') for e in result}
    counts=[dict(agency=a,exam_year=y,identified=len(rows),selected=sum(k in selected for k in rows),downloaded=sum(x['download_status']=='downloaded' for x in rows.values()),failed=sum(x['download_status']=='failed' for x in rows.values()),unresolved=sum(k not in selected for k in rows),scan_status='not_assessed') for (a,y),rows in sorted(summary.items())]
    (root/'reports/summary.json').write_text(json.dumps({'scope':'Development manifest only; candidate histories may include other years','counts':counts},indent=2)+'\n')
    parts=['<!doctype html><html><meta charset="utf-8"><title>CRA acquisition inventory</title><style>body{font:16px system-ui;margin:32px}table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:8px;text-align:left}small{color:#555}</style><h1>Development acquisition inventory</h1><p>Website metadata only. PDF contents uninspected. Scan classification deferred.</p>']
    for e in result:
        r=e['request'];parts.append('<h2>'+html.escape(r['request_id'])+'</h2><p>'+html.escape(r.get('status','not searched'))+' '+html.escape(r.get('error') or '')+'</p><table><tr><th>Institution</th><th>ID</th><th>Exam date</th><th>Release date</th><th>Rating</th><th>Download</th><th>Candidate ID</th><th>Official PDF</th></tr>')
        for x in e['candidates']:
            vals=[x['institution_name'],x['agency_id'],x['exam_date'],x['release_date'],x['rating'],x['download_status']]
            parts.append('<tr>'+''.join('<td>'+html.escape(str(v) if v is not None else 'Unknown')+'</td>' for v in vals)+'<td>'+html.escape(x['pe_id'])+'</td><td>'+('<a href="'+html.escape(x['pdf_url'],quote=True)+'">PDF link</a>' if x['pdf_url'] else 'Unavailable')+'</td></tr>')
        parts.append('</table>')
    (root/'reports/inventory.html').write_text('\n'.join(parts)+'</html>')
    print('Reports written to reports/ (HTML and JSON)')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['discover','select','download','report']);p.add_argument('--manifest',type=Path,default=ROOT/'config/development_sample.json');p.add_argument('--request-id');p.add_argument('--candidate-id');p.add_argument('--ffiec-file',type=Path);a=p.parse_args()
    requests=manifest(a.manifest.resolve());config=json.loads((ROOT/'config/sources.json').read_text());c=connect(ROOT);client=Client(ROOT,config)
    if a.command=='discover': discover(ROOT,c,client,requests,config,a.ffiec_file)
    elif a.command=='download': download(ROOT,c,client,requests)
    elif a.command=='report': report(ROOT,c,requests)
    else:
        if not a.request_id or not a.candidate_id: p.error('select requires --request-id and --candidate-id')
        if a.request_id not in {x['request_id'] for x in requests}: p.error('Request not in manifest')
        if not c.execute('SELECT 1 FROM candidates WHERE request_id=? AND pe_id=?',(a.request_id,a.candidate_id)).fetchone(): p.error('Candidate does not belong to request')
        c.execute('UPDATE requests SET selected_pe_id=?,status=?,updated_at=? WHERE request_id=?',(a.candidate_id,'resolved',now(),a.request_id));c.commit()
    c.close()

if __name__=='__main__':main()
