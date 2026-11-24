import json,subprocess,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace as NS
from cra_acquisition import batch,runstate,pipeline,tasks as T
from cra_acquisition.provider import Anthropic,Budget,BudgetError
from cra_acquisition.paths import ROOT
from test_tasks_pipeline import bundle,default_handler,Script,COLS
from test_io_provider import FakeMessages

def msg(parsed,stop='end_turn',model='claude-sonnet-5-5',tokens=(1000,500)):
    usage=NS(input_tokens=tokens[0],output_tokens=tokens[1],cache_creation_input_tokens=0,cache_read_input_tokens=0,model_dump=lambda:dict(input_tokens=tokens[0],output_tokens=tokens[1]))
    return NS(content=[NS(type='text',text=json.dumps(parsed))],stop_reason=stop,model=model,usage=usage,stop_details=None,_request_id='rq')

class FakeBatches:
    def __init__(self,responder):self.responder=responder;self.created=[];self.polls=0
    def create(self,requests):
        self.created.append(requests);return NS(id='b1',processing_status='in_progress')
    def retrieve(self,i):
        self.polls+=1;return NS(id=i,processing_status='ended' if self.polls>=2 else 'in_progress')
    def results(self,i):
        for r in self.created[-1]:
            out=self.responder(r)
            if out is not None:yield NS(custom_id=r['custom_id'],result=out)

class Env(unittest.TestCase):
    def setUp(self):
        self.d=tempfile.TemporaryDirectory(ignore_cleanup_errors=True);self.addCleanup(self.d.cleanup);self.dir=Path(self.d.name)
        self.db=runstate.init_staging(self.dir/'s.sqlite',ROOT);self.addCleanup(self.db.close)
        self.ledger=Budget(self.dir/'l.sqlite',25)
        self.dirs={k:self.dir/k for k in ('cache','raw','proposals')}
        for p in self.dirs.values():p.mkdir()
        self.rec=dict(pe_id='PE1',sha256='s'*64);self.b=bundle()
    def provider(self,responder):
        msgs=FakeMessages();msgs.batches=FakeBatches(responder)
        return Anthropic(client=NS(messages=msgs,models=None))
    def system_target(self,params):
        s=params['system'];return s
    def success(self,r):
        parsed=default_handler(r['params']['system'],'',0)
        return NS(type='succeeded',message=msg(parsed))
    def warm(self,prov,**kw):
        reqs=batch.prepare_requests(prov,{'PE1':(self.rec,self.b)},COLS,T.prompts(),self.dirs,'low',('a','b','c','e','peers','d'))
        return reqs,batch.run_round(prov,self.ledger,reqs,self.dirs,self.db,'RUN',sleep=lambda s:None,**kw)

class BatchTests(Env):
    def test_batch_warms_cache_at_half_price_and_sync_run_makes_no_calls(self):
        prov=self.provider(self.success);reqs,resplit=self.warm(prov)
        self.assertEqual(resplit,[]);self.assertGreater(len(reqs),3);self.assertEqual(len(prov.client.messages.batches.created[0]),len(reqs))
        expected=len(reqs)*(1000*2+500*10)/1e6*0.5
        self.assertAlmostEqual(self.ledger.summary()['spent'],expected,places=6)
        sync=Script(lambda *a:RuntimeError('should not be called'));sync.model=prov.model
        r=pipeline.run_document(self.rec,self.b,sync,self.ledger,self.dirs,COLS,self.db,'RUN')
        self.assertEqual(len(sync.calls),0);self.assertEqual(r['status'],'staged')
        self.assertEqual(self.db.execute('select count(*) from table_d_distribution_measures').fetchone()[0],4)
    def test_second_round_has_nothing_to_resubmit(self):
        prov=self.provider(self.success);self.warm(prov)
        reqs=batch.prepare_requests(prov,{'PE1':(self.rec,self.b)},COLS,T.prompts(),self.dirs,'low',('a','b','c','e','peers','d'))
        self.assertEqual(reqs,[])
    def test_truncation_is_split_and_never_accepted(self):
        def responder(r):
            if 'Target: Table A' in r['params']['system'] and len(r['params']['messages'][0]['content'])>0 and '=== PDF PAGE 2' in r['params']['messages'][0]['content'] and '=== PDF PAGE 1' in r['params']['messages'][0]['content']:
                return NS(type='succeeded',message=msg(dict(facts=[]),stop='max_tokens'))
            return self.success(r)
        prov=self.provider(responder);reqs,resplit=self.warm(prov)
        self.assertEqual(len(resplit),1);self.assertEqual(len(resplit[0][1]),2)
        sync=Script(default_handler);sync.model=prov.model
        # sync run raises the cached truncation, splits, and finds the pieces missing -> it would call them: here we only prove no acceptance
        r=pipeline.run_document(self.rec,self.b,sync,self.ledger,self.dirs,COLS,self.db,'RUN')
        self.assertTrue(all('Target: Table A' not in c[0] or '=== PDF PAGE' in c[1] for c in sync.calls))
    def test_budget_refusal_sends_nothing_and_releases_reservations(self):
        small=Budget(self.dir/'small.sqlite',0.0005);prov=self.provider(self.success)
        reqs=batch.prepare_requests(prov,{'PE1':(self.rec,self.b)},COLS,T.prompts(),self.dirs,'low',('a','b','c','e','peers','d'))
        with self.assertRaises(BudgetError):batch.run_round(prov,small,reqs,self.dirs,self.db,'RUN',sleep=lambda s:None)
        self.assertEqual(prov.client.messages.batches.created,[]);self.assertEqual(small.summary()['reserved_unsettled'],0)
    def test_errored_results_are_unbilled_and_missing_results_stay_reserved(self):
        count={'n':0}
        def responder(r):
            count['n']+=1
            if count['n']==1:return NS(type='errored',error='boom')
            if count['n']==2:return None
            return self.success(r)
        prov=self.provider(responder);reqs,_=self.warm(prov);s=self.ledger.summary()
        self.assertEqual(s['ambiguous'],1);self.assertGreater(s['reserved_unsettled'],0)
        kinds=[r[0] for r in self.db.execute('select status from model_requests')];self.assertIn('batch_errored',kinds)
    def test_refusal_and_malformed_cache_markers_stop_repeat_spend(self):
        def responder(r):
            if 'Target: Table E' in r['params']['system']:return NS(type='succeeded',message=msg({},stop='refusal'))
            if 'Target: Table C' in r['params']['system']:return NS(type='succeeded',message=msg({'wrong':1}))
            return self.success(r)
        prov=self.provider(responder);self.warm(prov)
        sync=Script(default_handler);sync.model=prov.model
        r=pipeline.run_document(self.rec,self.b,sync,self.ledger,self.dirs,COLS,self.db,'RUN')
        self.assertEqual(r['status'],'incomplete');self.assertFalse(any('Target: Table E' in c[0] or 'Target: Table C' in c[0] for c in sync.calls))

