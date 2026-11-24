import csv,json,sqlite3,tempfile,unittest
from pathlib import Path
from cra_acquisition import runstate,validate,review,score,handoff,packet,rssd
from cra_acquisition.paths import ROOT
from cra_acquisition.research import save,TABLES
from test_tasks_pipeline import bundle,COLS

def item(value,page,quote,literal=None):return dict(value=value,page=page,quote=quote,value_as_printed=literal,printed_page_label=None)

def proposal(pe='PE1'):
    t={k:[] for k in TABLES}
    t['table_a_exam_level']=[dict(ids={'pe_id':pe},fields={'agency_id':item('14807',1,'Certificate Number: 14807','14807'),
                                                         'exam_date':item('2015-08-12',1,'August 12, 2015','August 12, 2015'),
                                                         'rating_overall':item('Satisfactory',2,'The bank is rated "Satisfactory" overall.','Satisfactory')})]
    return dict(sha256='s'*64,tables=t)

class Env(unittest.TestCase):
    def setUp(self):
        self.d=tempfile.TemporaryDirectory();self.addCleanup(self.d.cleanup);self.dir=Path(self.d.name)
        self.db=runstate.init_staging(self.dir/'s.sqlite',ROOT);self.addCleanup(self.db.close)
        save(self.db,'PE1',bundle(),proposal())
        runstate.set_status(self.db,'RUN','PE1','staged')

class ValidateTests(Env):
    def kinds(self,**rec):return [f['kind'] for f in validate.validate_document(self.db,'PE1',rec or None)]
    def test_date_and_rating_and_ffiec_difference(self):
        self.db.execute("UPDATE table_a_exam_level SET eval_period_end='2016-01-01',rating_overall='Great',prior_exam_date='2016-01-01'")
        k=self.kinds(exam_date='2015-12-01',agency_id='14807',date_basis='FFIEC release-date proxy')
        for expect in ('date_inconsistent','rating_out_of_set','date_differs_from_ffiec'):self.assertIn(expect,k)
    def test_identity_mismatch_handles_leading_zeros(self):
        self.assertNotIn('identity_mismatch',self.kinds(agency_id='014807'));self.assertIn('identity_mismatch',self.kinds(agency_id='99'))
    def test_percent_sums_and_impossible_values(self):
        self.db.execute("INSERT INTO table_b_products_reviewed(product_id,pe_id,product) VALUES ('B1','PE1','home mortgage')")
        for i,(c,v) in enumerate([('low',10),('moderate',20),('middle',30),('upper',50)]):
            self.db.execute("INSERT INTO table_d_distribution_measures(distribution_id,pe_id,product_id,dimension,category,bank_count_pct,page) VALUES (?,?,?,?,?,?,1)",(f'D{i}','PE1','B1','borrower income',c,v))
        self.assertIn('percent_sum',self.kinds())
        self.db.execute("UPDATE table_d_distribution_measures SET bank_count_pct=250 WHERE distribution_id='D0'")
        self.assertIn('impossible_percent',self.kinds())
    def test_tolerance_for_rounding(self):
        for i,(c,v) in enumerate([('low',10.1),('moderate',20.0),('middle',30.0),('upper',39.4)]):
            self.db.execute("INSERT INTO table_d_distribution_measures(distribution_id,pe_id,dimension,category,bank_count_pct,page) VALUES (?,?,?,?,?,1)",(f'D{i}','PE1','borrower income',c,v))
        self.assertNotIn('percent_sum',self.kinds())
    def test_missing_evidence_and_required_families(self):
        self.db.execute("UPDATE table_a_exam_level SET prior_rating='Satisfactory'")
        k=self.kinds(exam_type='small');self.assertIn('missing_evidence',k);self.assertIn('missing_table_family',k)
    def test_run_disagreement(self):
        other=runstate.init_staging(self.dir/'o.sqlite',ROOT);self.addCleanup(other.close)
        p=proposal();p['tables']['table_a_exam_level'][0]['fields']['rating_overall']=item('Outstanding',2,'The bank is rated "Satisfactory" overall.','Satisfactory')
        save(other,'PE1',bundle(),proposal())
        other.execute("UPDATE table_a_exam_level SET rating_overall='Outstanding'");other.commit()
        self.assertEqual([f['field'] for f in validate.compare_runs(self.db,other,'PE1')],['rating_overall'])

