"""Checks against the real 44 PDFs. Skipped when the project data is absent (for example in CI)."""
import re,unittest
from cra_acquisition import segment,tasks as T
from cra_acquisition.io import read_json
from cra_acquisition.paths import ROOT
from cra_acquisition.prepare import load_or_prepare
from cra_acquisition.tables import read_table

FINAL=ROOT/'reports/final_904bed5b30cc793e19d4.json'
HAVE=FINAL.is_file() and (ROOT/'data/raw').is_dir()

@unittest.skipUnless(HAVE,'project data not present')
class RealCorpus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest=read_json(FINAL);cls.split=read_json(ROOT/'docs/extraction_handoff/holdout_split.json')
        cls.docs={r['pe_id']:r for r in cls.manifest['documents']}
    def bundle(self,pe):return load_or_prepare(ROOT,self.docs[pe])
    def test_dev_documents_identity_on_cover(self):
        expect={'FARMERS':('14807','August 12, 2015'),'HAWAII':('14911','August 3, 2020'),'CITIZENS NATIONAL BANK OF PARK':('13692','January 17, 2023'),'WIGGINS':('8250','July 22, 2024')}
        seen=0
        for pe in self.split['development']:
            rec=self.docs[pe];b=self.bundle(pe);text=b['pages'][0]['text']
            for name,(cid,date) in expect.items():
                if name in rec['institution_name'].upper():
                    self.assertIn(cid,text);self.assertIn(date,text);seen+=1
        self.assertEqual(seen,4)
    def test_every_document_pages_match_manifest_and_are_segmented(self):
        for pe,rec in self.docs.items():
            b=self.bundle(pe);self.assertEqual(b['page_count'],rec['pages'],pe)
            self.assertTrue(segment.covered(segment.segments(b),b['page_count']),pe)
            self.assertEqual(b['unreadable_pages'],0)
    def test_tasks_are_bounded_and_nonempty_for_all_documents(self):
        for pe in self.docs:
            b=self.bundle(pe);tasks=T.plan(b)
            self.assertTrue({'a','b','c','e'}<={t['target'] for t in tasks},pe)
            for t in tasks:
                chars=sum(p['char_count'] for p in b['pages'] if p['page'] in t['pages'])
                self.assertTrue(len(t['pages'])==1 or chars<=T.MAX_CHARS*1.6,(pe,t['target'],chars))
    def test_scans_are_image_backed_and_flagged_for_review(self):
        scanned=[r for r in self.docs.values() if r['scan_status']=='scanned'];self.assertEqual(len(scanned),4)
        for r in scanned:
            b=self.bundle(r['pe_id']);self.assertTrue(all(p['page_class']=='ocr_layer' and p['needs_review'] for p in b['pages']))
    def test_real_table_rows_are_read_by_code(self):
        # Farmers Savings Bank (FDIC small, 2015): borrower-income rows exist on a numbered table page
        pe=next(p for p in self.split['development'] if 'FARMERS' in self.docs[p]['institution_name'])
        b=self.bundle(pe);found=0
        for page in b['pages']:
            for i,l in enumerate(page['lines'],1):
                if re.match(r'^(Low|Moderate|Middle|Upper)\b',l) and len(re.findall(r'\d',l))>=4:
                    rows,_=read_table(page['lines'],i,i,['bank_count','bank_count_pct','bank_dollars','bank_dollar_pct'][:len(re.findall(r'\d[\d,.]*%?',l))])
                    found+=len(rows)
        self.assertGreater(found,0)
    def test_blank_page_is_the_only_blank(self):
        blanks=[(pe,p['page']) for pe in self.docs for p in self.bundle(pe)['pages'] if p['page_class']=='blank']
        self.assertEqual(len(blanks),1)
    def test_holdout_split_is_reproducible_from_seed(self):
        from cra_acquisition.score import split
        self.assertEqual(split(self.manifest)['holdout'],sorted(self.split['holdout']))
    def test_accepted_research_database_is_untouched_by_the_pipeline(self):
        import sqlite3
        with sqlite3.connect((ROOT/'data/research.sqlite').as_uri()+'?mode=ro',uri=True) as c:
            for (t,) in c.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'").fetchall():
                if t in ('table_a_exam_level','field_evidence'):self.assertEqual(c.execute(f'select count(*) from {t}').fetchone()[0],0)
    def test_final_pdfs_remain_read_only_and_unchanged(self):
        import hashlib,os
        for rec in self.docs.values():
            p=ROOT/rec['path'];self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),rec['sha256'])
            if os.name=='posix':self.assertEqual(p.stat().st_mode&0o222,0)

if __name__=='__main__':unittest.main()

