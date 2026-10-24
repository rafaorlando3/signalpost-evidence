import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import cli

ORG='810034882'
class R5Cli(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
 def call(self, flags):
  out=self.root/'run.jsonl'
  with contextlib.redirect_stderr(io.StringIO()) as err:
   code=cli.main(['--orgs',ORG,'--output',str(out),'--cache',str(self.root/'cache'),*flags])
  return code,out,err.getvalue()
 def result(self):
  row=cli.failed(ORG,'fixture');row['run']['terminal_status']='completed';row['errors']=[]
  row['claims']=[{'field':'legal_name','value':'Fixture AS','availability':'available','evidence_ids':['e']}]
  row['evidence']=[{'id':'e','source_url':'https://example.test/legal','retrieved_at':'2026-10-23T00:00:00Z','content_sha256':'a'*64}]
  return row
 def test_search_missing_key_fails_before_output(self):
  with patch.dict(os.environ,{},clear=True),patch('cli.collect',side_effect=AssertionError('must not collect')):
   code,out,err=self.call(['--search','tavily-free','--search-free-credit-limit','100'])
  self.assertEqual(code,1);self.assertFalse(out.exists());self.assertIn('TAVILY_API_KEY',err)
 def test_search_never_exceeds_confirmed_credit_cap(self):
  with patch.dict(os.environ,{'TAVILY_API_KEY':'test-only-not-real'}),patch('cli.collect',side_effect=AssertionError('must not collect')):
   code,out,err=self.call(['--search','tavily-free','--search-credit-limit','101','--search-free-credit-limit','100'])
  self.assertEqual(code,1);self.assertFalse(out.exists());self.assertIn('free credits',err)
 def test_free_search_arguments_and_unknown_cost_are_transparent(self):
  row=self.result();row['operations']['third_party_cost_usd']=None
  row['discovery']={'request_attempts':3,'credits_reported':3}
  def collect(command,*args,**kwargs):
   self.assertEqual(command[command.index('--search')+1],'tavily-free')
   self.assertEqual(command[command.index('--search-credit-limit')+1],'300')
   self.assertEqual(command[command.index('--search-free-credit-limit')+1],'300')
   self.assertTrue(kwargs['paid_search'])
   return [row],{'collector_exit':0}
  with patch.dict(os.environ,{'TAVILY_API_KEY':'test-only-not-real'}),patch('cli.collect',side_effect=collect):
   code,out,err=self.call(['--search','tavily-free','--search-credit-limit','300','--search-free-credit-limit','300'])
  self.assertEqual(code,0,err)
  s=json.loads(out.with_suffix('.summary.json').read_text());self.assertIsNone(s['third_party_cost_usd']);self.assertFalse(s['paid_fallback'])
  self.assertEqual(s['search'],'tavily-free');self.assertEqual(s['review']['state'],'completed')
  self.assertEqual(s['search_request_attempts'],3);self.assertEqual(s['search_basic_credit_upper_bound'],3)
  self.assertEqual(s['review']['count'],1);self.assertTrue(Path(s['review']['html_path']).is_file())
  self.assertEqual(json.loads(out.read_text())['_cli']['search'],'tavily-free')
 def test_existing_review_path_refused_before_collection(self):
  dest=self.root/'run.review';dest.mkdir();(dest/'sentinel').write_text('keep')
  with patch('cli.collect',side_effect=AssertionError('must not collect')):code,out,err=self.call([])
  self.assertEqual(code,1);self.assertFalse(out.exists());self.assertEqual((dest/'sentinel').read_text(),'keep')
 def test_readable_html_never_executes_source_data(self):
  from report import build
  marker='</script><script>alert(1)</script>&'
  text=build([{'probe':marker}]);self.assertNotIn(marker,text)
  payload=text.split('<script id="data" type="application/json">',1)[1].split('</script>',1)[0]
  self.assertEqual(json.loads(payload),[{'probe':marker}])

 def test_interrupted_search_never_reports_unknown_usage_as_zero(self):
  row=cli.failed(ORG,'deadline',interrupted=True)
  with patch.dict(os.environ,{'TAVILY_API_KEY':'test-only-not-real'}),patch('cli.execute',return_value=([row],{'collector_exit':-9,'wall_clock_timeout':True,'synthesized_failures':1})):
   code,out,err=self.call(['--search','tavily-free','--search-credit-limit','100','--search-free-credit-limit','100'])
  self.assertEqual(code,2,err)
  s=json.loads(out.with_suffix('.summary.json').read_text());self.assertIsNone(s['search_request_attempts']);self.assertFalse(s['search_attempts_complete']);self.assertEqual(s['search_basic_credit_upper_bound'],3);self.assertIsNone(s['third_party_cost_usd'])
  r=json.loads(out.read_text());self.assertIsNone(r['operations']['third_party_cost_usd']);self.assertIsNone(r['discovery']['request_attempts'])