class ReviewTests(Env):
    def add_flag(self,kind):
        runstate.add_flags(self.db,'RUN','PE1',[dict(kind=kind,page=2)])
    def test_review_level_flags_travel_with_the_data_but_error_level_flags_stop_it(self):
        self.add_flag('image_review_required')
        with self.assertRaises(ValueError):review.mark_reviewed(self.db,'RUN','PE1',strict=True)      # strict still demands everything clear
        review.mark_reviewed(self.db,'RUN','PE1');self.assertIn('review flags still open',self.db.execute("select detail from doc_status").fetchone()[0])
        runstate.set_status(self.db,'RUN','PE1','staged');self.add_flag('task_failed')
        with self.assertRaises(ValueError):review.mark_reviewed(self.db,'RUN','PE1')                  # wrong or missing data is never waved through
    def test_attesting_the_page_clears_the_image_flag(self):
        self.add_flag('image_review_required');review.attest_pages(self.db,'PE1','s'*64,[2],'A. Reviewer')
        self.assertEqual([f for f in runstate.open_flags(self.db,'RUN','PE1') if f['kind']=='image_review_required'],[])
    def test_attestation_requires_a_name_and_resolve_requires_a_note(self):
        with self.assertRaises(ValueError):review.attest_pages(self.db,'PE1','s'*64,[2],'  ')
        self.add_flag('percent_sum');fid=runstate.open_flags(self.db,'RUN','PE1')[0]['flag_id']
        with self.assertRaises(ValueError):review.resolve_flag(self.db,fid,'waived','no')
        review.resolve_flag(self.db,fid,'waived','checked the printed table; rounding in source',reviewer='B. Nair');review.mark_reviewed(self.db,'RUN','PE1')
    def test_accept_copies_atomically_backs_up_and_is_idempotent(self):
        review.mark_reviewed(self.db,'RUN','PE1');self.db.commit()
        research=self.dir/'research.sqlite'
        research.write_bytes((ROOT/'data/research.sqlite').read_bytes()) if (ROOT/'data/research.sqlite').is_file() else None
        r=review.accept(self.dir/'s.sqlite',research,'RUN','PE1',ROOT,backup_dir=self.dir/'bk')
        with sqlite3.connect(research) as c:
            self.assertEqual(c.execute('select agency_id from table_a_exam_level').fetchone()[0],'14807')
            self.assertEqual(c.execute('select count(*) from field_evidence').fetchone()[0],3)
            self.assertEqual(c.execute('pragma foreign_key_check').fetchall(),[])
        self.assertTrue(Path(r['backup']).is_file())
    def test_accept_refuses_mock_unreviewed_and_blocked(self):
        with self.assertRaises(ValueError):review.accept(self.dir/'s.sqlite',self.dir/'r.sqlite','MOCK-1','PE1')
        with self.assertRaises(ValueError):review.accept(self.dir/'s.sqlite',self.dir/'r.sqlite','RUN','PE1')   # staged, not reviewed
    def test_freeze_detects_any_change(self):
        class P:model='m';price_version='1'
        path=self.dir/'f.json';review.freeze(path,P(),'low','test',ROOT)
        review.verify_freeze(path,P(),'low',ROOT)
        with self.assertRaises(ValueError):review.verify_freeze(path,P(),'high',ROOT)
        P.model='other'
        with self.assertRaises(ValueError):review.verify_freeze(path,P(),'low',ROOT)
        second=review.freeze(path,P(),'low','again',ROOT);self.assertNotEqual(second['path'],str(path))   # a later freeze gets its own file instead of being refused