@unittest.skipUnless(HAVE,'project data not present')
class WideTableReader(unittest.TestCase):
    """Hawaii National Bank Table O (areas down the side, income categories across): values checked against the printed page."""
    def test_hawaii_table_o_is_read_exactly(self):
        from cra_acquisition import tasks as T
        manifest=read_json(FINAL);split=read_json(ROOT/'docs/extraction_handoff/holdout_split.json')
        rec=next(r for r in manifest['documents'] if r['pe_id'] in split['development'] and 'HAWAII' in r['institution_name'])
        b=load_or_prepare(ROOT,rec);cols=T.research_columns()
        cats=['low','moderate','middle','upper','not available']
        columns=[dict(meaning='ignore',category='',header='')]*4
        for c in cats:columns+=[dict(meaning='demographic_pct',category=c,header=''),dict(meaning='bank_count_pct',category=c,header=''),dict(meaning='aggregate_pct',category=c,header='')]
        layout=dict(kind='area_rows',page=24,first_line=0,last_line=0,table_index=1,first_row=4,last_row=7,table_label='Table O',title='',aa_ref='',product_ref='',
                    dimension='census tract income',years='2017-19',demographic_base='% of Owner-Occupied Housing Units',source_note='',columns=columns)
        flags=[];aa={'honolulu aa':'AA1','hawaii non-msa aa':'AA2','maui (limited-scope)':'AA3'}
        rows=T.build_d('PE',b,[layout],aa,{},cols,flags)
        got={(r['ids'].get('aa_id'),r['fields']['category']['value']):{k:v['value'] for k,v in r['fields'].items()} for r in rows}
        h=got[('AA1','low')];self.assertEqual((h['demographic_pct'],h['bank_count_pct'],h['aggregate_pct']),(1.1,0.9,0.7))
        h=got[('AA1','upper')];self.assertEqual((h['demographic_pct'],h['bank_count_pct'],h['aggregate_pct']),(43.3,59.6,48.1))
        h=got[('AA2','middle')];self.assertEqual((h['demographic_pct'],h['bank_count_pct'],h['aggregate_pct']),(64.0,40.0,59.2))
        self.assertEqual(len(rows),15)   # 3 areas x 5 categories; the Total row is skipped
        self.assertEqual(got[('AA3','low')]['table_label'],'Table O')
        self.assertTrue(all(r['fields']['dimension']['value']=='census tract income' for r in rows))
        # every field validates against the page: re-stage through the strict path
        pages={p['page']:p for p in b['pages']}
        from cra_acquisition.research import check_field
        for r in rows:
            for f,item in r['fields'].items():check_field('table_d_distribution_measures',f,cols['table_d_distribution_measures'][f],item,pages)
        self.assertEqual([f for f in flags if f['kind'] in ('field_rejected','table_row_unread','layout_rejected')],[])
        self.assertEqual(got[('AA1','low')]['demographic_base'],'% of Owner-Occupied Housing Units')

@unittest.skipUnless(HAVE,'project data not present')
class CategoryColumnsReader(unittest.TestCase):
    def test_frb_2002_borrower_income_table_is_read_exactly(self):
        from cra_acquisition import tasks as T
        m=read_json(FINAL);rec=next(r for r in m['documents'] if r['agency']=='FRB' and r['pages']==23 and r['exam_date'].startswith('2002'))
        b=load_or_prepare(ROOT,rec);cols=T.research_columns();lines=b['pages'][11]['lines']
        ln={k:i+1 for i,l in enumerate(lines) for k in ('Total Number of Loans','Percentage of Total Loans') if l.startswith(k)}
        lay=dict(kind='category_columns',page=12,first_line=0,last_line=0,table_index=0,first_row=0,last_row=0,table_label='',title='',aa_ref='',product_ref='home mortgage',dimension='borrower income',years='',demographic_base='',source_note='',
                 columns=[dict(meaning='ignore',category=c,header='') for c in ('low','moderate','middle','upper','')],
                 row_meanings=[dict(line=ln['Total Number of Loans'],meaning='bank_count',label=''),dict(line=ln['Percentage of Total Loans'],meaning='bank_count_pct',label='')])
        flags=[];rows=T.build_d('PE',b,[lay],{},{},cols,flags)
        got={(r['fields']['category']['value']):r['fields'] for r in rows}
        self.assertEqual([got[c]['bank_count']['value'] for c in ('low','moderate','middle','upper')],[50,49,30,41])
        self.assertEqual([got[c]['bank_count_pct']['value'] for c in ('low','moderate','middle','upper')],[29.5,28.8,17.6,24.1])
        self.assertEqual([f for f in flags if f['kind'] in ('field_rejected','table_row_unread','layout_rejected')],[])
