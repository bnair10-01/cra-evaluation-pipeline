import tempfile
import unittest
from pathlib import Path

from cra_acquisition.workflow import read_frame, custom_draw
from cra_acquisition.retrieve import federal_rows, month_links

class WorkflowTests(unittest.TestCase):
    def test_real_form_shape(self):
        body=b'<tr><td><a class="bankDetail">1ST BANK&nbsp;-&nbsp;564856</a><br>BROADUS, MT</td><td>Satisfactory</td><td>Jan 13, 2020<br><a href="DownloadPDF/564856_20200113">Download PE</a></td><td>Apr 11, 2020</td><td>Small Bank</td></tr>'
        row,=federal_rows(body)
        self.assertEqual((row['agency_id'],row['exam_date']),('564856','2020-01-13'))
        self.assertTrue(row['pdf_url'].endswith('/CRA/DownloadPDF/564856_20200113'))
    def test_ffiec_quarantines_conflicting_rows(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            p=Path(d)/'crarating.txt'
            good='14\t2\t20200102\tA Bank\tA\tDE\t1\t2\t2\n'
            conflict='15\t3\t20200202\tB Bank\tB\tDE\t1\t2\t2\n'
            p.write_text(good*2+conflict+conflict.replace('B Bank','Alternate')+'short\n')
            rows,report=read_frame(p)
            self.assertEqual(len(rows),1);self.assertEqual(report['duplicates'],1)
            self.assertEqual(len(report['conflicts']),1);self.assertEqual(report['invalid_lines'],[5])
    def test_custom_six_and_shortage(self):
        frame=[dict(pe_id=a+str(i),agency=a,exam_date=f'{year}-01-02',exam_type='small')
               for a in ['OCC','FDIC','FRB'] for i,year in enumerate([2019,2020,2020,2020])]
        a,b=custom_draw(frame,6,[2020,2020],['OCC','FDIC','FRB'],1)
        self.assertEqual(len(a),6);self.assertEqual(len(b),3)
        self.assertTrue(all(r['exam_date'].startswith('2020') for r in a+b))
        with self.assertRaisesRegex(ValueError,'requested 4, available 3'):
            custom_draw(frame,10,[2020,2020],['OCC','FDIC','FRB'],1)
    def test_discover_occ_month_pages(self):
        links=month_links(b'<a href="/path/cra-performance-evaluations-jan-2021.html">January</a><a href="/other.html">Other</a>', 'https://www.occ.gov/')
        self.assertEqual(links,['https://www.occ.gov/path/cra-performance-evaluations-jan-2021.html'])

    def test_resume_preserves_failed_slot_and_reuses_verified_reserve(self):
        from unittest.mock import patch
        from cra_acquisition.retrieve import execute
        from cra_acquisition.__main__ import digest
        def record(name):
            return dict(pe_id=name,agency='FDIC',exam_type='small',exam_date='2020-01-01')
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            root=Path(d); (root/'reports').mkdir()
            verified=root/'reserve.pdf'; verified.write_bytes(b'fixture'); verified.chmod(0o444)
            plan=dict(run_id='resume',pilot=False,years=[2020,2020],named=[],
                      initial_draw=[record('first')],reserves=[record('reserve')],
                      unresolved=[],scan_target=0)
            progress={}
            with patch('cra_acquisition.retrieve.acquire',side_effect=[
                dict(status='unavailable'),
                dict(status='verified',sha256=digest(b'fixture'),path='reserve.pdf',scan_status='text_based')
            ]) as get:
                execute(root,plan,progress,None,{},1)
                self.assertFalse(progress['complete'])
                execute(root,plan,progress,None,{},1)
                self.assertTrue(progress['complete'])
                execute(root,plan,progress,None,{},1)
                self.assertEqual(get.call_count,2)
            self.assertEqual(progress['replacements'],[dict(old='first',new='reserve',reason='unavailable')])
