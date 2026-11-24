import tempfile
from pathlib import Path
import unittest
from cra_acquisition.provider import Budget
class BudgetTests(unittest.TestCase):
 def test_cap_and_ambiguous_reservation(self):
  with tempfile.TemporaryDirectory() as d:
   b=Budget(Path(d)/'ledger.sqlite',1)
   n=b.reserve('a',.8)
   with self.assertRaises(ValueError):b.reserve('b',.3)
   b.settle(n,.1);b.reserve('b',.3)
 def test_attempt_limit_persists(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'ledger.sqlite';b=Budget(p)
   for _ in range(3):b.reserve('a',.01)
   with self.assertRaises(ValueError):Budget(p).reserve('a',.01)