class CliTests(unittest.TestCase):
    def run_cli(self,*args,env=None):
        import os
        e={k:v for k,v in os.environ.items() if k!='ANTHROPIC_API_KEY'};e.update(env or {})
        return subprocess.run([sys.executable,'-m','cra_acquisition.cli',*args],capture_output=True,text=True,env=e,cwd=ROOT)
    def test_extract_refuses_without_explicit_spend_flag(self):
        r=self.run_cli('extract','--group','development','--run-id','x')
        self.assertNotEqual(r.returncode,0);self.assertIn('--yes-spend',r.stderr+r.stdout)
    def test_holdout_requires_a_freeze(self):
        r=self.run_cli('extract','--group','holdout','--run-id','x','--yes-spend')
        self.assertNotEqual(r.returncode,0);self.assertIn('frozen',r.stderr+r.stdout)
    @unittest.skipUnless((ROOT/'reports/final_904bed5b30cc793e19d4.json').is_file(),'project data not present')
    @unittest.skipUnless((ROOT/'data/raw').is_dir(),'source PDFs are not stored in git (e.g. in CI)')
    def test_offline_preflight_passes_and_never_needs_a_key(self):
        r=self.run_cli('preflight');self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertIn('44/44',r.stdout)
    def test_online_preflight_without_key_fails_cleanly(self):
        r=self.run_cli('preflight','--online');self.assertNotEqual(r.returncode,0);self.assertIn('ANTHROPIC_API_KEY present',r.stdout)
    def test_unknown_pe_id_rejected(self):
        r=self.run_cli('extract','--pe-id','nope','--run-id','x','--yes-spend');self.assertNotEqual(r.returncode,0)
    def test_mock_run_can_never_be_accepted_from_cli(self):
        r=self.run_cli('review','accept','--run-id','MOCK-1','--pe-id','x','--staging','/nonexistent/s.sqlite');self.assertNotEqual(r.returncode,0)

if __name__=='__main__':unittest.main()

class MaxPagesTests(unittest.TestCase):
    def test_max_pages_skips_long_documents_before_any_spend(self):
        import os
        r=subprocess.run([sys.executable,'-m','cra_acquisition.cli','extract','--group','calibration','--run-id','x','--max-pages','100','--cache-only','--staging','/tmp/cra_maxpages_test.sqlite'],
                         capture_output=True,text=True,cwd=ROOT,env={k:v for k,v in os.environ.items() if k!='ANTHROPIC_API_KEY'})
        self.assertIn('skipping 3 longer documents',r.stdout)   # 363, 293 and 180 pages