class ScoreTests(unittest.TestCase):
    def row(self,pe,field,value,table='table_c_assessment_areas',ctx='a',critical=True):return dict(pe_id=pe,table=table,context=ctx,field=field,value=value,critical=critical)
    def test_omissions_additions_and_numeric_equality(self):
        ref=[self.row('p','aa_name','Honolulu'),self.row('p','review_scope','full scope'),self.row('p','x',5.0,'table_d_distribution_measures')]
        pred=[self.row('p','aa_name','honolulu'),self.row('p','x',5,'table_d_distribution_measures'),self.row('p','extra','z',critical=True)]
        s=score.measure(ref,pred,{'p'})
        self.assertEqual(s['critical_denominator'],3);self.assertEqual(s['critical_hits'],2);self.assertAlmostEqual(s['critical_exact'],2/3)
        self.assertEqual(s['per_table']['table_c_assessment_areas'],dict(exact=1,omission=1,false_addition=1))
    def test_zero_denominator_is_not_evaluable(self):
        s=score.measure([],[],{'p'},targets={'critical_exact':.99,'conclusion_precision':.95,'conclusion_recall':.95})
        self.assertIsNone(s['critical_exact']);self.assertIsNone(s['passed']);self.assertFalse(s['reference_complete'])
    def test_missing_holdout_document_blocks_pass(self):
        r=[self.row('p','aa_name','A')];s=score.measure(r,r,{'p','q'},targets={'critical_exact':.99,'conclusion_precision':.95,'conclusion_recall':.95})
        self.assertEqual(s['documents_missing_reference'],['q']);self.assertIsNone(s['gates']['critical_exact'])
    def test_non_holdout_rows_rejected_and_duplicates_get_ordinals(self):
        with self.assertRaises(ValueError):score.measure([self.row('z','f',1)],[],{'p'})
        dup=[self.row('p','f',1),self.row('p','f',2)];s=score.measure(dup,dup,{'p'});self.assertEqual(s['critical_hits'],2)
    def test_wrong_context_is_addition_and_omission(self):
        e='table_e_examiner_conclusions'
        a=self.row('p','label_verbatim','good',e,'m|a');b=dict(a,context='m|b')
        s=score.measure([a],[b],{'p'});self.assertEqual((s['conclusion_precision'],s['conclusion_recall']),(0,0))
    def test_wilson_and_strata(self):
        self.assertEqual(score.wilson(0,0),None);lo,hi=score.wilson(95,100);self.assertTrue(lo<.95<hi)
        r=[self.row('p','aa_name','A')];s=score.measure(r,r,{'p'},strata={'p':dict(agency='OCC',era='2020+',exam_type='small',scan_status='text_based')})
        self.assertEqual(s['strata']['agency=OCC']['exact'],1.0)
    def test_era(self):self.assertEqual([score.era(y) for y in (1999,2007,2012,2016,2024)],['1997-2004','2005-2009','2010-2014','2015-2019','2020+'])

class ExportTests(Env):
    def test_csv_conventions_are_lossless_and_spreadsheet_safe_copy_differs(self):
        self.assertEqual(handoff.csv_cell(None),'\\N');self.assertEqual(handoff.csv_cell(''),'');self.assertEqual(handoff.csv_cell('\\N'),'\\\\N')
        self.assertEqual(handoff.csv_cell('=SUM(A1)'),'=SUM(A1)');self.assertEqual(handoff.csv_cell('=SUM(A1)',safe=True),"'=SUM(A1)")
        self.assertEqual(handoff.csv_cell('-5',safe=True),'-5');self.assertEqual(handoff.csv_cell(0),'0')
    def test_incomplete_gates_produce_a_draft_never_a_release(self):
        m=dict(run_id='r',development_ids=[],documents=[dict(pe_id='PE1',agency='FDIC',exam_type='small',sha256='1',scan_status='text_based')])
        out=self.dir/'exports';res=handoff.export(self.db,m,out)
        self.assertFalse(res['release']);self.assertEqual(res['label'],'UNVERIFIED');self.assertTrue(Path(res['path']).name.startswith('UNVERIFIED'))
        status=json.loads((Path(res['path'])/'RELEASE_STATUS.json').read_text());self.assertFalse(status['release']);self.assertEqual(status['label'],'UNVERIFIED')
        self.assertEqual([p for p in out.iterdir() if p.name.startswith('.export')],[])
        self.assertTrue((Path(res['path'])/'CHECKSUMS.json').is_file());self.assertTrue((Path(res['path'])/'safe_for_spreadsheets').is_dir())
        with open(Path(res['path'])/'table_a_exam_level.csv',newline='',encoding='utf-8') as f:rows=list(csv.reader(f))
        self.assertIn('\\N',rows[1])   # NULLs are explicit
    def test_indicator_proposals_are_not_confirmations(self):
        p=handoff.propose_indicators(self.db,['PE1'])
        self.assertTrue(all(v['basis']=='proposed' and 'reviewed_by' not in v for v in p['PE1'].values()))

