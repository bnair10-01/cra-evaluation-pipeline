import sqlite3,tempfile
from pathlib import Path
from cra_acquisition import review,reviewstore,runstate
from cra_acquisition.paths import ROOT
from test_tasks_pipeline import Env,bundle,default_handler,Script,COLS

class Survival(Env):
    """Human decisions must outlive the extraction database, and must not be applied to something that changed."""
    def flagged(self):
        r=self.run_doc(Script(default_handler));runstate.add_flags(self.db,'RUN','PE1',r['flags']+[dict(kind='percent_sum',table='table_d_distribution_measures',record='PE1:D:p3l2',field='bank_count_pct',detail='sums to 96.6')])
        return self.db.execute("select * from review_flags where kind='percent_sum'").fetchone()
    def rebuild(self,detail='sums to 96.6'):
        """A fresh extraction database with the same flag regenerated."""
        db2=runstate.init_staging(self.dir/'rebuilt.sqlite',ROOT) if not (self.dir/'rebuilt.sqlite').exists() else runstate.connect(self.dir/'rebuilt.sqlite')
        runstate.add_flags(db2,'RUN','PE1',[dict(kind='percent_sum',table='table_d_distribution_measures',record='PE1:D:p3l2',field='bank_count_pct',detail=detail)]);return db2
    def test_a_waived_flag_stays_waived_after_the_database_is_rebuilt(self):
        f=self.flagged();review.resolve_flag(self.db,f['flag_id'],'waived','printed table rounds; checked the PDF',reviewer='B. Nair')
        db2=self.rebuild();self.assertEqual(db2.execute("select status from review_flags").fetchone()[0],'open')       # a rebuild starts open ...
        st=reviewstore.open_store(ROOT);n=review.apply_decisions(db2,st,'RUN','PE1');self.assertEqual(n['applied'],1)  # ... the saved decision is re-applied
        row=db2.execute("select status,resolution from review_flags").fetchone();self.assertEqual(row[0],'waived');self.assertIn('B. Nair',row[1])
    def test_a_decision_is_not_applied_when_the_flagged_thing_changed(self):
        f=self.flagged();review.resolve_flag(self.db,f['flag_id'],'resolved','looked fine at the time',reviewer='B. Nair')
        db2=self.rebuild('sums to 140.2');st=reviewstore.open_store(ROOT);n=review.apply_decisions(db2,st,'RUN','PE1')
        self.assertEqual((n['applied'],n['recheck']),(0,1));row=db2.execute("select status,resolution from review_flags").fetchone()
        self.assertEqual(row[0],'open');self.assertIn('re-check',row[1])
    def test_attestation_survives_and_resolves_the_image_flag_of_a_rebuilt_database(self):
        b=bundle()
        for p in b['pages']:p['page_class']='ocr_layer'
        self.run_doc(Script(default_handler),b);pages={f['pdf_page'] for f in runstate.open_flags(self.db,'RUN','PE1') if f['kind']=='image_review_required'};self.assertTrue(pages)
        review.attest_pages(self.db,'PE1','s'*64,sorted(pages),'B. Nair')
        db2=runstate.init_staging(self.dir/'r2.sqlite',ROOT);r=pipeline_rebuild(self,db2,b)
        self.assertEqual([f for f in runstate.open_flags(db2,'RUN','PE1') if f['kind']=='image_review_required'],[])
    def test_conclusion_keys_follow_the_content_not_the_position(self):
        self.run_doc(Script(default_handler));k1=reviewstore.stable_keys(self.db,'PE1','table_e_examiner_conclusions')
        ids=list(k1);self.assertTrue(ids)
        self.db.execute('PRAGMA foreign_keys=OFF');self.db.execute("UPDATE table_e_examiner_conclusions SET conclusion_id='PE1:E:9999' WHERE conclusion_id=?",(ids[0],))
        self.db.execute("UPDATE field_evidence SET record_id='PE1:E:9999' WHERE record_id=?",(ids[0],));self.db.commit()   # same row, different position/number
        k2=reviewstore.stable_keys(self.db,'PE1','table_e_examiner_conclusions');self.assertEqual(sorted(k1.values()),sorted(k2.values()))
    def test_correction_follows_its_row_to_a_rebuilt_database_and_rechecks_when_the_value_moved(self):
        self.run_doc(Script(default_handler))
        review.add_correction(self.db,bundle(),'PE1','table_a_exam_level','PE1','rating_overall','Outstanding',2,'The bank is rated "Satisfactory" overall.' if False else 'The bank is rated "Satisfactory" overall.','checked the cover table by hand',  'B. Nair') if False else None
        review.add_correction(self.db,bundle(),'PE1','table_a_exam_level','PE1','rating_overall','Satisfactory',2,'The bank is rated "Satisfactory" overall.','confirmed against the printed rating text','B. Nair')
        out=self.dir/'c1.sqlite';res=review.apply_corrections(self.dir/'s.sqlite',out);self.assertEqual(res['applied'],1)
        self.db.execute("UPDATE table_a_exam_level SET rating_overall='Needs to Improve'");self.db.commit()   # the re-extraction now says something else
        res=review.apply_corrections(self.dir/'s.sqlite',self.dir/'c2.sqlite');self.assertEqual((res['applied'],len(res['recheck'])),(0,1))
    def test_decisions_are_mirrored_to_readable_csv_files(self):
        d=tempfile.mkdtemp();db=sqlite3.connect(self.dir/'x.sqlite');db.row_factory=sqlite3.Row;db.executescript(reviewstore.SCHEMA)
        st=reviewstore.Store(db,d);st.attest('PE1','h',[1,2],'B. Nair');text=(Path(d)/'attestations.csv').read_text()
        self.assertIn('B. Nair',text);self.assertEqual(len(text.strip().splitlines()),3)

def pipeline_rebuild(self,db2,b):
    from cra_acquisition import pipeline
    st=reviewstore.open_store(ROOT)
    r=pipeline.run_document(self.rec,b,Script(default_handler),self.ledger,self.dirs,COLS,db2,'RUN',attested=frozenset(st.attested_pages('PE1','s'*64)))
    review.apply_decisions(db2,st,'RUN','PE1');return r
