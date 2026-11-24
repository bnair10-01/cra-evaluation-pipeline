"""Anthropic provider with one persistent, locked spending ledger.

Safety rules: every request reserves its worst-case cost first; unknown outcomes keep the
full reservation; usage above the reservation is recorded (never under-counted); the cap lives
in the ledger and can only be raised with an explicit reason; model identity is never
substituted; refusals and truncation are errors, not partial results."""
from contextlib import closing
import json
import math
import os
from pathlib import Path
import sqlite3
import time

from .io import atomic_write_text, fingerprint, loads, read_json
from .paths import ROOT

DEFAULT_MODEL='claude-sonnet-5-5'
DEFAULT_CAP=25.0
MAX_ATTEMPTS=3   # per task, per run (a new run gets a fresh allowance); never unlimited
MICRO=1_000_000

class BudgetError(ValueError):pass
class RefusalError(ValueError):pass
class TruncatedError(ValueError):
    """Output hit max_tokens; the caller must split the task, never accept it."""
class MalformedOutputError(ValueError):pass
class RawWriteError(OSError):pass

def money(value,name='amount'):
    if isinstance(value,bool) or not isinstance(value,(int,float)):raise BudgetError(f'{name} must be a number')
    if not math.isfinite(value) or value<0:raise BudgetError(f'{name} must be finite and non-negative')
    return math.ceil(round(value*MICRO,6))  # round up: never under-reserve

def load_pricing(path=None,model=DEFAULT_MODEL):
    data=read_json(path or ROOT/'config/pricing.json')
    if model not in data['models']:raise BudgetError(f'No verified pricing for {model}')
    return data['version'],data['models'][model]

def usage_cost(usage,price,batch=False):
    """Dollars for a usage object/dict. Unknown or negative counts are rejected."""
    get=(lambda k:usage.get(k)) if isinstance(usage,dict) else (lambda k:getattr(usage,k,None))
    def count(k):
        v=get(k)
        if v is None:return 0
        if isinstance(v,bool) or not isinstance(v,int) or v<0:raise BudgetError(f'Invalid usage field {k}')
        return v
    cache_write=count('cache_creation_input_tokens')
    cost=(count('input_tokens')*price['input']+count('output_tokens')*price['output']
          +cache_write*price['cache_write_1h']  # conservative: the dearer write tier
          +count('cache_read_input_tokens')*price['cache_read'])/MICRO
    return cost*(price['batch_discount'] if batch else 1)

def image_tokens(width,height):
    if width<1 or height<1:raise ValueError('Invalid image size')
    return math.ceil(width/28)*math.ceil(height/28)

def estimate_text_tokens(text):
    """Offline upper bound used only for `cra estimate`; live calls use count_tokens."""
    return math.ceil(len(text.encode('utf-8'))/2.5)+200

