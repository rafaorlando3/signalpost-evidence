import copy,json,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode
from agent import Fetcher,Page,digest,encode,research
from free_search import AnonymousSearch
from audit import audit
import test_pipeline as pipeline_fixtures
from test_pipeline import save,BASE,ORG
DATA={'organisasjonsnummer':ORG,'navn':'Example Plant AS'}
ENDPOINT='https://api.mwmbl.org/api/v2/search/?'+urlencode({'q':'Example Plant'})
class Fake:
 def __init__(self,path,payload,status=200):self.directory=Path(path);self.replay=False;self.fresh=True;self.requests=0;self.limit=20;self.end=time.monotonic()+60;self.payload=payload;self.status=status;self.urls=[]
 def get(self,url):
  self.urls.append(url);self.requests+=1
  return {'url':url,'status':'available' if self.status==200 else 'blocked','status_code':self.status,'retrieved_at':'2026-11-01T00:00:00Z','content_sha256':'f'*64,'json':self.payload}
def payload(results):return {'query':'Example Plant','results':results,'monthly_usage':None,'monthly_limit':None}
class FreeSearch(unittest.TestCase):
 def test_public_anonymous_url_only_no_secret_or_billing(self):
  with tempfile.TemporaryDirectory() as d,patch.dict('os.environ',{'MWMBL_API_KEY':'MUST_NOT_BE_USED'}):
   f=Fake(d,payload([{'url':'https://own-brand.test/contact','title':'Example Plant AS','content':'We are Example Plant AS'}]));r=AnonymousSearch().discover(DATA,f)
   self.assertEqual(r,[{'url':'https://own-brand.test/','hints':['https://own-brand.test/contact']}]);self.assertEqual(f.urls,[ENDPOINT]);self.assertEqual(f.public_search_discovery['paid_cost_usd'],0);self.assertIsNone(f.public_search_discovery['monthly_usage']);self.assertNotIn('MUST_NOT_BE_USED',json.dumps(f.public_search_discovery))
 def test_429_stops_the_shared_provider_without_other_host_or_account(self):
  with tempfile.TemporaryDirectory() as d:
   p=AnonymousSearch();a=Fake(d,None,429);b=Fake(d,payload([]));self.assertFalse(p.discover(DATA,a));self.assertFalse(p.discover(DATA,b));self.assertEqual(a.urls,[ENDPOINT]);self.assertFalse(b.urls);self.assertEqual(p.attempts,1)
 def test_run_cap_and_company_budget_prevent_calls(self):
  with tempfile.TemporaryDirectory() as d:
   p=AnonymousSearch(1);a=Fake(d,payload([]));b=Fake(d,payload([]));p.discover(DATA,a);p.discover(DATA,b);self.assertFalse(b.urls)
   f=Fake(d,payload([]));f.requests=18;self.assertFalse(AnonymousSearch().discover(DATA,f));self.assertFalse(f.urls)
 def test_missing_replay_does_not_consume_or_access_network(self):
  with tempfile.TemporaryDirectory() as d:
   f=Fake(d,payload([]));f.replay=True;p=AnonymousSearch();self.assertFalse(p.discover(DATA,f));self.assertFalse(f.urls);self.assertEqual(p.attempts,0)
 def test_empty_invalid_and_foreign_results_do_not_become_company_facts(self):
  for response in [payload([]),None,payload('not a list'),{'query':'another company','results':[]}]:
   with tempfile.TemporaryDirectory() as d:
    f=Fake(d,response);self.assertFalse(AnonymousSearch().discover(DATA,f))
  with tempfile.TemporaryDirectory() as d:
   f=Fake(d,payload([{'url':'https://proff.no/company','title':'Example Plant AS'},{'url':'http://user:secret@own-brand.test','title':'Example Plant AS'},{'url':'javascript:alert(1)','title':'Example Plant AS'}]));self.assertFalse(AnonymousSearch().discover(DATA,f))
 def test_result_cannot_bypass_first_party_identity(self):
  for number,expected in [(ORG,'available'),('974761076',None)]:
   with tempfile.TemporaryDirectory() as d,patch('socket.getaddrinfo',side_effect=AssertionError('network forbidden')):
    pipeline_fixtures.Pipeline().fixture(d);save(d,BASE,DATA);own='https://own-brand.test/'
    sources=[(ENDPOINT,payload([{'url':own,'title':'Example Plant AS','content':'Org.nr '+ORG}])),('https://own-brand.test/robots.txt','User-agent: *\nAllow: /'),(own,'<title>Example Plant</title><p>Manufacturing and repair services for industrial customers.</p><footer>Example Plant AS Org.nr. '+number+'</footer>')]
    for url,body in sources:
     text=json.dumps(body) if isinstance(body,dict) else body
     r={'url':url,'requested_url':url,'status':'available','status_code':200,'retrieved_at':'2026-11-01T00:00:00Z','content_sha256':digest(text.encode()),'text':text}
     if isinstance(body,dict):r['json']=body
     (Path(d)/(digest(url.encode())+'.json')).write_text(encode(r))
    row=research({'organisation_number':ORG},Fetcher(d,replay=True,public_search=AnonymousSearch()));c={x['field']:x for x in row['claims']}
    if expected:self.assertEqual(c['website.verified_url']['value'],own);self.assertTrue(audit([row],d)['passed'])
    else:self.assertNotEqual(c['website.verified_url']['availability'],'available')