class PacketTests(unittest.TestCase):
    def test_forms_have_no_model_output_and_round_trip(self):
        inv=validate.inventory();forms=packet.form_columns(COLS,inv)
        self.assertIn('source_page',forms['table_e_examiner_conclusions']);self.assertNotIn('conclusion_id',forms['table_e_examiner_conclusions'])
        with tempfile.TemporaryDirectory() as d:
            d=Path(d)
            with (d/'table_c_assessment_areas.csv').open('w',newline='',encoding='utf-8') as f:
                w=csv.writer(f);w.writerow(forms['table_c_assessment_areas']);w.writerow(['PE1','Honolulu MSA','','','full scope'])
            rows=packet.read_forms(d,inv,COLS)
            self.assertEqual({(r['field'],r['value']) for r in rows},{('aa_name','Honolulu MSA'),('review_scope','full scope')})
            self.assertTrue(all(r['critical'] for r in rows))
            with self.assertRaises(ValueError):packet.submit_reference(d,d/'out','R','a','b',False,{'PE1'})
            res=packet.submit_reference(d,d/'out','R','a','b',True,{'PE1','PE2'});self.assertEqual(res['missing'],['PE2'])

class RssdTests(unittest.TestCase):
    SNAP=dict(rows=[dict(CERT=14807,FED_RSSD=111,CHARTER=0,ACTIVE=1),dict(CERT=5,FED_RSSD=222,CHARTER=14911,ACTIVE=0),
                    dict(CERT=6,FED_RSSD=333,CHARTER=13692,ACTIVE=1),dict(CERT=7,FED_RSSD=444,CHARTER=13692,ACTIVE=1)])
    def test_matching_rules(self):
        docs=[dict(agency='FDIC',agency_id='14807',institution_name='a'),dict(agency='OCC',agency_id='14911',institution_name='b'),
              dict(agency='OCC',agency_id='13692',institution_name='c'),dict(agency='OCC',agency_id='99999',institution_name='d'),
              dict(agency='FRB',agency_id='0638850',institution_name='e'),dict(agency='OCC',agency_id='014911',institution_name='f')]
        out={r['institution_name']:r for r in rssd.build(dict(documents=docs),self.SNAP)}
        self.assertEqual((out['a']['rssd_id'],out['b']['rssd_id'],out['b']['active']),('111','222',0))
        self.assertEqual(out['c']['status'],'conflict');self.assertEqual(out['d']['status'],'unmatched')
        self.assertEqual(out['e']['rssd_id'],'0638850');self.assertEqual(out['f']['rssd_id'],'222')   # leading zeros preserved / normalised
    def test_incomplete_enumeration_is_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            pages=[dict(data=[dict(data=dict(CERT=1))],meta=dict(total=5)),dict(data=[],meta=dict(total=5))]
            with self.assertRaises(ValueError):rssd.fetch_snapshot(d,fetch=lambda url:pages.pop(0),sleep=0)

if __name__=='__main__':unittest.main()

