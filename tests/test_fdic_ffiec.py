import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from cra_acquisition.__main__ import fdic_ffiec_dates, fdic_rows, filename, use_fdic_ffiec_date


class FfiecDateTests(unittest.TestCase):
    def test_fdic_date_requires_unique_same_certificate_and_date(self):
        body = json.dumps({'status':'success','data':[
            {'ORG_CERT_NUM':8250,'INST_FIN_LGL_NME':'Bank of Wiggins',
             'EXM_CRA_PUB_DTE':'12/01/2024','SYS_EXTRN_FILE_ID':'2024/8250_240722.PDF'}
        ]}).encode()
        row = fdic_rows(body,'','https://crapes.fdic.gov/publish/')[0]
        with TemporaryDirectory() as tmp:
            export = Path(tmp)/'crarating.txt'
            matching = '08250\t3\t20241201\tBANK OF WIGGINS\tWIGGINS\tMS\t192262\t2\t1\n'
            wrong_agency = matching.replace('\t3\t','\t1\t')
            wrong_date = matching.replace('20241201','20240722')
            for source in (wrong_agency + wrong_date, matching * 2):
                export.write_text(source)
                if source == wrong_agency + wrong_date:
                    export.write_text(source + '1\t3\t20241201\tOTHER\tX\tMS\t1\t2\t1\n')
                use_fdic_ffiec_date(row,fdic_ffiec_dates(export))
                self.assertIsNone(row['exam_date'])
            export.write_text(wrong_agency+wrong_date+matching)
            use_fdic_ffiec_date(row,fdic_ffiec_dates(export))
            self.assertEqual(filename(row),'FDIC_8250_2024-12-01.pdf')
            self.assertEqual(row['release_date'],'2024-12-01')
            source = json.loads(row['raw_metadata_json'])['ffiec_date_source']
            self.assertEqual(source['line'],3)
            self.assertFalse(source['verified_against_pdf'])
