import json
from types import SimpleNamespace as NS
from openpyxl import load_workbook
from cra_acquisition import audit,visioncheck,runstate
from cra_acquisition.paths import ROOT
from cra_acquisition.provider import Anthropic
from test_io_provider import FakeMessages,FakeResponse
from test_tasks_pipeline import bundle,default_handler,Script
from test_tasks_pipeline import Env as PipeEnv

class AuditTests(PipeEnv):
    def staged(self):
        self.run_doc(Script(default_handler));return self.dir/'s.sqlite'
    def manifest(self):return dict(documents=[dict(pe_id='PE1',institution_name='Example Bank',exam_date='2015-08-12',path='x.pdf',sha256='s'*64,agency='FDIC',pages=3)])
    def test_sample_is_stratified_reproducible_and_scores_with_intervals(self):
        db=self.staged();self.db.commit()
        a=audit.build_precision_sheet(db,self.manifest(),self.dir/'o',quotas={'table_a_exam_level':3,'table_d_distribution_measures':3,'table_e_examiner_conclusions':1},seed=1,root=self.dir)
        b=audit.build_precision_sheet(db,self.manifest(),self.dir/'o2',quotas={'table_a_exam_level':3,'table_d_distribution_measures':3,'table_e_examiner_conclusions':1},seed=1,root=self.dir)
        ra=[r[0:6] for r in load_workbook(a)['Audit'].iter_rows(min_row=2,values_only=True)];rb=[r[0:6] for r in load_workbook(b)['Audit'].iter_rows(min_row=2,values_only=True)]
        self.assertEqual(ra,rb);self.assertEqual(len(ra),7)
        wb=load_workbook(a);ws=wb['Audit']
        for i in range(2,ws.max_row+1):ws.cell(i,12).value='Y' if i<6 else ('P' if i==6 else 'N')
        wb.save(a);r=audit.score_precision(a)
        tot=sum(t['n'] for t in r['per_table'].values());self.assertEqual(tot,7);self.assertEqual(sum(t['correct'] for t in r['per_table'].values()),4)
        self.assertEqual(len(r['wrong']),2);self.assertIn('overall_strict_precision',r);self.assertLessEqual(r['overall_ci95_approx'][0],r['overall_strict_precision'])
        self.assertIn('not measure values the pipeline missed',r['note'])
    def test_unanswered_rows_are_not_counted_and_bad_verdicts_ignored(self):
        db=self.staged();self.db.commit()
        a=audit.build_precision_sheet(db,self.manifest(),self.dir/'o',quotas={'table_a_exam_level':4},seed=2,root=self.dir)
        wb=load_workbook(a);ws=wb['Audit'];ws.cell(2,12).value='y';ws.cell(3,12).value='maybe';wb.save(a)
        r=audit.score_precision(a);self.assertEqual(r['answered'],1)
    def test_formula_looking_text_is_never_stored_as_a_formula(self):
        db=self.staged();self.db.execute("UPDATE table_a_exam_level SET hmda_status_text='=1+1'");self.db.commit()
        self.db.execute("INSERT INTO field_evidence VALUES ('x','PE1','table_a_exam_level','PE1','hmda_status_text',1,NULL,'=1+1',NULL)");self.db.commit()
        a=audit.build_precision_sheet(db,self.manifest(),self.dir/'o',quotas={'table_a_exam_level':99},seed=3,root=self.dir)
        wb=load_workbook(a);self.assertEqual([c.data_type for row in wb['Audit'].iter_rows(min_row=2) for c in row if c.value=='=1+1'],['s']*2)

class VisionTests(PipeEnv):
    def test_vision_results_are_stored_as_advice_and_never_clear_a_flag_or_attest(self):
        b=bundle()
        for p in b['pages']:p['page_class']='ocr_layer'
        self.run_doc(Script(default_handler),b);before=len(runstate.open_flags(self.db,'RUN','PE1'));self.assertGreater(before,0)
        self.db.commit()
        def create(**kw):
            n=sum(1 for t in kw['messages'][0]['content'][-1]['text'].split('\n') if t[:1].isdigit())
            return FakeResponse(text=json.dumps(dict(results=[dict(id=i,verdict='supported' if i%2 else 'not_found',seen_text='x') for i in range(1,n+1)])))
        m=FakeMessages();m.create=create;prov=Anthropic(client=NS(messages=m,models=None))
        man=dict(documents=[dict(pe_id='PE1',path='a.pdf',sha256='s'*64,institution_name='B',agency='FDIC',pages=3)])
        from pdfs import make_pdf,TEXT
        make_pdf(self.dir/'a.pdf',[dict(lines=TEXT)]*3)
        tally=visioncheck.run(self.dir/'s.sqlite',man,prov,self.ledger,self.dir/'v',root=self.dir)
        self.assertGreater(tally['supported']+tally['not_found'],0)
        db=runstate.connect(self.dir/'s.sqlite');self.assertEqual(len(runstate.open_flags(db,'RUN','PE1')),before)    # flags unchanged
        from cra_acquisition import reviewstore;st=reviewstore.open_store(ROOT)
        self.assertEqual(st.db.execute('select count(*) from attestations').fetchone()[0],0)                         # nothing attested
        self.assertGreater(st.db.execute('select count(*) from vision_checks').fetchone()[0],0)                      # advice is kept in the durable store
        calls=m.n if hasattr(m,'n') else None
        tally2=visioncheck.run(self.dir/'s.sqlite',man,prov,self.ledger,self.dir/'v',root=self.dir);self.assertEqual(tally,tally2)   # resumes from cache
    def test_scan_worksheet_and_attest_from_sheet(self):
        b=bundle()
        for p in b['pages']:p['page_class']='ocr_layer'
        self.run_doc(Script(default_handler),b);self.db.commit()
        from pdfs import make_pdf,TEXT
        make_pdf(self.dir/'a.pdf',[dict(lines=TEXT)]*3)
        man=dict(documents=[dict(pe_id='PE1',path='a.pdf',sha256='s'*64,institution_name='Example Bank',agency='FDIC',pages=3)])
        r=audit.build_scan_worksheet(self.dir/'s.sqlite',man,self.dir/'scans',root=self.dir);self.assertGreater(r['pages'],0)
        csvp=self.dir/'scans'/'pages_to_attest.csv';text=csvp.read_text().splitlines();hdr,rows=text[0],text[1:]
        rows[0]=rows[0].rstrip(',')+',Y' if rows[0].endswith(',') is False else rows[0]+'Y';csvp.write_text('\n'.join([hdr]+rows))
        with runstate.connect(self.dir/'s.sqlite') as db:
            n=audit.attest_from_sheet(db,man,csvp,'R. Reviewer');self.assertEqual(n,1)
            from cra_acquisition import reviewstore;self.assertEqual(reviewstore.open_store(ROOT).db.execute('select count(*) from attestations').fetchone()[0],1)