class ConclusionMatchTests(unittest.TestCase):
    E='table_e_examiner_conclusions'
    def obj(self,pe,rid,label,page,**kw):
        rows=[dict(pe_id=pe,table=self.E,context=rid,field='label_verbatim',value=label,row_id=rid,page=page)]
        for k,v in kw.items():rows.append(dict(pe_id=pe,table=self.E,context=rid,field=k,value=v,row_id=rid,page=page))
        return rows
    def test_boundary_differences_match_leniently_not_exactly(self):
        ref=self.obj('p','r1','adequate responsiveness',7,level='criterion')
        pred=self.obj('p','x1','shows adequate responsiveness',7,level='criterion')
        m=score.match_conclusions(ref,pred);self.assertEqual((m['matched'],m['matched_exact']),(1,0));self.assertEqual(m['level_agreement'],1.0)
        self.assertEqual(m['exact_recall'],0.0);self.assertEqual(m['lenient_recall'],1.0)
    def test_page_must_agree_and_matching_is_one_to_one(self):
        ref=self.obj('p','r1','reasonable',7)+self.obj('p','r2','reasonable',7)
        pred=self.obj('p','x1','reasonable',7)+self.obj('p','x2','reasonable',9)
        m=score.match_conclusions(ref,pred);self.assertEqual(m['matched'],1);self.assertEqual(m['predicted'],2);self.assertEqual(m['reference'],2)
        self.assertEqual((m['lenient_precision'],m['lenient_recall']),(0.5,0.5))
    def test_different_judgments_on_one_page_do_not_match(self):
        m=score.match_conclusions(self.obj('p','r1','excellent performance',3),self.obj('p','x1','poor distribution',3));self.assertEqual(m['matched'],0)
    def test_attribute_disagreement_is_reported_for_matched_pairs(self):
        ref=self.obj('p','r1','reasonable',3,level='criterion',category='low')
        pred=self.obj('p','x1','reasonable',3,level='income category',category='low')
        m=score.match_conclusions(ref,pred);self.assertEqual(m['level_agreement'],0.0);self.assertEqual(m['category_agreement'],1.0)
    def test_no_conclusions_is_not_evaluable(self):
        m=score.match_conclusions([],[]);self.assertIsNone(m['lenient_recall']);self.assertIsNone(m['level_agreement'])

class CoverageTests(unittest.TestCase):
    def row(self,pe,table,field,value,ctx='a',critical=True):return dict(pe_id=pe,table=table,context=ctx,field=field,value=value,critical=critical)
    def test_uncoded_tables_are_not_counted_as_false_additions(self):
        C='table_c_assessment_areas';D='table_d_distribution_measures'
        ref=[self.row('p',C,'aa_name','Honolulu')]
        pred=[self.row('p',C,'aa_name','Honolulu')]+[self.row('p',D,'bank_count_pct',float(i),ctx=str(i)) for i in range(50)]
        full=score.measure(ref,pred,{'p'})                                   # no declaration: the 50 table D rows look like false additions
        self.assertEqual(full['per_table'][D]['false_addition'],50)
        scoped=score.measure(ref,pred,{'p'},coverage={'p':[C]})
        self.assertNotIn(D,scoped['per_table']);self.assertEqual(scoped['critical_exact'],1.0)
        self.assertEqual(scoped['coverage']['tables_not_coded'].count(D),1)
    def test_coded_but_empty_table_still_counts_extra_predictions(self):
        D='table_d_distribution_measures'
        pred=[self.row('p',D,'bank_count_pct',1.0)]
        s=score.measure([],pred,{'p'},coverage={'p':[D]});self.assertEqual(s['per_table'][D]['false_addition'],1)
    def test_submit_validates_coverage(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):packet.submit_reference(d,Path(d)/'o','R','a','b',True,{'PE1'},coverage={'PE1':['not_a_table']})
            with self.assertRaises(ValueError):packet.submit_reference(d,Path(d)/'o','R','a','b',True,{'PE1'},coverage={'OTHER':['table_c_assessment_areas']})

class EmptySubmissionTests(unittest.TestCase):
    def test_an_empty_forms_folder_is_refused_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            forms=Path(d)/'forms';forms.mkdir();out=Path(d)/'out'
            for t in ('table_a_exam_level','table_c_assessment_areas'):
                (forms/f'{t}.csv').write_text('pe_id,aa_name,source_page\n',encoding='utf-8')   # headers only
            with self.assertRaises(ValueError) as cm:packet.submit_reference(forms,out,'R','a','b',True,{'PE1'})
            self.assertIn('no coded rows',str(cm.exception));self.assertFalse(out.exists())

