"""Preflight checks. Offline needs no credential or network; online verifies the provider without spending."""
import os
from pathlib import Path
import shutil
import sqlite3
import sys

from .io import fingerprint,read_json,sha256_file
from .paths import ROOT

def check(name,ok,detail=''):
    return dict(name=name,ok=bool(ok),detail=detail)

def offline(root=ROOT,final=None,expect=None):
    from .paths import project_config
    cfg=project_config(root);final=final or cfg['manifest'];expect=expect or cfg['expected_documents']
    root=Path(root);out=[]
    out.append(check('python>=3.10',sys.version_info>=(3,10),sys.version.split()[0]))
    for mod in ('pdfplumber','pypdfium2','filelock','anthropic','PIL'):
        try:
            m=__import__(mod);out.append(check(f'import {mod}',True,getattr(m,'__version__','')))
        except ImportError as e:out.append(check(f'import {mod}',False,str(e)))
    path=root/final
    if not path.is_file():out.append(check('final manifest',False,str(path)));return out
    m=read_json(path);docs=m['documents']
    out.append(check('manifest count',len(docs)==expect,f'{len(docs)} documents'))
    out.append(check('unique pe_id',len({d['pe_id'] for d in docs})==len(docs)))
    out.append(check('unique hashes',len({d['sha256'] for d in docs})==len(docs)))
    bad=[];writable=[];missing=[]
    for d in docs:
        p=root/d['path']
        if not p.is_file():missing.append(d['pe_id']);continue
        if sha256_file(p)!=d['sha256']:bad.append(d['pe_id'])
        if os.name=='posix' and p.stat().st_mode&0o222:writable.append(d['pe_id'])
    out.append(check('files present',not missing,f'{len(missing)} missing'))
    out.append(check('sha256 match',not bad,f'{len(docs)-len(bad)-len(missing)}/{len(docs)} verified'))
    out.append(check('files read-only',not writable if os.name=='posix' else True,'POSIX permission check' if os.name=='posix' else 'skipped on this platform'))
    out.append(check('scans confirmed',sum(d['scan_status']=='scanned' for d in docs)>=cfg['scan_quota'],f"{cfg['scan_quota']} required"))
    free=shutil.disk_usage(root).free
    out.append(check('free space>=1GB',free>=1<<30,f'{free>>20} MB'))
    schema=root/'schemas/research_schema.sql'
    out.append(check('research schema',schema.is_file(),fingerprint(schema.read_text(encoding='utf-8'))[:12] if schema.is_file() else ''))
    pricing=root/'config/pricing.json'
    if pricing.is_file():
        pr=read_json(pricing);out.append(check('pricing config',True,f"version {pr['version']}"))
    else:out.append(check('pricing config',False,'config/pricing.json missing'))
    db=root/'data/research.sqlite'
    if db.is_file():
        with sqlite3.connect(db.as_uri()+'?mode=ro',uri=True) as c:
            n=c.execute('select count(*) from table_a_exam_level').fetchone()[0]
            out.append(check('research database integrity',c.execute('pragma integrity_check').fetchone()[0]=='ok',f'{n} accepted evaluations'))
    exe=os.environ.get('CRA_TESSERACT') or shutil.which('tesseract')
    out.append(check('tesseract (optional)',True,exe or 'not installed: image pages queue for review or the vision path'))
    return out

def online(root=ROOT,probe=False,model=None):
    from .provider import Anthropic,Budget,DEFAULT_MODEL
    out=[]
    key=bool(os.environ.get('ANTHROPIC_API_KEY'))
    out.append(check('ANTHROPIC_API_KEY present',key,'(value never printed)'))
    if not key:return out
    try:
        p=Anthropic(model or DEFAULT_MODEL);info=p.preflight()
        out.append(check('model reachable',True,f"{info['model']} price_version={info['price_version']}"))
        out.append(check('capabilities',info['capabilities'] is not None,str(info['capabilities'])[:200]))
    except Exception as e:
        out.append(check('model reachable',False,f'{type(e).__name__}: {e}'));return out
    ledger=Budget(Path(root)/'data/model/ledger.sqlite')
    s=ledger.summary()
    out.append(check('budget headroom',s['remaining']>0,f"cap ${s['cap']:.2f} spent ${s['spent']:.4f} held ${s['reserved_unsettled']:.4f} remaining ${s['remaining']:.4f}"))
    if probe:
        schema=dict(type='object',additionalProperties=False,required=['ok'],properties=dict(ok=dict(type='boolean')))
        r=p.call('Reply with JSON only.','Return {"ok": true}.',schema,200,ledger,Path(root)/'data/model/raw',label='probe')
        out.append(check('structured output probe',r['parsed'].get('ok') is True,f"cost ${r['cost']:.5f}"))
    return out
