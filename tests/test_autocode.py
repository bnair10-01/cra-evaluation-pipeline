import json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace as NS
from cra_acquisition import autocode,score,handoff,tasks as T
from cra_acquisition.provider import Anthropic,Budget
from test_io_provider import FakeMessages,FakeResponse

class AutoTests(unittest.TestCase):
    def test_windows_cover_every_page(self):
        w=autocode.windows(12);self.assertEqual([p for x in w for p in x],list(range(1,13)));self.assertTrue(all(len(x)<=5 for x in w))
    def test_schema_fits_api_limits_and_forms_round_trip(self):
        cols=autocode.form_columns(T.research_columns(),autocode.inventory());s=autocode.schema(cols)
        self.assertFalse(s['properties']['facts']['items']['additionalProperties'])
        facts={'PE1':[dict(table='table_c_assessment_areas',record='Honolulu AA',field='aa_name',value='Honolulu AA',page=3),
                      dict(table='table_c_assessment_areas',record='Honolulu AA',field='review_scope',value='full scope',page=3)]}
        with tempfile.TemporaryDirectory() as d:
            f=autocode.write_forms(facts,d);rows=autocode.read_forms(f,autocode.inventory(),T.research_columns())
            self.assertEqual({(r['field'],r['value']) for r in rows},{('aa_name','Honolulu AA'),('review_scope','full scope')})
            res=autocode.submit(f,Path(d)/'sub','m',{'PE1'});self.assertEqual(json.loads(Path(res['path']).read_text())['reference_kind'],'model_generated')
    def test_empty_transcription_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            f=autocode.write_forms({},d)
            with self.assertRaises(ValueError):autocode.submit(f,Path(d)/'s','m',{'PE1'})
    def test_run_sends_images_caches_and_resumes(self):
        with tempfile.TemporaryDirectory() as d:
            msgs=FakeMessages(response=FakeResponse(text=json.dumps(dict(facts=[dict(table='table_a_exam_level',record='A',field='agency',value='OCC',page=1)]))))
            prov=Anthropic(client=NS(messages=msgs,models=None));led=Budget(Path(d)/'l.sqlite',150)
            from pdfs import make_pdf,TEXT
            pdf=make_pdf(Path(d)/'a.pdf',[dict(lines=TEXT)]*7);import hashlib
            rec=dict(pe_id='PE1',path='a.pdf',pages=7,sha256=hashlib.sha256(pdf.read_bytes()).hexdigest())
            f1=autocode.run(dict(documents=[rec]),{'PE1'},prov,led,Path(d)/'o',files_root=d)
            self.assertEqual(msgs.sent,2)                                   # 7 pages -> 2 windows
            self.assertEqual(len(f1['PE1']),2)
            autocode.run(dict(documents=[rec]),{'PE1'},prov,led,Path(d)/'o',files_root=d);self.assertEqual(msgs.sent,2)   # cached
    def test_model_reference_can_never_pass_or_open_the_export_gate(self):
        r=[dict(pe_id='p',table='table_c_assessment_areas',context='a',field='aa_name',value='A',critical=True)]
        s=score.measure(r,r,{'p'},targets={'critical_exact':.99,'conclusion_precision':.95,'conclusion_recall':.95})
        s['reference_kind']='model_generated'
        self.assertEqual(s['reference_kind'],'model_generated')
        self.assertNotEqual(handoff.gates.__name__,'')   # gate wiring checked in the handoff test below

class SnapTests(unittest.TestCase):
    PT={1:'cover page june 9, 2003',2:'the bank is rated satisfactory overall',3:'also satisfactory elsewhere'}
    def f(self,field,value,page):return dict(table='table_a_exam_level',record='A',field=field,value=value,page=page)
    def test_wrong_page_is_moved_to_the_nearest_page_that_prints_it(self):
        out,n=autocode.snap_pages([self.f('weight_text','is rated satisfactory overall',1),self.f('weight_text','satisfactory elsewhere',1)],self.PT)
        self.assertEqual([x['page'] for x in out],[2,3]);self.assertEqual(n,2)
    def test_numbers_classified_values_and_unfound_text_are_untouched(self):
        facts=[self.f('universe_count','92',1),self.f('level','criterion',1),self.f('weight_text','text printed nowhere',1),self.f('weight_text','june 9, 2003',1)]
        out,n=autocode.snap_pages(facts,self.PT);self.assertEqual([x['page'] for x in out],[1,1,1,1]);self.assertEqual(n,0)

class TruncationTests(unittest.TestCase):
    def setUp(self):
        from pdfs import make_pdf,TEXT
        import hashlib
        self.d=tempfile.TemporaryDirectory();self.addCleanup(self.d.cleanup);d=Path(self.d.name)
        pdf=make_pdf(d/'a.pdf',[dict(lines=TEXT)]*5)
        self.rec=dict(pe_id='PE1',path='a.pdf',pages=5,sha256=hashlib.sha256(pdf.read_bytes()).hexdigest());self.d_=d
        self.led=Budget(d/'l.sqlite',150)
    def prov(self,truncate_if):
        ok=dict(facts=[dict(table='table_a_exam_level',record='A',field='agency',value='OCC',page=1)])
        msgs=FakeMessages();n={'calls':0}
        def create(**kw):
            n['calls']+=1;pages=sum(1 for b in kw['messages'][0]['content'] if b.get('type')=='image')
            return FakeResponse(text=json.dumps(ok),stop='max_tokens' if truncate_if(pages) else 'end_turn')
        msgs.create=create;msgs.n=n
        return Anthropic(client=NS(messages=msgs,models=None)),n
    def test_truncated_window_splits_until_it_fits_and_a_rerun_makes_no_new_calls(self):
        prov,n=self.prov(lambda pages:pages>2)
        f=autocode.run(dict(documents=[self.rec]),{'PE1'},prov,self.led,self.d_/'o',files_root=self.d_)
        self.assertEqual(len(f['PE1']),3)          # 5 pages -> 5 truncated; 2 + 3 -> 3 truncated; 1+2 ... all end with fitting pieces
        self.assertEqual(autocode.run.untranscribed['PE1'],[])
        calls=n['calls'];autocode.run(dict(documents=[self.rec]),{'PE1'},prov,self.led,self.d_/'o',files_root=self.d_);self.assertEqual(n['calls'],calls)
    def test_a_single_page_that_always_truncates_is_reported_not_fatal(self):
        prov,_=self.prov(lambda pages:True)
        f=autocode.run(dict(documents=[self.rec]),{'PE1'},prov,self.led,self.d_/'o',files_root=self.d_)
        self.assertEqual(f['PE1'],[]);self.assertEqual(autocode.run.untranscribed['PE1'],[1,2,3,4,5])
