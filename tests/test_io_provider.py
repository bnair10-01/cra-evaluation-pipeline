import json,math,os,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace as NS
from cra_acquisition import io as cio
from cra_acquisition.provider import (Anthropic,Budget,BudgetError,RefusalError,TruncatedError,MalformedOutputError,
                                      RawWriteError,usage_cost,money,image_tokens,task_key,load_pricing)

SCHEMA=dict(type='object',additionalProperties=False,required=['facts'],properties=dict(facts=dict(type='array',items=dict(type='string'))))
PRICE=load_pricing()[1]

class FakeResponse:
    def __init__(self,text='{"facts": []}',stop='end_turn',usage=None,model='claude-sonnet-5-5'):
        self.content=[NS(type='text',text=text)];self.stop_reason=stop;self.model=model;self._request_id='req_1'
        self.usage=usage if usage is not None else NS(input_tokens=1000,output_tokens=500,cache_creation_input_tokens=0,cache_read_input_tokens=0,model_dump=lambda:dict(input_tokens=1000,output_tokens=500))
        self.stop_details=None
    def to_json(self):return json.dumps(dict(model=self.model,stop=self.stop_reason))

class FakeMessages:
    def __init__(self,response=None,error=None,tokens=1000):
        self.response=response or FakeResponse();self.error=error;self.sent=0;self.tokens=tokens
    def count_tokens(self,**kw):return NS(input_tokens=self.tokens)
    def create(self,**kw):
        self.sent+=1
        if self.error:raise self.error
        return self.response

def provider(**kw):
    messages=FakeMessages(**kw);return Anthropic(client=NS(messages=messages,models=NS(retrieve=lambda m:NS(id=m,capabilities=None,max_input_tokens=1,max_tokens=1))))

class StatusError(Exception):
    def __init__(self,code):self.status_code=code

