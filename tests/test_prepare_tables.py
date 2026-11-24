import hashlib,tempfile,unittest
from decimal import Decimal
from pathlib import Path
from pdfs import make_pdf,TEXT
from cra_acquisition.prepare import prepare_pdf,classify,text_quality
from cra_acquisition import segment
from cra_acquisition.tables import read_row,read_table,category,parse_token

class PrepareTests(unittest.TestCase):
    def setUp(self):
        self.d=tempfile.TemporaryDirectory(ignore_cleanup_errors=True);self.addCleanup(self.d.cleanup);self.dir=Path(self.d.name)
    def test_every_page_class_and_labels(self):
        p=make_pdf(self.dir/'Ünï cøde spaced name.pdf',[dict(kind='text',lines=TEXT),dict(kind='image'),dict(kind='ocr',lines=TEXT),dict(kind='blank'),dict(kind='landscape',lines=['x'*30])],labels=[(0,'ROMAN_LOWER',1)])
        b=prepare_pdf(p)
        self.assertEqual([x['page_class'] for x in b['pages']],['text','image_no_text','ocr_layer','blank','text'])
        self.assertEqual([x['printed_label_pdf'] for x in b['pages']],['i','ii','iii','iv','v'])
        self.assertEqual(b['pages'][4]['width'],792.0);self.assertTrue(b['pages'][1]['needs_review'] and b['pages'][2]['needs_review'])
        self.assertFalse(b['pages'][0]['needs_review']);self.assertEqual(b['page_count'],5)
        self.assertEqual(b['sha256'],hashlib.sha256(p.read_bytes()).hexdigest())
    def test_checksum_mismatch_blocks(self):
        p=make_pdf(self.dir/'a.pdf',[dict(lines=TEXT)])
        with self.assertRaises(ValueError):prepare_pdf(p,'0'*64)
    def test_encrypted_truncated_html_and_empty_fail_loudly(self):
        e=make_pdf(self.dir/'e.pdf',[dict(lines=TEXT)],encrypt='pw')
        t=self.dir/'t.pdf';t.write_bytes(make_pdf(self.dir/'full.pdf',[dict(lines=TEXT)]).read_bytes()[:200])
        h=self.dir/'h.pdf';h.write_text('<html><body>Service unavailable</body></html>')
        z=self.dir/'z.pdf';z.write_bytes(b'')
        for bad in (e,t,h,z):
            with self.assertRaises(Exception,msg=bad.name):prepare_pdf(bad)
    def test_leading_zero_ids_survive_as_text(self):
        p=make_pdf(self.dir/'z.pdf',[dict(lines=['Certificate Number: 00123'])])
        self.assertIn('00123',prepare_pdf(p)['pages'][0]['text'])
    def test_classify_matrix(self):
        self.assertEqual(classify(100,50,False,False,False),'text');self.assertEqual(classify(5,5,False,False,False),'sparse')
        self.assertEqual(classify(0,0,False,True,False),'blank');self.assertEqual(classify(0,0,False,True,True),'no_text_content')
        self.assertEqual(classify(0,0,False,False,False),'no_text_content');self.assertEqual(classify(80,60,True,False,True),'ocr_layer')
    def test_quality_flags(self):
        self.assertIn('garbled_glyphs',text_quality('(cid:12)'*30))
        self.assertIn('very_long_unspaced_run',text_quality('a'*80))
        self.assertEqual(text_quality('The bank made loans in the area for the test of lending and income. '*8),[])
        self.assertIn('low_word_quality',text_quality(' '.join(['qzx','vwp','kjh','mnb']*30)))

def fake_bundle(pages):
    return dict(sha256='h',parser=dict(fingerprint='f'),page_count=len(pages),
                pages=[dict(page=i,text='\n'.join(l),lines=l,char_count=sum(len(x) for x in l),tables=[],needs_review=False,page_class='text',
                            printed_label_pdf=None,printed_label_guess=None) for i,l in enumerate(pages,1)])

