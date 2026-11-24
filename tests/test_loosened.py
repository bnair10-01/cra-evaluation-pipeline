"""Behaviour that used to block updating and no longer does."""
import subprocess,sys,os,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace as NS
from cra_acquisition import pipeline
from cra_acquisition.paths import ROOT
from cra_acquisition.provider import Anthropic,Budget,BudgetError
from test_io_provider import FakeMessages,FakeResponse,SCHEMA
from test_tasks_pipeline import Env,bundle,default_handler,Script,COLS

class AttemptTests(unittest.TestCase):
    def test_attempts_are_counted_per_run_so_a_new_run_can_try_again(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            b=Budget(Path(d)/'l.sqlite',150);b.run='run-1'
            for _ in range(3):b.reserve('k',.01)
            with self.assertRaises(BudgetError) as cm:b.reserve('k',.01)
            self.assertIn('new run',str(cm.exception))
            b.run='run-2';b.reserve('k',.01)                      # fresh allowance, same ledger and same cap
            self.assertEqual(Budget(Path(d)/'l.sqlite').summary()['cap'],150.0)
    def test_without_a_run_label_the_old_total_limit_still_applies(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            b=Budget(Path(d)/'l.sqlite');[b.reserve('k',.01) for _ in range(3)]
            with self.assertRaises(BudgetError):b.reserve('k',.01)
    def test_an_existing_ledger_gets_the_run_column_without_losing_rows(self):
        import sqlite3
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            p=Path(d)/'old.sqlite';c=sqlite3.connect(p)
            c.executescript("CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);INSERT INTO settings VALUES('cap_micro','25000000');CREATE TABLE reservations(id INTEGER PRIMARY KEY,task TEXT NOT NULL,maximum INTEGER NOT NULL,actual INTEGER,status TEXT NOT NULL,price_version TEXT,note TEXT);CREATE TABLE cap_changes(id INTEGER PRIMARY KEY,old_cap INTEGER,new_cap INTEGER,reason TEXT NOT NULL);INSERT INTO reservations(task,maximum,actual,status) VALUES('x',5,5,'settled')");c.commit();c.close()
            b=Budget(p);self.assertEqual(b.summary()['spent'],5e-06);b.run='r';b.reserve('x',.01)

class StreamingTests(unittest.TestCase):
    def test_outputs_over_16000_tokens_are_streamed_not_refused(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            m=FakeMessages();seen={}
            class S:
                def __enter__(s):return s
                def __exit__(s,*a):return False
                def get_final_message(s):return FakeResponse()
            m.stream=lambda **kw:(seen.update(kw) or S());prov=Anthropic(client=NS(messages=m,models=None))
            out=prov.call('s','hello',SCHEMA,32000,Budget(Path(d)/'l.sqlite',150),Path(d)/'raw')
            self.assertEqual(out['parsed'],{'facts':[]});self.assertEqual(seen['max_tokens'],32000);self.assertEqual(m.sent,0)   # create() was not used

class CacheMissTests(Env):
    def test_a_missing_cache_entry_skips_that_task_and_the_document_still_finishes(self):
        pipeline_ok=Script(default_handler);self.run_doc(pipeline_ok)             # fills the cache
        for f in list(self.dirs['cache'].glob('*.json'))[:1]:f.unlink()            # lose one stored response
        r=pipeline.run_document(self.rec,bundle(),pipeline.CacheOnlyProvider('m'),self.ledger,self.dirs,COLS,self.db,'RUN2')
        self.assertEqual(r['status'],'incomplete');self.assertEqual(len(r['stats']['failures']),1);self.assertIn('not in the cache',r['stats']['failures'][0]['reason'])
        self.assertEqual(self.db.execute('select count(*) from table_a_exam_level').fetchone()[0],1)    # the other tasks' data was still staged
    def test_a_stored_refusal_is_reused_until_retry_failed_is_given(self):
        self.run_doc(Script(default_handler))                                       # fills the cache
        from cra_acquisition.io import read_json,write_json
        target=next(f for f in self.dirs['cache'].glob('*.json') if 'facts' in read_json(f).get('parsed',{}) and not read_json(f)['parsed']['facts'])   # an empty-result task
        write_json(target,dict(failed='RefusalError',detail='refused earlier'))
        calls=Script(default_handler);r=self.run_doc(calls)
        self.assertEqual(len(calls.calls),0);self.assertEqual(r['status'],'incomplete')              # reused, not re-asked
        calls=Script(default_handler);r=self.run_doc(calls,retry_failed=True)
        self.assertEqual(len(calls.calls),1);self.assertEqual(r['status'],'staged')                  # asked once more, and it worked

class CliTests(unittest.TestCase):
    def cli(self,*a):
        e={k:v for k,v in os.environ.items() if k!='ANTHROPIC_API_KEY'};return subprocess.run([sys.executable,'-m','cra_acquisition.cli',*a],capture_output=True,text=True,env=e,cwd=ROOT)
    def test_holdout_without_a_freeze_is_only_a_note_but_clean_test_still_demands_one(self):
        r=self.cli('extract','--group','holdout','--run-id','x');self.assertIn('--yes-spend',r.stderr+r.stdout)        # reaches the spend guard, not a freeze refusal
        r=self.cli('extract','--group','holdout','--run-id','x','--yes-spend','--clean-test');self.assertIn('--clean-test needs --freeze',r.stderr+r.stdout)

class FreezeAndOutputTests(unittest.TestCase):
    def test_a_code_change_does_not_break_a_freeze_but_a_prompt_or_effort_change_does(self):
        from cra_acquisition import review
        class P:model='m';price_version='1'
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            f=Path(d)/'f.json';review.freeze(f,P(),'low','t',ROOT)
            real=review.freeze_state
            def other_code(*a,**k):
                s=real(*a,**k);s['code']='different';s['field_inventory']='x';s['research_schema']='y';return s       # merge/validation code, inventory, schema file changed
            review.freeze_state=other_code
            try:review.verify_freeze(f,P(),'low',ROOT)                                                            # still fine
            finally:review.freeze_state=real
            with self.assertRaises(ValueError) as cm:review.verify_freeze(f,P(),'high',ROOT)
            self.assertIn('effort',str(cm.exception))
    def test_outputs_get_a_new_name_instead_of_a_refusal(self):
        from cra_acquisition.io import write_json_new,read_json
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            p=Path(d)/'out.json';a=write_json_new(p,{'v':1});b=write_json_new(p,{'v':2});c=write_json_new(p,{'v':3})
            self.assertEqual(a,p);self.assertEqual(len({a,b,c}),3);self.assertEqual([read_json(x)['v'] for x in (a,b,c)],[1,2,3])
    def test_names_and_sizes_come_from_the_project_config(self):
        from cra_acquisition.paths import project_config
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            (Path(d)/'config').mkdir();(Path(d)/'config/project.json').write_text('{"expected_documents": 60}')
            c=project_config(d);self.assertEqual((c['expected_documents'],c['scan_quota']),(60,4))   # override one value, keep the other defaults
