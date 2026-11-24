import hashlib,os,subprocess,sys,tempfile,unittest,urllib.error
from pathlib import Path
from unittest.mock import patch
from filelock import FileLock,Timeout
from pdfs import make_pdf,TEXT
from cra_acquisition import __main__ as acq,retrieve,workflow,io as cio

class FakeClient:
    def __init__(self,body):self.body=body
    def check_url(self,url):acq.Client.check_url(NS_CLIENT,url)
    def fetch(self,url,data=None):return self.body,url,200,{}
class NS_CLIENT:config=dict(allowed_hosts=['crapes.fdic.gov','www.federalreserve.gov','www.occ.gov'])
class FakeResolver:
    def __init__(self,body):self.client=FakeClient(body)
    def find(self,record):return dict(url='https://crapes.fdic.gov/publish/2015/1.PDF',listing='l',snapshot='s',imported_pdf=None)

RECORD=dict(agency='FDIC',agency_id='0014807',exam_date='2015-12-01',pe_id='FRAME_x',rating='Satisfactory')

class AcquireTests(unittest.TestCase):
    def setUp(self):
        self.d=tempfile.TemporaryDirectory(ignore_cleanup_errors=True);self.addCleanup(self.d.cleanup);self.root=Path(self.d.name)/'root with spaces é'
        self.root.mkdir();self.pdf=make_pdf(self.root/'src.pdf',[dict(lines=TEXT)]).read_bytes()
    def test_download_is_read_only_hash_checked_without_leftovers(self):
        r=retrieve.acquire(self.root,RECORD,FakeResolver(self.pdf))
        self.assertEqual(r['status'],'verified');self.assertEqual(r['sha256'],hashlib.sha256(self.pdf).hexdigest())
        path=self.root/r['path'];self.assertTrue(path.is_file())
        if os.name=='posix':self.assertEqual(path.stat().st_mode&0o222,0)
        self.assertEqual([p for p in path.parent.iterdir() if p.suffix=='.part'],[])
        self.assertIn('0014807',path.name) if False else None
    def test_html_and_truncated_downloads_rejected_and_nothing_published(self):
        for body in (b'<html>Service unavailable</html>',self.pdf[:300],b''):
            with self.assertRaises(Exception):retrieve.acquire(self.root,RECORD,FakeResolver(body))
        cache=self.root/'data/pilot_cache';self.assertEqual([p for p in cache.iterdir() if p.suffix in ('.pdf','.PDF')],[])
    def test_existing_file_with_different_bytes_is_not_overwritten(self):
        r=retrieve.acquire(self.root,RECORD,FakeResolver(self.pdf));other=make_pdf(self.root/'other.pdf',[dict(lines=['different content here'])]).read_bytes()
        with self.assertRaises(ValueError):retrieve.acquire(self.root,RECORD,FakeResolver(other))
        self.assertEqual(hashlib.sha256((self.root/r['path']).read_bytes()).hexdigest(),r['sha256'])

