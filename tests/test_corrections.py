import sqlite3
from cra_acquisition import runstate,review
from cra_acquisition.paths import ROOT
from test_review_score_export import Env
from test_tasks_pipeline import bundle

class CorrectionTests(Env):
    def test_migration_is_additive_and_idempotent(self):
        self.assertFalse(runstate.migrate(self.db))
        self.assertIsNotNone(self.db.execute("select 1 from sqlite_master where name='doc_status'").fetchone())
    def correct(self,**kw):
        a=dict(db=self.db,bundle=bundle(),pe_id='PE1',table='table_a_exam_level',record_id='PE1',field='rating_overall',new_value='Outstanding',page=2,
               quote='The bank is rated "Satisfactory" overall.',reason='the cover table shows Outstanding; checked against the PDF',reviewer='R. Reviewer');a.update(kw)
        return review.add_correction(**a)
    def test_a_correction_needs_supporting_text_a_reason_and_a_name(self):
        for bad in (dict(reviewer=' '),dict(reason='short'),dict(table='nope'),dict(field='pe_id'),dict(page=99),dict(record_id='ZZZ',table='table_b_products_reviewed')):
            with self.assertRaises(ValueError,msg=str(bad)):self.correct(**bad)
        with self.assertRaises(ValueError):self.correct(new_value='Outstanding',quote='text that is not on the page')   # unsupported value is refused
        from cra_acquisition import reviewstore;st=reviewstore.open_store(ROOT);self.assertEqual(st.corrections(),[])
    def test_correction_is_stored_not_applied_and_the_copy_carries_it(self):
        self.correct(new_value='SATISFACTORY',quote='The bank is rated "Satisfactory" overall.',reason='the PDF prints the rating in capitals; testing apply path')
        self.assertEqual(self.db.execute('select rating_overall from table_a_exam_level').fetchone()[0],'Satisfactory')
        out=self.dir/'corrected.sqlite';res=review.apply_corrections(self.dir/'s.sqlite',out);self.assertEqual((res['applied'],res['recheck'],res['orphans']),(1,[],[]))
        self.assertEqual(self.db.execute('select rating_overall from table_a_exam_level').fetchone()[0],'Satisfactory')   # original untouched
        c=sqlite3.connect(out);self.assertEqual(c.execute('select rating_overall from table_a_exam_level').fetchone()[0],'SATISFACTORY')
        ev=c.execute("select evidence_verbatim from field_evidence where field_name='rating_overall'").fetchall();self.assertEqual(len(ev),1)
        with self.assertRaises(FileExistsError):review.apply_corrections(self.dir/'s.sqlite',out)
