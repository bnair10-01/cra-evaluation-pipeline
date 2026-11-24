"""Run section tasks for one document: cache, call, split on truncation, merge, validate, stage."""
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import time

from .io import fingerprint,read_json,write_json
from .provider import BudgetError,RefusalError,TruncatedError,MalformedOutputError,RawWriteError
from .research import save
from . import review,reviewstore,runstate,tasks as T

CODE_FILES=('tasks.py','pipeline.py','research.py','segment.py','tables.py','provider.py')
def code_version():
    h=sha256()
    for name in CODE_FILES:h.update((Path(__file__).with_name(name)).read_bytes())
    return h.hexdigest()

class TaskFailure(Exception):pass
class CacheMissError(Exception):
    """--cache-only found no stored response for a task. That task is skipped, not the whole run."""

def cache_key(bundle,provider,target,system,content,schema,max_tokens,effort,extra):
    """Key = the request actually sent (document, model, prompt, page text, schema, limits). Merge and
    validation code is deliberately excluded: the cache holds raw model output, so improving the
    checks never re-bills a request. `code_version` is recorded in the freeze instead."""
    return fingerprint(dict(pdf=bundle['sha256'],model=provider.model,target=target,system=sha256(system.encode()).hexdigest(),
                            content=sha256(content.encode()).hexdigest(),schema=fingerprint(schema),max_tokens=max_tokens,
                            effort=effort,extra=extra))

def run_task(task,bundle,provider,ledger,dirs,cols,prompts_,db,run_id,pe_id,effort,extra,stats,retry_failed=False):
    target=task['target'];system=T.system_prompt(target,cols,prompts_);schema=T.schema_for(target,cols)
    max_tokens=T.MAX_TOKENS[target];content=T.user_content(bundle,task['pages'],target)
    key=cache_key(bundle,provider,target,system,content,schema,max_tokens,effort,extra)
    cache=Path(dirs['cache'])/f'{key}.json'
    base=dict(run_id=run_id,pe_id=pe_id,target=target,window=task['window'],cache_key=key,model=provider.model,
              prompt_hash=sha256(system.encode()).hexdigest(),schema_hash=fingerprint(schema),effort=effort,max_tokens=max_tokens)
    if cache.is_file():
        try:
            cached=read_json(cache)
            if cached.get('failed') and retry_failed:raise OSError('retrying a stored failure')   # fall through to a fresh call
            if cached.get('failed'):   # a batch result that was refused/truncated/malformed: do not pay to repeat it
                runstate.log_request(db,task_key='cache',status='cached_'+cached['failed'],cache_hit=True,cost_usd=0.0,**base)
                raise {'TruncatedError':TruncatedError,'RefusalError':RefusalError}.get(cached['failed'],MalformedOutputError)(cached.get('detail','cached failure'))
            runstate.log_request(db,task_key='cache',status='cache_hit',cache_hit=True,cost_usd=0.0,**base)
            stats['cache_hits']+=1;return cached['parsed']
        except (TruncatedError,RefusalError,MalformedOutputError):raise
        except (OSError,ValueError):pass  # corrupt cache entries are ignored and re-requested
    started=time.monotonic()
    try:
        out=provider.call(system,content,schema,max_tokens,ledger,dirs['raw'],effort,label=f'{pe_id[-8:]}-{target}',extra=dict(window=task['window']))
    except (TruncatedError,RefusalError,MalformedOutputError,RawWriteError) as e:
        runstate.log_request(db,task_key=getattr(e,'task_key','unknown'),status=type(e).__name__,error=str(e),seconds=time.monotonic()-started,**base)
        raise
    # a malformed shape must not enter the cache
    parsed=out['parsed']
    key_name='tables' if target in ('d','dc') else 'facts'
    if not isinstance(parsed,dict) or not isinstance(parsed.get(key_name),list):
        raise MalformedOutputError('Output lacks the expected list')
    write_json(cache,dict(parsed=parsed,usage=out['usage'],cost=out['cost'],request_id=out['request_id'],price_version=out['price_version']))
    runstate.log_request(db,task_key=out['task_key'],status='ok',cost_usd=out['cost'],usage_json=out['usage'],
                         api_request_id=out['request_id'],raw_path=out['raw_path'],seconds=out['seconds'],**base)
    stats['calls']+=1;stats['cost']+=out['cost'] or 0.0
    return parsed

