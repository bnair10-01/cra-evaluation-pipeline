import json
from pathlib import Path
import tempfile
import unittest
from cra_acquisition.__main__ import occ_rows, fdic_rows, filename, matches, manifest, connect, download, discover

class AcquisitionTests(unittest.TestCase):
    def test_occ_metadata_and_link(self):
        body=b'<table><tr><td>00123</td><td>The Example Bank</td><td>City</td><td>HI</td><td>08/03/2020</td><td>Satisfactory</td><td><a href="/static/example.pdf">Small</a></td></tr></table>'
        r=occ_rows(body,'https://www.occ.gov/list')[0]
        self.assertEqual(r['agency_id'],'00123');self.assertEqual(r['exam_date'],'2020-08-03')
        self.assertEqual(filename(r),'OCC_00123_2020-08-03.pdf')
        self.assertEqual(r['pdf_url'],'https://www.occ.gov/static/example.pdf')
        self.assertTrue(matches(r,dict(agency='OCC',institution_name='Example Bank',exam_year=2020)))
        self.assertFalse(matches(r,dict(agency='OCC',institution_name='Example Bank',exam_year=2021)))
    def test_fdic_never_uses_release_or_filename_as_exam_date(self):
        b=json.dumps({'status':'success','data':[dict(ORG_CERT_NUM=123,INST_FIN_LGL_NME='Example',EXM_CRA_PUB_DTE='12/01/2024',SYS_EXTRN_FILE_ID='2024/00123_240722.PDF')]}).encode()
        r=fdic_rows(b,'https://crapes.fdic.gov/api/getSearchResults','https://crapes.fdic.gov/publish/')[0]
        self.assertIsNone(r['exam_date']);self.assertEqual(r['release_date'],'2024-12-01')
        with self.assertRaises(ValueError):filename(r)
    def test_fdic_truncation_is_not_silent(self):
        with self.assertRaises(ValueError):fdic_rows(json.dumps({'status':'success','data':[{}]*500}).encode(),'','')
    def test_invalid_listing(self):
        with self.assertRaises(ValueError):occ_rows(b'<html>Error</html>','https://www.occ.gov')
    def test_manifest_ambiguity(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            p=Path(d)/'manifest.json';p.write_text(json.dumps({'requests':[dict(request_id='a',agency='OCC',institution_name='Example')]}))
            with self.assertRaises(ValueError):manifest(p)
    def test_download_resume_collision_invalid_pdf(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            root=Path(d);(root/'schemas').mkdir();(root/'data').mkdir()
            source=Path(__file__).resolve().parents[1]/'schemas/acquisition_schema.sql'
            (root/'schemas/acquisition_schema.sql').write_bytes(source.read_bytes());c=connect(root)
            req=dict(request_id='a',agency='OCC',institution_name='Example',exam_year=2020)
            c.execute("INSERT INTO inventory(pe_id,agency,agency_id,institution_name,exam_date,pdf_url,source_url,snapshot_path,raw_metadata_json,retrieved_at) VALUES ('p','OCC','00123','Example','2020-01-01','https://www.occ.gov/x.pdf','source','snapshot','{}','now')")
            c.execute("INSERT INTO requests VALUES (?,?,?,'p',NULL,'now')",('a',json.dumps(req,sort_keys=True),'resolved'));c.commit()
            class Fake:
                body=b'<html>error</html>'
                calls=0
                def fetch(self,url):self.calls+=1;return self.body,url,200,{}
            fake=Fake();download(root,c,fake,[req]);self.assertEqual(c.execute('SELECT download_status FROM inventory').fetchone()[0],'failed')
            self.assertFalse(list((root/'data').rglob('*.pdf')))
            fake.body=b'%PDF-1.4\nsynthetic fixture';download(root,c,fake,[req]);target=root/'data/raw/OCC/OCC_00123_2020-01-01.pdf'
            self.assertEqual(target.read_bytes(),fake.body);self.assertEqual(target.stat().st_mode & 0o222,0)
            calls=fake.calls;download(root,c,fake,[req]);self.assertEqual(fake.calls,calls)
            target.chmod(0o644);target.write_bytes(b'%PDF-changed');download(root,c,fake,[req]);self.assertEqual(target.read_bytes(),b'%PDF-changed');self.assertEqual(fake.calls,calls)
            c.close()
    def test_manifest_change_requires_rediscovery(self):
        # Criteria matching is deliberately exact; names alone cannot select a record.
        row=dict(agency='OCC',institution_name='Example',agency_id='001',city='A',state='HI',exam_date=None)
        self.assertFalse(matches(row,dict(agency='OCC',institution_name='Example',exam_year=2024)))

if __name__=='__main__':unittest.main()

class DiscoveryTests(unittest.TestCase):
    def test_repeat_discovery_and_ambiguous_matches(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            root=Path(d);(root/'schemas').mkdir();(root/'data').mkdir()
            source=Path(__file__).resolve().parents[1]/'schemas/acquisition_schema.sql'
            (root/'schemas/acquisition_schema.sql').write_bytes(source.read_bytes());c=connect(root)
            class Fake:
                two=False
                def fetch(self,url,data=None):
                    row='<tr><td>001</td><td>Example Bank</td><td>A</td><td>HI</td><td>01/01/2020</td><td>Satisfactory</td><td><a href="/a.pdf">Small</a></td></tr>'
                    if self.two: row+=row.replace('001','002').replace('/a.pdf','/b.pdf')
                    return ('<table>'+row+'</table>').encode(),url,200,{}
                def snapshot(self,*args):return 'fixture'
            f=Fake();r=dict(request_id='example',agency='OCC',institution_name='Example Bank',exam_year=2020,listing_urls=['https://www.occ.gov/list'])
            config={'agencies':{'OCC':{}}}
            discover(root,c,f,[r],config);discover(root,c,f,[r],config)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM inventory').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT status FROM requests').fetchone()[0],'resolved')
            f.two=True;discover(root,c,f,[r],config)
            chosen=c.execute('SELECT i.agency_id FROM requests r JOIN inventory i ON i.pe_id=r.selected_pe_id').fetchone()
            self.assertEqual(chosen[0],'001')
            self.assertIn('selected first',c.execute('SELECT error FROM requests').fetchone()[0])
            discover(root,c,f,[dict(r,location='a, hi')],config)
            self.assertEqual(c.execute('SELECT status FROM requests').fetchone()[0],'ambiguous')
            self.assertIsNone(c.execute('SELECT selected_pe_id FROM requests').fetchone()[0])
            c.close()