class SegmentTests(unittest.TestCase):
    def test_all_pages_covered_even_without_headings(self):
        b=fake_bundle([['PUBLIC DISCLOSURE'],['random words'],['more random words']])
        s=segment.segments(b);self.assertTrue(segment.covered(s,3))
    def test_headings_and_carry(self):
        b=fake_bundle([['cover'],['Scope of Evaluation','text'],['more scope text'],['Description of Institution'],['Appendix A'],['x']])
        kinds=[(s['kind'],s['first'],s['last']) for s in segment.segments(b)]
        self.assertEqual(kinds,[('cover',1,1),('scope',2,3),('institution',4,4),('appendix',5,6)])
    def test_windows_bounded_with_overlap_and_oversize_page(self):
        b=fake_bundle([['x'*400]]*10+[['y'*5000]])
        w=segment.windows(b,list(range(1,12)),max_chars=1500,overlap=1)
        self.assertTrue(all(len(x)>=1 for x in w));self.assertEqual(sorted({p for x in w for p in x}),list(range(1,12)))
        self.assertTrue(any(11 in x and len(x)<=2 for x in w))   # oversize page is never truncated
        for a,c in zip(w,w[1:]):self.assertIn(a[-1],c)
    def test_table_pages_detection(self):
        b=fake_bundle([['prose only'],['Table 11 - Borrower','Low 5 10.0 12.0 30.0'],['1 2 3 4','5 6 7 8','9 10 11 12','1 2 3','4 5 6']])
        self.assertEqual(segment.table_pages(b),[2,3])

class TableTests(unittest.TestCase):
    def test_token_forms(self):
        self.assertEqual(parse_token('(1,234)')[0],Decimal(-1234));self.assertEqual(parse_token('-5.5%')[0],Decimal('-5.5'))
        self.assertIsNone(parse_token('--')[0]);self.assertIsNone(parse_token('N/A')[0]);self.assertEqual(parse_token('0')[0],0)
        self.assertEqual(parse_token('$1,250')[0],1250);self.assertEqual(parse_token('12.50%')[1],'12.50%')
    def test_row_reads_label_and_values(self):
        r=read_row('Low Income 12 $1,200 10.5% 8.0%',4);self.assertEqual(r['label'],'Low Income');self.assertEqual(len(r['values']),4)
        self.assertIsNone(read_row('Low 12 10',4));self.assertIsNone(read_row('text only',1))
        self.assertIsNone(read_row('Low 12 abc 10',2))   # stray text between numbers: refuse to guess
    def test_dash_is_not_zero_and_zero_is_kept(self):
        r=read_row('Moderate 0 -- 7.5',3);self.assertEqual(r['values'][0][0],0);self.assertIsNone(r['values'][1][0])
    def test_categories(self):
        for label,expect in (('Low Income','low'),('Moderate-income','moderate'),('Upper','upper'),('Middle Income Tracts','middle'),
                             ('Not Available','not available'),('Unknown','not available'),('$1 Million or Less','at or below $1 million'),
                             ('Over $1 Million','above $1 million'),('Total',None),('Revenue Not Available','not available'),('Revenues <= $1 Million','at or below $1 million'),('Revenues > $1 Million','above $1 million'),('Unknown Revenue','not available')):
            self.assertEqual(category(label),expect,label)
    def test_read_table_rejects_and_reports(self):
        lines=['Table 1','Low 5 10.0','Moderate 6 12.0','Total 11 22.0','Upper 7','Footer text 5 5 5']
        rows,rej=read_table(lines,2,6,['bank_count','bank_count_pct'])
        self.assertEqual([r['category'] for r in rows],['low','moderate'])
        reasons={x['reason'] for x in rej};self.assertTrue(any('not a recognized category' in x for x in reasons) or any('does not match' in x for x in reasons))
        rows2,rej2=read_table(lines,1,99,['bank_count','bank_count_pct'])
        self.assertTrue(any(x['reason']=='line out of range' for x in rej2))

if __name__=='__main__':unittest.main()