def run_document(record,bundle,provider,ledger,dirs,cols,db,run_id,targets=('a','b','c','e','peers','d'),effort='low',extra=None,attested=frozenset(),efforts=None,retry_failed=False):
    """Returns dict(status, stats, flags, proposal). Never partially accepts: any failed task => 'incomplete'."""
    pe_id=record['pe_id'];prompts_=T.prompts()
    stats=dict(calls=0,cache_hits=0,cost=0.0,failures=[]);results={t:[] for t in targets}
    runstate.set_status(db,run_id,pe_id,'extracting')
    queue=T.plan(bundle,targets)
    while queue:
        task=queue.pop(0)
        try:
            parsed=run_task(task,bundle,provider,ledger,dirs,cols,prompts_,db,run_id,pe_id,(efforts or {}).get(task['target'],effort),extra,stats,retry_failed)
        except TruncatedError:
            parts=T.split_task(bundle,task)
            if parts:queue=parts+queue
            else:stats['failures'].append(dict(target=task['target'],pages=task['pages'],reason='single page exceeds max_tokens'))
            continue
        except CacheMissError:
            stats['failures'].append(dict(target=task['target'],pages=task['pages'],reason='not in the cache (cache-only run)'));continue
        except (RefusalError,MalformedOutputError,RawWriteError) as e:
            stats['failures'].append(dict(target=task['target'],pages=task['pages'],reason=f'{type(e).__name__}: {e}'));continue
        except BudgetError:
            runstate.set_status(db,run_id,pe_id,'incomplete','budget or attempt limit reached');raise
        results[task['target']].append((task['window'],parsed['tables' if task['target'] in ('d','dc') else 'facts']))
    proposal,flags=T.build_proposal(pe_id,bundle,results,cols,attested)
    for f in stats['failures']:flags.append(dict(kind='task_failed',**f))
    status='staged'
    try:
        detail=save(db,pe_id,bundle,proposal,strict=True,attested=attested,flags=flags)
        # evidence on image-backed pages needs a person; one flag per page (attestation is per page), not one per value
        img=[f for f in flags if f['kind']=='image_review_required']
        if img:
            from collections import Counter
            flags[:]=[f for f in flags if f['kind']!='image_review_required']+[dict(kind='image_review_required',page=pg,values=n,detail='values on this page rest on its text layer; compare with the page image') for pg,n in sorted(Counter(f['page'] for f in img).items())]
    except (ValueError,sqlite3.Error) as e:   # a database constraint is a bug to record, never a reason to lose the run
        status='failed';detail=dict(error=f'{type(e).__name__}: {e}')
    if stats['failures'] and status=='staged':status='incomplete'
    runstate.add_flags(db,run_id,pe_id,flags)
    runstate.set_status(db,run_id,pe_id,status,json.dumps(dict(detail=detail,stats=stats),default=str))
    write_json(Path(dirs['proposals'])/f'{pe_id}.json',proposal)
    return dict(status=status,stats=stats,flags=flags,detail=detail)

def extract_group(manifest,ids,provider,ledger,staging_path,run_id,root,effort='low',targets=('a','b','c','e','peers','d'),extra=None,efforts=None,retry_failed=False):
    """Run documents one at a time (single concurrency). Stops cleanly when the budget refuses a request."""
    from .prepare import load_or_prepare
    db=runstate.init_staging(staging_path,root);cols=T.research_columns(root)
    dirs={k:Path(root)/'data/model'/k for k in ('cache','raw','proposals')}
    for d in dirs.values():d.mkdir(parents=True,exist_ok=True)
    summary=[];store=reviewstore.open_store(root)
    try:
        for rec in manifest['documents']:
            if rec['pe_id'] not in ids:continue
            if runstate.get_status(db,run_id,rec['pe_id']) in ('reviewed','accepted'):
                summary.append(dict(pe_id=rec['pe_id'],status='skipped_already_'+runstate.get_status(db,run_id,rec['pe_id'])));continue
            bundle=load_or_prepare(root,rec)
            if bundle['unreadable_pages']:
                runstate.set_status(db,run_id,rec['pe_id'],'unreadable',f"{bundle['unreadable_pages']} unreadable pages")
            attested=store.attested_pages(rec['pe_id'],rec['sha256'])
            try:
                r=run_document(rec,bundle,provider,ledger,dirs,cols,db,run_id,targets,effort,extra=extra,attested=frozenset(attested),efforts=efforts,retry_failed=retry_failed)
            except BudgetError as e:
                summary.append(dict(pe_id=rec['pe_id'],status='stopped_budget',reason=str(e)));break
            except Exception as e:   # one document's unexpected failure must not stop the others
                import traceback
                runstate.set_status(db,run_id,rec['pe_id'],'failed',traceback.format_exc()[-1500:])
                summary.append(dict(pe_id=rec['pe_id'],status='failed',reason=f'{type(e).__name__}: {e}'));continue
            review.apply_decisions(db,store,run_id,rec['pe_id'])   # earlier human decisions apply to the regenerated flags
            summary.append(dict(pe_id=rec['pe_id'],status=r['status'],calls=r['stats']['calls'],cache_hits=r['stats']['cache_hits'],
                                cost=round(r['stats']['cost'],4),flags=len(r['flags']),failures=len(r['stats']['failures'])))
    finally:
        db.close();store.close()
    return summary


class CacheOnlyProvider:
    """Reprocess cached model output after a code change: zero spend, no credential, any miss is an error."""
    def __init__(self,model='claude-sonnet-5-5'):self.model=model;self.price_version='cache-only'
    def call(self,*a,**k):raise CacheMissError('not in the cache; --cache-only never calls the model')