class Budget:
    def __init__(self,path,cap=None):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True);self.run=None   # set to a run label to count attempts per run
        with closing(sqlite3.connect(self.path)) as c, c:
            c.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            c.execute('CREATE TABLE IF NOT EXISTS reservations (id INTEGER PRIMARY KEY, task TEXT NOT NULL, maximum INTEGER NOT NULL, actual INTEGER, status TEXT NOT NULL, price_version TEXT, note TEXT)')
            c.execute('CREATE TABLE IF NOT EXISTS cap_changes (id INTEGER PRIMARY KEY, old_cap INTEGER, new_cap INTEGER, reason TEXT NOT NULL)')
            c.execute('CREATE INDEX IF NOT EXISTS reservation_task ON reservations(task)')
            if 'run_id' not in [r[1] for r in c.execute('PRAGMA table_info(reservations)')]:c.execute('ALTER TABLE reservations ADD COLUMN run_id TEXT')
            row=c.execute("SELECT value FROM settings WHERE key='cap_micro'").fetchone()
            if row is None:
                c.execute("INSERT INTO settings VALUES ('cap_micro',?)",(str(money(DEFAULT_CAP if cap is None else cap,'cap')),))
            elif cap is not None and money(cap,'cap')!=int(row[0]):
                raise BudgetError('Ledger cap is locked; use raise_cap(new_cap, reason)')
    @property
    def cap(self):
        with closing(sqlite3.connect(self.path)) as c:
            return int(c.execute("SELECT value FROM settings WHERE key='cap_micro'").fetchone()[0])
    def raise_cap(self,new_cap,reason):
        if not isinstance(reason,str) or len(reason.strip())<10:raise BudgetError('A written reason is required to change the cap')
        amount=money(new_cap,'cap')
        with closing(sqlite3.connect(self.path,isolation_level=None)) as c:
            c.execute('BEGIN IMMEDIATE')
            old=int(c.execute("SELECT value FROM settings WHERE key='cap_micro'").fetchone()[0])
            c.execute('INSERT INTO cap_changes(old_cap,new_cap,reason) VALUES (?,?,?)',(old,amount,reason))
            c.execute("UPDATE settings SET value=? WHERE key='cap_micro'",(str(amount),))
            c.commit()
    def _spent(self,c):
        return c.execute('SELECT coalesce(sum(coalesce(actual,maximum)),0) FROM reservations').fetchone()[0]
    def reserve(self,task,dollars,price_version=None):
        amount=money(dollars,'reservation')
        if not isinstance(task,str) or not task:raise BudgetError('Task key required')
        with closing(sqlite3.connect(self.path,isolation_level=None)) as c:
            c.execute('BEGIN IMMEDIATE')
            used=c.execute('SELECT count(*) FROM reservations WHERE task=?'+(' AND run_id=?' if self.run else ''),(task,self.run) if self.run else (task,)).fetchone()[0]
            if used>=MAX_ATTEMPTS:
                c.rollback();raise BudgetError(f'Task used its {MAX_ATTEMPTS} attempts'+(' in this run (start a new run to try again)' if self.run else ''))
            cap=int(c.execute("SELECT value FROM settings WHERE key='cap_micro'").fetchone()[0])
            if self._spent(c)+amount>cap:
                c.rollback();raise BudgetError('Pilot budget exhausted before request')
            n=c.execute("INSERT INTO reservations(task,maximum,status,price_version,run_id) VALUES (?,?,'reserved',?,?)",(task,amount,price_version,self.run)).lastrowid
            c.commit();return n
    def settle(self,ident,dollars,status='settled',note=None):
        """Record the true charge. A charge above the reservation is stored in full and flagged
        'overrun' so later reservations see it; it is never silently capped."""
        amount=money(dollars,'charge')
        with closing(sqlite3.connect(self.path,isolation_level=None)) as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT maximum FROM reservations WHERE id=? AND actual IS NULL',(ident,)).fetchone()
            if not row:
                c.rollback();raise BudgetError('Unknown or settled reservation')
            if amount>row[0]:status='overrun'
            c.execute('UPDATE reservations SET actual=?,status=?,note=? WHERE id=?',(amount,status,note,ident))
            c.commit()
        return status
    def mark_ambiguous(self,ident,note):
        with closing(sqlite3.connect(self.path)) as c, c:
            c.execute("UPDATE reservations SET status='ambiguous',note=? WHERE id=? AND actual IS NULL",(note,ident))
    def release(self,ident,reason):
        """Settle a stale reservation at $0 after a person has confirmed nothing was billed for it."""
        if not isinstance(reason,str) or len(reason.strip())<10:raise BudgetError('A written reason is required')
        self.settle(ident,0,'released',reason.strip())
    def unsettled(self):
        with closing(sqlite3.connect(self.path)) as c:
            return [dict(id=r[0],task=r[1],maximum=r[2]/MICRO,status=r[3]) for r in c.execute('SELECT id,task,maximum,status FROM reservations WHERE actual IS NULL ORDER BY id')]
    def cancel_unsent(self,ident):
        """Remove a reservation whose request was provably never sent."""
        with closing(sqlite3.connect(self.path)) as c, c:
            c.execute('DELETE FROM reservations WHERE id=? AND actual IS NULL',(ident,))
    def attempts(self,task):
        with closing(sqlite3.connect(self.path)) as c:
            return c.execute('SELECT count(*) FROM reservations WHERE task=?',(task,)).fetchone()[0]   # used only to number raw-response files
    def summary(self):
        with closing(sqlite3.connect(self.path)) as c:
            cap=self.cap
            settled=c.execute("SELECT coalesce(sum(actual),0) FROM reservations WHERE actual IS NOT NULL").fetchone()[0]
            held=c.execute("SELECT coalesce(sum(maximum),0) FROM reservations WHERE actual IS NULL").fetchone()[0]
            overruns=c.execute("SELECT count(*) FROM reservations WHERE status='overrun'").fetchone()[0]
            ambiguous=c.execute("SELECT count(*) FROM reservations WHERE status='ambiguous'").fetchone()[0]
        return dict(cap=cap/MICRO,spent=settled/MICRO,reserved_unsettled=held/MICRO,
                    remaining=(cap-settled-held)/MICRO,overruns=overruns,ambiguous=ambiguous)

def task_key(model,system,content,schema,max_tokens,effort,extra=None):
    """Attempt limits follow the content, so renaming a task cannot evade them."""
    return fingerprint(dict(model=model,system=system,content=content,schema=schema,max_tokens=max_tokens,effort=effort,extra=extra))

