from pathlib import Path
import sqlite3
import unittest
from cra_acquisition.research import save,TABLES

class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.executescript((Path(__file__).resolve().parents[1]/'schemas/research_schema.sql').read_text())
        self.bundle={'sha256':'hash','pages':[{'page':1,'text':'Example Bank, December 1, 2024','status':'text'}]}
        self.p={'sha256':'hash','tables':{t:[] for t in TABLES}}
        self.p['tables']['table_a_exam_level']=[{'ids':{'pe_id':'a'},'fields':{
           'exam_date':{'value':'2024-12-01','value_as_printed':'December 1, 2024','page':1,'quote':'Example Bank, December 1, 2024'}}}]
    def test_repeat_then_bad_proposal_preserves_accepted_rows(self):
        self.assertEqual(save(self.db,'a',self.bundle,self.p)['evidence'],1)
        self.assertEqual(save(self.db,'a',self.bundle,self.p)['evidence'],1)
        self.p['tables']['table_a_exam_level'][0]['fields']['exam_date']['value']='2024-12-02'
        with self.assertRaises(ValueError):save(self.db,'a',self.bundle,self.p)
        self.assertEqual(self.db.execute('SELECT exam_date FROM table_a_exam_level').fetchone()[0],'2024-12-01')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM field_evidence').fetchone()[0],1)
