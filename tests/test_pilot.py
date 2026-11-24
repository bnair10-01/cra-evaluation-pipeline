import unittest
from cra_acquisition.pilot import draw,replace,QUOTAS,ERAS,TYPES
class PilotTests(unittest.TestCase):
 def frame(self):
  return [dict(pe_id=f'{a}-{i}-{t}-{n}',agency=a,institution_name='Example',exam_date=f'{start}-01-01',exam_type=t) for a in QUOTAS for i,(start,end) in enumerate(ERAS) for t in TYPES for n in range(8)]
 def test_deterministic_balanced(self):
  f=self.frame();s,r=draw(f);self.assertEqual(s,draw(list(reversed(f)))[0]);self.assertEqual(len(s),40);self.assertEqual(len({x['pe_id'] for x in s}),40)
  for a,q in QUOTAS.items():self.assertEqual(sum(x['agency']==a for x in s),sum(q))
 def test_shortfall(self):
  with self.assertRaises(ValueError):draw([])
 def test_exclusion(self):
  f=self.frame();s,r=draw(f,exclude=[f[0]['pe_id']]);self.assertNotIn(f[0]['pe_id'],[x['pe_id'] for x in s])
 def test_replacement(self):
  s,r=draw(self.frame());n=replace(s,r,s[0]['pe_id'],'unavailable');self.assertEqual(n['agency'],s[0]['agency']);self.assertEqual(n['exam_type'],s[0]['exam_type'])
 def test_scan_replacement_requires_confirmed_scan(self):
  s,r=draw(self.frame())
  with self.assertRaises(ValueError):replace(s,r,s[0]['pe_id'],'scan_quota')

class RequestTests(unittest.TestCase):
 def test_name_year_without_identifier(self):
  from cra_acquisition.collect import ranked
  f=[dict(pe_id='a',agency='FDIC',institution_name='The Example Bank',exam_date='2020-01-01'),dict(pe_id='b',agency='FDIC',institution_name='Example Bank',exam_date='2021-01-01')]
  self.assertEqual([x['record']['pe_id'] for x in ranked(dict(institution_name='Example Bank',year=2020),f)],['a'])
 def test_same_name_not_collapsed(self):
  from cra_acquisition.collect import ranked
  f=[dict(pe_id=str(n),agency='FDIC',institution_name='Example Bank',exam_date='2020-01-01') for n in range(2)]
  self.assertEqual(len(ranked(dict(institution_name='Example Bank',year=2020),f)),2)
