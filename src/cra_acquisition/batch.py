"""Batch API path (50% price). It only warms the response cache; `run_document` then builds the
proposal from cache hits, so validation, staging and flags are identical to the synchronous path.

Every request is reserved in the ledger first (at the batch rate), usage is settled per result, and
truncated tasks are split and resubmitted in a later round (never accepted)."""
import time
from pathlib import Path

from .io import loads,read_json,write_json
from .provider import task_key,usage_cost
from . import pipeline,runstate,tasks as T

def _cache_path(dirs,key):return Path(dirs['cache'])/f'{key}.json'

def prepare_requests(provider,bundle_by_doc,cols,prompts_,dirs,effort,targets,extra=None,task_override=None,efforts=None,retry_failed=False):
    """-> list of dict(custom_id, params, cache_key, pe_id, task, reserve_key) for tasks not yet cached."""
    out=[]
    for pe_id,(rec,bundle) in bundle_by_doc.items():
        for task in (task_override or {}).get(pe_id) or T.plan(bundle,targets):
            target=task['target'];system=T.system_prompt(target,cols,prompts_);schema=T.schema_for(target,cols)
            max_tokens=T.MAX_TOKENS[target];eff=(efforts or {}).get(target,effort)
            content=T.user_content(bundle,task['pages'],target)
            key=pipeline.cache_key(bundle,provider,target,system,content,schema,max_tokens,eff,extra)
            cp=_cache_path(dirs,key)
            if cp.is_file() and not (retry_failed and read_json(cp).get('failed')):continue
            params=provider.payload(system,content,schema,max_tokens,eff)
            out.append(dict(custom_id='k'+key[:62],params=params,cache_key=key,pe_id=pe_id,task=task,
                            reserve_key=task_key(provider.model,system,content,schema,max_tokens,eff,dict(batch=True,window=str(task['window'])))))
    return out

def _batch_dir(dirs):
    d=Path(dirs['batches']) if 'batches' in dirs else Path(dirs['cache']).parent/'batches'
    d.mkdir(parents=True,exist_ok=True);return d

def submit_round(provider,ledger,requests,dirs,run_id):
    """Reserve, create the batch, and persist its id and reservation map to disk immediately, so an
    interrupted run can be collected later (a created batch is processed and billed server-side)."""
    reservations={}
    try:
        for r in requests:
            est=provider.worst_case(provider.count_tokens(r['params'])+256,r['params']['max_tokens'])*provider.price['batch_discount']
            reservations[r['custom_id']]=ledger.reserve(r['reserve_key'],est,provider.price_version)
    except BaseException:
        for ident in reservations.values():ledger.cancel_unsent(ident)   # nothing was sent: release every hold, whatever the error
        raise
    try:
        batch=provider.client.messages.batches.create(requests=[dict(custom_id=r['custom_id'],params=r['params']) for r in requests])
    except Exception as e:
        status=getattr(e,'status_code',None)
        for ident in reservations.values():
            if isinstance(status,int) and status<500:ledger.settle(ident,0,'failed_unbilled',f'batch create HTTP {status}')
            else:ledger.mark_ambiguous(ident,f'batch create {type(e).__name__}')
        raise
    record=dict(batch_id=batch.id,run_id=run_id,collected=False,requests=[
        dict(custom_id=r['custom_id'],cache_key=r['cache_key'],pe_id=r['pe_id'],task=r['task'],reserve_key=r['reserve_key'],
             max_tokens=r['params']['max_tokens'],reservation=reservations[r['custom_id']]) for r in requests])
    write_json(_batch_dir(dirs)/f'{batch.id}.json',record)
    return batch.id

def pending_batches(dirs):
    out=[]
    for f in sorted(_batch_dir(dirs).glob('*.json')):
        rec=read_json(f)
        if not rec.get('collected'):out.append(rec)
    return out