class CanonicalTests(unittest.TestCase):
    D='table_d_distribution_measures'
    def r(self,ctx,field,value,table=None):return dict(pe_id='p',table=table or self.D,context=ctx,field=field,value=value,critical=True)
    def test_spelling_and_format_differences_are_not_disagreement(self):
        ref=[self.r('wichita ks msa 48620|home purchase|borrower income|<$1,000,000|2019','bank_count_pct','82.5%')]
        pred=[self.r('wichita ma|home mortgage|borrower income|at or below $1 million|','bank_count_pct',82.5)]
        s=score.measure(ref,pred,{'p'});self.assertEqual(s['per_table'][self.D],dict(exact=1))
        a=[self.r('row','agency','Comptroller of the Currency','table_a_exam_level')];b=[self.r('row','agency','OCC','table_a_exam_level')]
        self.assertEqual(score.measure(a,b,{'p'})['critical_exact'],1.0)
    def test_real_value_differences_still_count(self):
        ref=[self.r('x|home mortgage|borrower income|low|','bank_count_pct',10.0)];pred=[self.r('x|home mortgage|borrower income|low|','bank_count_pct',11.0)]
        self.assertEqual(score.measure(ref,pred,{'p'})['per_table'][self.D],dict(mismatch=1))
        a=[self.r('row','rating_overall','Satisfactory','table_a_exam_level')];b=[self.r('row','rating_overall','Outstanding','table_a_exam_level')]
        self.assertEqual(score.measure(a,b,{'p'})['critical_exact'],0.0)
    def test_partial_reference_summary_separates_coverage_from_pipeline_only_rows(self):
        ref=[self.r('a|||low|','bank_count_pct',1.0),self.r('a|||moderate|','bank_count_pct',2.0)]
        pred=[self.r('a|||low|','bank_count_pct',1.0)]+[self.r(f'a|||x{i}|','bank_count_pct',float(i)) for i in range(10)]
        t=score.measure(ref,pred,{'p'})['table_summary'][self.D]
        self.assertEqual((t['reference_rows'],t['reference_coverage'],t['value_agreement_when_both_present'],t['pipeline_only_rows']),(2,0.5,1.0,10))

class ValidateRerunTests(Env):
    def test_rerunning_validation_does_not_duplicate_or_keep_stale_flags(self):
        from cra_acquisition import runstate as rs
        self.db.execute("UPDATE table_a_exam_level SET rating_overall='Great'");self.db.commit()
        def run():
            f=validate.validate_document(self.db,'PE1',None);keep=[x for x in rs.open_flags(self.db,'RUN','PE1') if x['kind'] not in validate.VALIDATION_KINDS]
            rs.add_flags(self.db,'RUN','PE1',[dict(kind=x['kind']) for x in keep]+f)
            return sorted(x['kind'] for x in rs.open_flags(self.db,'RUN','PE1'))
        first=run();second=run();self.assertEqual(first,second);self.assertEqual(first.count('rating_out_of_set'),1)
        self.db.execute("UPDATE table_a_exam_level SET rating_overall='SATISFACTORY'");self.db.commit()
        self.assertNotIn('rating_out_of_set',run())     # fixed data clears the stale flag; case is not an error
    def test_areas_down_the_side_rows_are_summed_per_row_not_per_table(self):
        for i,(row,c,v) in enumerate([('r4','low',10),('r4','moderate',20),('r4','middle',30),('r4','upper',40),('r5','low',50),('r5','moderate',20),('r5','middle',20),('r5','upper',10)]):
            self.db.execute("INSERT INTO table_d_distribution_measures(distribution_id,pe_id,dimension,category,bank_count_pct,page,table_label) VALUES (?,?,?,?,?,1,'Table O')",(f'PE1:D:p1t1{row}:{c}','PE1','census tract income',c,v))
        self.assertNotIn('percent_sum',[f['kind'] for f in validate.validate_document(self.db,'PE1',None)])