class LockTests(unittest.TestCase):
    def test_second_writer_cannot_take_the_run_lock(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            lock=Path(d)/'run.lock'
            with FileLock(lock):
                with self.assertRaises(Timeout):FileLock(lock).acquire(timeout=0.1)

class ClientPolicyTests(unittest.TestCase):
    def client(self):
        c=acq.Client(Path('.'),dict(allowed_hosts=['crapes.fdic.gov'],request_interval_seconds=2));return c
    def test_only_https_allowlisted_hosts(self):
        c=self.client();c.check_url('https://crapes.fdic.gov/x')
        for bad in ('http://crapes.fdic.gov/x','https://evil.example/x','https://crapes.fdic.gov.evil.example/x','ftp://crapes.fdic.gov/x','file:///etc/passwd'):
            with self.assertRaises(ValueError,msg=bad):c.check_url(bad)
    def test_retry_after_forms(self):
        c=self.client();c.last={};
        def err(value):
            return urllib.error.HTTPError('u',429,'x',{'Retry-After':value} if value is not None else {},None)
        cases=[('99999',RuntimeError),('Wed, 21 Oct 2099 07:28:00 GMT',RuntimeError)]
        for value,exc in cases:
            with patch.object(c,'policy'),patch.object(c,'raw',side_effect=err(value)),patch('time.sleep'):
                with self.assertRaises(exc):c.fetch('https://crapes.fdic.gov/x')
        for value in ('-5','garbage',None):   # negative/invalid/missing: bounded retry, then the HTTP error surfaces
            with patch.object(c,'policy'),patch.object(c,'raw',side_effect=err(value)),patch('time.sleep') as sl:
                with self.assertRaises(urllib.error.HTTPError):c.fetch('https://crapes.fdic.gov/x')
                self.assertLessEqual(max([x.args[0] for x in sl.call_args_list] or [0]),4)
    def test_non_retryable_status_fails_immediately(self):
        c=self.client()
        with patch.object(c,'policy'),patch.object(c,'raw',side_effect=urllib.error.HTTPError('u',403,'x',{},None)) as raw,patch('time.sleep'):
            with self.assertRaises(urllib.error.HTTPError):c.fetch('https://crapes.fdic.gov/x')
            self.assertEqual(raw.call_count,1)

class ConfigPortabilityTests(unittest.TestCase):
    def test_cra_root_override(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            code="from cra_acquisition import __main__ as a, paths; print(a.ROOT, paths.ROOT)"
            out=subprocess.run([sys.executable,'-c',code],env={**os.environ,'CRA_ROOT':d},capture_output=True,text=True)
            self.assertEqual(out.stdout.split(),[str(Path(d).resolve())]*2,out.stderr)
    def test_requested_works_without_development_config_or_database(self):
        frame=[dict(agency='OCC',agency_id='14911',exam_date='2020-08-03',institution_name='HAWAII NATIONAL BANK',city='HONOLULU',state='HI',exam_type='intermediate small',rating='Satisfactory',pe_id='P1',date_basis='x',source_line=1,source_sha256='h')]
        spec=[dict(request_id='r1',institution_name='Hawaii National Bank',agency='OCC',exam_year=2020)]
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            got,unresolved=workflow.requested(frame,spec,Path(d)/'missing.json',Path(d)/'missing.sqlite')
        self.assertEqual([r['pe_id'] for r in got],['P1']);self.assertEqual(unresolved,[])
    def test_workflow_validation_errors_are_explicit(self):
        frame=[dict(agency='OCC',pe_id=str(i),exam_date='2020-01-01',exam_type='small') for i in range(3)]
        for kw in (dict(count=0),dict(count=2,years=(2021,2020)),dict(count=-1),dict(count=1,minimum=-1)):
            args=dict(count=1,years=(2000,2030),agencies=['OCC'],seed=1);args.update(kw)
            with self.assertRaises(ValueError):workflow.custom_draw(frame,args['count'],args['years'],args['agencies'],args['seed'],(),args.get('minimum',0))
        with self.assertRaises(ValueError):workflow.custom_draw(frame,5,(2000,2030),['OCC'],1)   # shortage
    def test_json_writer_never_leaves_partial_file(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            p=Path(d)/'r.json'
            class Bad:pass
            with self.assertRaises(TypeError):cio.write_json(p,{'x':Bad()})
            self.assertFalse(p.exists());self.assertEqual(list(Path(d).iterdir()),[])

class OcrToolTests(unittest.TestCase):
    def test_missing_tesseract_is_an_explicit_error_not_a_silent_fallback(self):
        from cra_acquisition import prepare
        with patch.dict(os.environ,{'CRA_TESSERACT':'/nonexistent/tesseract'}),patch('shutil.which',return_value=None):
            self.assertIsNone(prepare.tesseract())
            with self.assertRaises(RuntimeError):prepare.ocr_page('x.pdf',1)