def collect_round(provider,ledger,batch_id,dirs,db,run_id,sleep=time.sleep,poll_seconds=30,max_polls=2880):
    """Wait for a persisted batch, settle every request, warm the cache. Returns tasks to split and resubmit."""
    path=_batch_dir(dirs)/f'{batch_id}.json';record=read_json(path)
    if record.get('collected'):return []
    by_id={r['custom_id']:r for r in record['requests']};reservations={c:r['reservation'] for c,r in by_id.items()}
    for _ in range(max_polls):
        batch=provider.client.messages.batches.retrieve(batch_id)
        if batch.processing_status=='ended':break
        sleep(poll_seconds)
    else:
        raise TimeoutError(f'Batch {batch_id} did not finish; reservations are kept and `cra batches --collect {batch_id}` can resume it')
    resplit=[]
    for entry in provider.client.messages.batches.results(batch_id):
        req=by_id.get(entry.custom_id)
        if req is None or entry.custom_id not in reservations:continue
        ident=reservations.pop(entry.custom_id)
        base=dict(run_id=run_id,pe_id=req['pe_id'],target=req['task']['target'],window=req['task']['window'],cache_key=req['cache_key'],
                  model=provider.model,prompt_hash='',schema_hash='',effort=None,max_tokens=req['max_tokens'],task_key=req['reserve_key'])
        kind=entry.result.type
        if kind!='succeeded':
            ledger.settle(ident,0,'failed_unbilled',kind)
            runstate.log_request(db,status=f'batch_{kind}',error=str(getattr(entry.result,'error',''))[:300],**base);continue
        msg=entry.result.message
        cost=usage_cost(msg.usage,provider.price,batch=True) if getattr(msg,'usage',None) else None
        if cost is None:ledger.settle(ident,ledger_amount(ledger,ident),'no_usage','batch result lacked usage')
        else:ledger.settle(ident,cost)
        base['cost_usd']=cost
        target='tables' if req['task']['target'] in ('d','dc') else 'facts'
        cpath=_cache_path(dirs,req['cache_key']);stop=getattr(msg,'stop_reason',None)
        if getattr(msg,'model',None)!=provider.model:
            write_json(cpath,dict(failed='MalformedOutputError',detail='response model differs'));continue
        if stop=='max_tokens':
            write_json(cpath,dict(failed='TruncatedError',detail='batch output reached max_tokens'))
            parts=T.split_task(None,req['task'])
            if parts:resplit.append((req['pe_id'],parts))
            runstate.log_request(db,status='batch_truncated',**base);continue
        if stop=='refusal':
            write_json(cpath,dict(failed='RefusalError',detail=str(getattr(msg,'stop_details',None))));runstate.log_request(db,status='batch_refusal',**base);continue
        text=''.join(b.text for b in msg.content if getattr(b,'type',None)=='text')
        try:
            parsed=loads(text)
            if stop!='end_turn' or not isinstance(parsed,dict) or not isinstance(parsed.get(target),list):raise ValueError('bad shape')
        except ValueError as e:
            write_json(cpath,dict(failed='MalformedOutputError',detail=str(e)));runstate.log_request(db,status='batch_malformed',**base);continue
        usage=msg.usage.model_dump() if hasattr(msg.usage,'model_dump') else dict(msg.usage or {})
        write_json(cpath,dict(parsed=parsed,usage=usage,cost=cost,request_id=getattr(msg,'_request_id',None),price_version=provider.price_version,batch=True))
        runstate.log_request(db,status='ok_batch',usage_json=usage,**base)
    for ident in reservations.values():   # absent from the results: outcome unknown, keep the reservation
        ledger.mark_ambiguous(ident,'missing from batch results')
    record['collected']=True;write_json(path,record)
    return resplit

def run_round(provider,ledger,requests,dirs,db,run_id,sleep=time.sleep,poll_seconds=30,max_polls=2880):
    if not requests:return []
    bid=submit_round(provider,ledger,requests,dirs,run_id)
    return collect_round(provider,ledger,bid,dirs,db,run_id,sleep,poll_seconds,max_polls)

def warm_cache(manifest,ids,provider,ledger,staging_path,run_id,root,effort='low',targets=('a','b','c','e','peers','d'),sleep=time.sleep,rounds=4,poll_seconds=30,extra=None,efforts=None,retry_failed=False):
    from .prepare import load_or_prepare
    db=runstate.init_staging(staging_path,root);cols=T.research_columns(root);prompts_=T.prompts()
    dirs={k:Path(root)/'data/model'/k for k in ('cache','raw','proposals','batches')}
    for d in dirs.values():d.mkdir(parents=True,exist_ok=True)
    docs={r['pe_id']:(r,load_or_prepare(root,r)) for r in manifest['documents'] if r['pe_id'] in ids}
    override=None;submitted=0
    try:
        for rec in pending_batches(dirs):   # a batch from an interrupted run is collected first, never resubmitted
            for pe_id,parts in collect_round(provider,ledger,rec['batch_id'],dirs,db,run_id,sleep,poll_seconds):
                override=override or {};override.setdefault(pe_id,[]).extend(parts)
        for n in range(rounds):
            reqs=prepare_requests(provider,docs,cols,prompts_,dirs,effort,targets,extra,override,efforts,retry_failed)
            if not reqs:break
            submitted+=len(reqs)
            resplit=run_round(provider,ledger,reqs,dirs,db,run_id,sleep,poll_seconds)
            override={}
            for pe_id,parts in resplit:override.setdefault(pe_id,[]).extend(parts)
            if not override:break
    finally:db.close()
    return dict(requests_submitted=submitted,rounds=n+1)

def ledger_amount(ledger,ident):
    from .provider import ledger_max
    return ledger_max(ledger,ident)