class StackedTableTests(Env):
    def test_several_tables_stacked_on_one_page_are_validated_separately(self):
        cats=['low','moderate','middle','upper']
        for base in (10,20,30):                                   # three separate 4-row tables, each summing to exactly 100
            for i,(c,v) in enumerate(zip(cats,(10,20,30,40))):
                self.db.execute("INSERT INTO table_d_distribution_measures(distribution_id,pe_id,dimension,category,bank_count_pct,page) VALUES (?,?,?,?,?,1)",(f'PE1:D:p1l{base+i}','PE1','borrower income',c,v))
        self.assertNotIn('percent_sum',[f['kind'] for f in validate.validate_document(self.db,'PE1',None)])
    def test_a_table_that_really_sums_wrong_is_still_flagged(self):
        for i,(c,v) in enumerate(zip(['low','moderate','middle','upper'],(10,20,30,60))):
            self.db.execute("INSERT INTO table_d_distribution_measures(distribution_id,pe_id,dimension,category,bank_count_pct,page) VALUES (?,?,?,?,?,1)",(f'PE1:D:p1l{10+i}','PE1','borrower income',c,v))
        self.assertIn('percent_sum',[f['kind'] for f in validate.validate_document(self.db,'PE1',None)])


class ExportLabelTests(Env):
    M=dict(run_id='r',development_ids=[],documents=[dict(pe_id='PE1',agency='FDIC',exam_type='small',sha256='1',scan_status='text_based')])
    AUDIT=dict(answered=120,overall_strict_precision=.91,overall_ci95_approx=[.87,.95],per_table={})
    def test_export_is_always_written_and_labelled_by_how_far_it_can_be_trusted(self):
        out=self.dir/'e'
        r=handoff.export(self.db,self.M,out);self.assertEqual(r['label'],'UNVERIFIED')
        r=handoff.export(self.db,self.M,out,audit=self.AUDIT);self.assertEqual(r['label'],'AUDITED');self.assertTrue(Path(r['path']).name.startswith('AUDITED'))
        r=handoff.export(self.db,self.M,out,audit=dict(self.AUDIT,answered=40));self.assertEqual(r['label'],'UNVERIFIED')     # too small a sample to count
    def test_an_open_error_level_flag_keeps_even_an_audited_export_unverified(self):
        runstate.add_flags(self.db,'RUN','PE1',[dict(kind='task_failed',detail='x')])
        self.assertEqual(handoff.export(self.db,self.M,self.dir/'e',audit=self.AUDIT)['label'],'UNVERIFIED')
    def test_the_workbook_says_what_the_label_means(self):
        from cra_acquisition import workbook
        self.assertIn('AUDITED',workbook.status_lines(dict(label='AUDITED',audit=self.AUDIT))[0]);self.assertIn('91%',workbook.status_lines(dict(label='AUDITED',audit=self.AUDIT))[0])
        self.assertIn('NOT been checked',' '.join(workbook.status_lines(dict(label='UNVERIFIED'))))

class EvaluationViewTests(unittest.TestCase):
    def test_every_evaluation_gets_a_row_and_an_unknown_rssd_stays_blank(self):
        import csv,sqlite3,tempfile
        from pathlib import Path
        from cra_acquisition.handoff import write_evaluation_view
        db=sqlite3.connect(':memory:')
        db.execute('create table rssd_crosswalk(agency text,agency_id text,rssd_id text,status text)')
        db.execute('create table table_a_exam_level(pe_id text,agency_id text,exam_date text,exam_type text,rating_overall text)')
        db.execute("insert into rssd_crosswalk values('FDIC','14807','123','matched')")
        docs={'p1':dict(agency='FDIC',agency_id='14807',institution_name='A'),'p2':dict(agency='OCC',agency_id='9',institution_name='B')}
        with tempfile.TemporaryDirectory() as d:
            write_evaluation_view(db,docs,Path(d)/'e.csv')
            rows=list(csv.DictReader((Path(d)/'e.csv').open(encoding='utf-8')))
        self.assertEqual([(r['pe_id'],r['rssd_id']) for r in rows],[('p1','123'),('p2','')])
        db.execute("insert into table_a_exam_level values('p1','14807','2020-01-01','x','Satisfactory')")
        self.assertEqual(db.execute('select rssd_id from v_evaluations_rssd').fetchone()[0],'123')