class IoTests(unittest.TestCase):
    def test_json_rejects_duplicates_and_nonfinite(self):
        for bad in ('{"a":1,"a":2}','{"a":NaN}','{"a":Infinity}'):
            with self.assertRaises(ValueError):cio.loads(bad)
        self.assertEqual(cio.loads('{"a":[1,2]}'),{'a':[1,2]})
    def test_atomic_exclusive_and_unicode_paths(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            p=Path(d)/'dir with spaces'/'é ü.json'
            cio.write_json(p,{'x':'ü'},exclusive=True)
            with self.assertRaises(FileExistsError):cio.write_json(p,{'x':2},exclusive=True)
            self.assertEqual(cio.read_json(p),{'x':'ü'})
            self.assertEqual([f for f in os.listdir(p.parent) if f.endswith('.part')],[])
    def test_fingerprint_is_order_independent_and_rejects_nan(self):
        self.assertEqual(cio.fingerprint({'a':1,'b':2}),cio.fingerprint({'b':2,'a':1}))
        with self.assertRaises(ValueError):cio.fingerprint({'a':math.nan})

class MoneyTests(unittest.TestCase):
    def test_strict_numbers(self):
        for bad in (True,-1,math.nan,math.inf,'1',None):
            with self.assertRaises(BudgetError):money(bad)
        self.assertEqual(money(0.0000001),1)  # rounds up, never under-reserves
    def test_usage_cost_and_unknown_fields(self):
        c=usage_cost(dict(input_tokens=1_000_000,output_tokens=1_000_000),PRICE);self.assertAlmostEqual(c,12.0)
        self.assertAlmostEqual(usage_cost(dict(input_tokens=1_000_000,output_tokens=1_000_000),PRICE,batch=True),6.0)
        with self.assertRaises(BudgetError):usage_cost(dict(input_tokens=-1),PRICE)
        with self.assertRaises(BudgetError):usage_cost(dict(input_tokens=True),PRICE)
    def test_image_tokens_formula(self):
        self.assertEqual(image_tokens(1000,1000),1296);self.assertEqual(image_tokens(28,28),1)
        with self.assertRaises(ValueError):image_tokens(0,10)

class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.d=tempfile.TemporaryDirectory(ignore_cleanup_errors=True);self.addCleanup(self.d.cleanup);self.path=Path(self.d.name)/'ledger é.sqlite'
    def test_cap_is_locked_and_raise_needs_reason(self):
        b=Budget(self.path,2)
        with self.assertRaises(BudgetError):Budget(self.path,100)   # tamper attempt
        self.assertEqual(Budget(self.path).cap,2_000_000)
        with self.assertRaises(BudgetError):b.raise_cap(5,'short')
        b.raise_cap(5,'approved by the user for the holdout run');self.assertEqual(Budget(self.path).cap,5_000_000)
    def test_default_cap_is_25(self):self.assertEqual(Budget(self.path).cap,25_000_000)
    def test_overrun_is_recorded_not_hidden(self):
        b=Budget(self.path,1);n=b.reserve('t',.1)
        self.assertEqual(b.settle(n,.3),'overrun')
        self.assertAlmostEqual(b.summary()['spent'],.3);self.assertEqual(b.summary()['overruns'],1)
        with self.assertRaises(BudgetError):b.reserve('u',.8)   # later reservations see the true spend
    def test_boundary_and_exact_cap(self):
        b=Budget(self.path,1);b.reserve('a',1.0)
        with self.assertRaises(BudgetError):b.reserve('b',0.000001)
    def test_cancel_unsent_frees_budget_and_attempt(self):
        b=Budget(self.path,1);n=b.reserve('a',.9);b.cancel_unsent(n);b.reserve('b',.9);self.assertEqual(b.attempts('a'),0)
    def test_unknown_or_double_settle(self):
        b=Budget(self.path,1);n=b.reserve('a',.1);b.settle(n,0)
        with self.assertRaises(BudgetError):b.settle(n,0)
        with self.assertRaises(BudgetError):b.settle(999,0)

class AnthropicTests(unittest.TestCase):
    def setUp(self):
        self.d=tempfile.TemporaryDirectory(ignore_cleanup_errors=True);self.addCleanup(self.d.cleanup);self.dir=Path(self.d.name)
        self.ledger=Budget(self.dir/'l.sqlite',25)
    def call(self,p,content='hello',**kw):
        return p.call('sys',content,SCHEMA,1000,self.ledger,self.dir/'raw',**kw)
    def test_success_settles_exact_cost_and_saves_raw_first(self):
        p=provider();out=self.call(p)
        self.assertEqual(out['parsed'],{'facts':[]});self.assertAlmostEqual(out['cost'],(1000*2+500*10)/1e6)
        self.assertAlmostEqual(self.ledger.summary()['spent'],out['cost']);self.assertTrue(Path(out['raw_path']).is_file())
    def test_budget_below_next_reservation_sends_zero_requests(self):
        led=Budget(self.dir/'tiny.sqlite',0.0001);p=provider()
        with self.assertRaises(BudgetError):p.call('sys','hello',SCHEMA,1000,led,self.dir/'raw')
        self.assertEqual(p.client.messages.sent,0)
    def test_fourth_attempt_of_same_content_refused_even_if_label_changes(self):
        p=provider(error=StatusError(400))
        for i in range(3):
            with self.assertRaises(StatusError):self.call(p,label=f'name-{i}')
        sent=p.client.messages.sent
        with self.assertRaises(BudgetError):self.call(p,label='brand-new-name')
        self.assertEqual(p.client.messages.sent,sent)
    def test_http_4xx_is_unbilled_but_counts_as_attempt(self):
        p=provider(error=StatusError(429))
        with self.assertRaises(StatusError):self.call(p)
        self.assertEqual(self.ledger.summary()['spent'],0);self.assertEqual(self.ledger.summary()['reserved_unsettled'],0)
    def test_connection_error_keeps_full_reservation(self):
        p=provider(error=ConnectionError('boom'))
        with self.assertRaises(ConnectionError):self.call(p)
        s=self.ledger.summary();self.assertGreater(s['reserved_unsettled'],0);self.assertEqual(s['ambiguous'],1)
    def test_5xx_keeps_reservation(self):
        p=provider(error=StatusError(503))
        with self.assertRaises(StatusError):self.call(p)
        self.assertEqual(self.ledger.summary()['ambiguous'],1)
    def test_missing_usage_keeps_reservation_charge(self):
        p=provider(response=FakeResponse(usage=NS()));r=FakeResponse();r.usage=None;p.client.messages.response=r
        out=self.call(p);self.assertIsNone(out['cost']);self.assertGreater(self.ledger.summary()['spent'],0)
    def test_refusal_truncation_malformed_and_model_mismatch(self):
        cases=[(FakeResponse(stop='refusal'),RefusalError),(FakeResponse(stop='max_tokens'),TruncatedError),
               (FakeResponse(text='{"facts": [} trailing'),MalformedOutputError),(FakeResponse(text='{"a":1,"a":2}'),MalformedOutputError),
               (FakeResponse(model='claude-other'),ValueError),(FakeResponse(stop='pause_turn'),ValueError)]
        for n,(resp,exc) in enumerate(cases):
            p=provider(response=resp)
            with self.assertRaises(exc):self.call(p,content=f'case {n}')
        self.assertGreater(self.ledger.summary()['spent'],0)   # every billed response was charged
    def test_raw_write_failure_after_billing_is_charged(self):
        p=provider();(self.dir/'raw').mkdir()
        first=self.call(p)
        blocker=Path(first['raw_path']).with_name(Path(first['raw_path']).name.replace('-1.json','-2.json'))
        blocker.write_text('x')
        before=self.ledger.summary()['spent']
        with self.assertRaises(RawWriteError):self.call(p)
        self.assertGreater(self.ledger.summary()['spent'],before)
    def test_payload_validation(self):
        p=provider()
        for tokens in (0,-5,True,10**9,200000):
            with self.assertRaises((BudgetError,TypeError)):p.payload('s','c',SCHEMA,tokens,'low')
        with self.assertRaises(BudgetError):p.payload('s','c',SCHEMA,100,'ultra')
        with self.assertRaises(ValueError):p.payload('s','c',dict(type='object'),100,'low')
        pl=p.payload('s','c',SCHEMA,100,'low')
        self.assertNotIn('temperature',pl);self.assertNotIn('tool_choice',pl);self.assertNotIn('thinking',pl)
    def test_no_key_no_client_fails_without_printing(self):
        old=os.environ.pop('ANTHROPIC_API_KEY',None)
        try:
            with self.assertRaises(BudgetError) as cm:Anthropic()
            self.assertNotIn('sk-',str(cm.exception))
        finally:
            if old:os.environ['ANTHROPIC_API_KEY']=old
    def test_preflight_rejects_model_substitution(self):
        p=provider();p.client.models=NS(retrieve=lambda m:NS(id='claude-other',capabilities=None))
        with self.assertRaises(ValueError):p.preflight()
    def test_task_key_depends_on_content(self):
        a=task_key('m','s','c1',SCHEMA,10,'low');b=task_key('m','s','c2',SCHEMA,10,'low')
        self.assertNotEqual(a,b);self.assertEqual(a,task_key('m','s','c1',SCHEMA,10,'low'))

if __name__=='__main__':unittest.main()