class Anthropic:
    """Thin, strict wrapper over the official SDK. A client may be injected for tests."""
    def __init__(self,model=DEFAULT_MODEL,client=None,pricing_path=None,timeout=600.0):
        self.model=model
        self.price_version,self.price=load_pricing(pricing_path,model)
        if client is None:
            if not os.environ.get('ANTHROPIC_API_KEY'):raise BudgetError('Set ANTHROPIC_API_KEY in the process environment')
            import anthropic
            client=anthropic.Anthropic(max_retries=0,timeout=timeout)  # ledger must see every attempt
        self.client=client
    def preflight(self):
        info=self.client.models.retrieve(self.model)
        if getattr(info,'id',None)!=self.model:raise ValueError('Model identifier mismatch; no substitution allowed')
        caps=getattr(info,'capabilities',None)
        return dict(model=info.id,max_input_tokens=getattr(info,'max_input_tokens',None),
                    max_tokens=getattr(info,'max_tokens',None),capabilities=caps.model_dump() if hasattr(caps,'model_dump') else caps,
                    price_version=self.price_version)
    def payload(self,system,content,schema,max_tokens,effort):
        if isinstance(max_tokens,bool) or not isinstance(max_tokens,int) or not 1<=max_tokens<=self.price['max_output_tokens']:
            raise BudgetError('max_tokens out of range')
        if effort not in ('low','medium','high','xhigh','max'):raise BudgetError('Invalid effort')
        if schema.get('additionalProperties') is not False:raise ValueError('Schema root needs additionalProperties:false')
        return dict(model=self.model,max_tokens=max_tokens,system=system,
                    messages=[{'role':'user','content':content}],
                    output_config={'effort':effort,'format':{'type':'json_schema','schema':schema}})
    def count_tokens(self,payload):
        keys=('model','system','messages','output_config')
        return self.client.messages.count_tokens(**{k:payload[k] for k in keys}).input_tokens
    def worst_case(self,input_tokens,max_tokens):
        p=self.price
        return (input_tokens*p['input']+max_tokens*p['output'])/MICRO
    def call(self,system,content,schema,max_tokens,ledger,raw_dir,effort='low',label='task',extra=None):
        payload=self.payload(system,content,schema,max_tokens,effort)
        key=task_key(self.model,system,content,schema,max_tokens,effort,extra)
        input_tokens=self.count_tokens(payload)+256  # exact count plus margin
        ident=ledger.reserve(key,self.worst_case(input_tokens,max_tokens),self.price_version)
        attempt=ledger.attempts(key)
        started=time.monotonic()
        try:
            if payload['max_tokens']>16000:   # large outputs must be streamed to avoid HTTP timeouts
                with self.client.messages.stream(**payload) as stream:response=stream.get_final_message()
            else:response=self.client.messages.create(**payload)
        except Exception as e:
            status=getattr(e,'status_code',None)
            if isinstance(status,int) and status<500:
                ledger.settle(ident,0,'failed_unbilled',f'HTTP {status}')
            else:
                ledger.mark_ambiguous(ident,f'{type(e).__name__}: {status}')  # keep the full reservation
            raise
        usage=getattr(response,'usage',None)
        if usage is None:
            ledger.settle(ident,ledger_max(ledger,ident),'no_usage','response lacked usage; full reservation kept')
            cost=None
        else:
            cost=usage_cost(usage,self.price);ledger.settle(ident,cost)
        raw=Path(raw_dir)/f'{label}-{key[:16]}-{attempt}.json'
        try:
            text=response.to_json() if hasattr(response,'to_json') else json.dumps(response)
            atomic_write_text(raw,text+'\n',exclusive=True)
        except OSError as e:
            raise RawWriteError(f'Billed response could not be saved ({e}); cost recorded in the ledger') from e
        if getattr(response,'model',None)!=self.model:raise ValueError('Response model differs; raw result retained')
        stop=getattr(response,'stop_reason',None)
        if stop=='refusal':raise RefusalError(f'Refused: {getattr(response,"stop_details",None)}')
        if stop=='max_tokens':raise TruncatedError('Output reached max_tokens; split the task')
        if stop!='end_turn':raise ValueError(f'Unexpected stop reason {stop}')
        text=''.join(b.text for b in response.content if getattr(b,'type',None)=='text')
        try:parsed=loads(text)
        except ValueError as e:raise MalformedOutputError(f'Invalid JSON: {e}') from e
        return dict(parsed=parsed,cost=cost,usage=usage.model_dump() if hasattr(usage,'model_dump') else dict(usage or {}),
                    request_id=getattr(response,'_request_id',None),raw_path=str(raw),task_key=key,
                    seconds=time.monotonic()-started,price_version=self.price_version)

def ledger_max(ledger,ident):
    with closing(sqlite3.connect(ledger.path)) as c:
        return c.execute('SELECT maximum FROM reservations WHERE id=?',(ident,)).fetchone()[0]/MICRO