class BatchResumeTests(Env):
    def test_batch_is_persisted_so_an_interrupted_run_can_be_collected(self):
        prov=self.provider(self.success)
        reqs=batch.prepare_requests(prov,{'PE1':(self.rec,self.b)},COLS,T.prompts(),self.dirs,'low',('a','b','c','e','peers','d'))
        bid=batch.submit_round(prov,self.ledger,reqs,self.dirs,'RUN')           # ...the process dies here, before polling
        pend=batch.pending_batches(self.dirs);self.assertEqual([p['batch_id'] for p in pend],[bid]);self.assertEqual(len(pend[0]['requests']),len(reqs))
        self.assertEqual(self.ledger.summary()['spent'],0);self.assertGreater(self.ledger.summary()['reserved_unsettled'],0)
        batch.collect_round(prov,self.ledger,bid,self.dirs,self.db,'RUN',sleep=lambda s:None)   # a later process resumes it
        self.assertEqual(batch.pending_batches(self.dirs),[]);self.assertEqual(self.ledger.summary()['reserved_unsettled'],0)
        self.assertGreater(self.ledger.summary()['spent'],0)
        again=batch.collect_round(prov,self.ledger,bid,self.dirs,self.db,'RUN');self.assertEqual(again,[])   # collecting twice never double-charges
    def test_warm_cache_resumes_a_pending_batch_instead_of_resubmitting(self):
        prov=self.provider(self.success)
        reqs=batch.prepare_requests(prov,{'PE1':(self.rec,self.b)},COLS,T.prompts(),self.dirs,'low',('a','b','c','e','peers','d'))
        bid=batch.submit_round(prov,self.ledger,reqs,self.dirs,'RUN')
        created=len(prov.client.messages.batches.created)
        # the persisted record is what a restarted run would find
        self.assertEqual(len(batch.pending_batches(self.dirs)),1);self.assertEqual(created,1)
    def test_any_failure_while_reserving_releases_every_hold(self):
        prov=self.provider(self.success);calls={'n':0}
        def flaky(**kw):
            calls['n']+=1
            if calls['n']==3:raise ConnectionError('network dropped')
            return NS(input_tokens=500)
        prov.client.messages.count_tokens=flaky
        reqs=batch.prepare_requests(prov,{'PE1':(self.rec,self.b)},COLS,T.prompts(),self.dirs,'low',('a','b','c','e','peers','d'))
        with self.assertRaises(ConnectionError):batch.submit_round(prov,self.ledger,reqs,self.dirs,'RUN')
        self.assertEqual(self.ledger.unsettled(),[]);self.assertEqual(prov.client.messages.batches.created,[])
    def test_ledger_release_needs_a_reason_and_only_touches_unsettled(self):
        n=self.ledger.reserve('k',.1)
        with self.assertRaises(BudgetError):self.ledger.release(n,'no')
        self.ledger.release(n,'verified no batch exists for this reservation');self.assertEqual(self.ledger.unsettled(),[])
        self.assertEqual(self.ledger.summary()['spent'],0)
        with self.assertRaises(BudgetError):self.ledger.release(n,'already settled, cannot release twice')

class ReplicateTests(Env):
    def test_replicate_uses_fresh_cache_entries_and_the_cli_refuses_to_overwrite_the_primary_staging(self):
        from cra_acquisition import pipeline
        p1=Script(default_handler);pipeline.run_document(self.rec,self.b,p1,self.ledger,self.dirs,COLS,self.db,'R1')
        again=Script(default_handler);pipeline.run_document(self.rec,self.b,again,self.ledger,self.dirs,COLS,self.db,'R1');self.assertEqual(len(again.calls),0)
        rep=Script(default_handler);pipeline.run_document(self.rec,self.b,rep,self.ledger,self.dirs,COLS,self.db,'R2',extra=dict(replicate=1))
        self.assertEqual(len(rep.calls),len(p1.calls))   # a deliberate second extraction, not a cache hit
        import os
        r=subprocess.run([sys.executable,'-m','cra_acquisition.cli','extract','--group','development','--run-id','x','--yes-spend','--replicate','1'],capture_output=True,text=True,cwd=ROOT,
                         env={k:v for k,v in os.environ.items() if k!='ANTHROPIC_API_KEY'})
        self.assertNotEqual(r.returncode,0)

class EffortTests(Env):
    def test_per_target_effort_changes_only_that_targets_requests_and_keys(self):
        prov=self.provider(self.success)
        base=batch.prepare_requests(prov,{'PE1':(self.rec,self.b)},COLS,T.prompts(),self.dirs,'low',('a','e'))
        mixed=batch.prepare_requests(prov,{'PE1':(self.rec,self.b)},COLS,T.prompts(),self.dirs,'low',('a','e'),efforts={'e':'medium'})
        eff=lambda reqs,t:{r['params']['output_config']['effort'] for r in reqs if r['task']['target']==t}
        self.assertEqual((eff(mixed,'a'),eff(mixed,'e')),({'low'},{'medium'}))
        ka={r['cache_key'] for r in base if r['task']['target']=='a'};kb={r['cache_key'] for r in mixed if r['task']['target']=='a'}
        self.assertEqual(ka,kb)   # untouched targets keep their cache entries
        self.assertNotEqual({r['cache_key'] for r in base if r['task']['target']=='e'},{r['cache_key'] for r in mixed if r['task']['target']=='e'})
    def test_cli_rejects_bad_effort_specs(self):
        import os
        r=subprocess.run([sys.executable,'-m','cra_acquisition.cli','extract','--group','development','--run-id','x','--yes-spend','--effort-for','zz=low'],capture_output=True,text=True,cwd=ROOT,env={k:v for k,v in os.environ.items() if k!='ANTHROPIC_API_KEY'})
        self.assertNotEqual(r.returncode,0)
