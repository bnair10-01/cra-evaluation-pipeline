import unittest
from cra_acquisition.score import measure
class ScoreTests(unittest.TestCase):
    def test_wrong_context_counts_as_addition_and_omission(self):
        r=dict(pe_id='p',table='table_e_examiner_conclusions',context='mortgage|area A',field='label_verbatim',value='good',critical=True)
        s=measure([r],[dict(r,context='mortgage|area B')],{'p'})
        self.assertEqual(s['conclusion_precision'],0)
        self.assertEqual(s['conclusion_recall'],0)
        self.assertEqual(s['critical_exact'],0)
