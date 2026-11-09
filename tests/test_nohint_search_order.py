import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from agent import Fetcher,Page,research,digest,encode
import test_pipeline as fixtures
from test_pipeline import save,BASE,ORG

class Provider:
    def __init__(self,events,found=False):self.events=events;self.calls=0;self.found=found
    def discover(self,data,fetcher):
        self.calls+=1;self.events.append('search')
        return [{'url':'https://unusual-trade.test/','hints':[]}] if self.found else []

def webpage(folder,url,body):
    value={'url':url,'requested_url':url,'status':'available','status_code':200,'retrieved_at':'2026-11-01T00:00:00Z','content_sha256':digest(body.encode()),'text':body}
    (Path(folder)/(digest(url.encode())+'.json')).write_text(encode(value))

class NohintSearchOrder(unittest.TestCase):
    def run_case(self,data,found=False,foreign=False):
        events=[];provider=Provider(events,found)
        with tempfile.TemporaryDirectory() as directory,patch('socket.getaddrinfo',side_effect=AssertionError('offline only')):
            fixtures.Pipeline().fixture(directory);save(directory,BASE,{'organisasjonsnummer':ORG,'navn':'Example Plant AS',**data})
            number='974761076' if foreign else ORG
            for url in ['https://unusual-trade.test/','https://official.test/','https://email.test']:
                webpage(directory,url.rstrip('/')+'/robots.txt','User-agent: *\nAllow: /')
                webpage(directory,url,'<title>Example Plant</title><p>Manufacturing tools and industrial services</p><footer>Example Plant AS Org.nr. '+number+'</footer>')
            f=Fetcher(directory,replay=True,public_search=provider);original=f.get
            def get(url,**kwargs):events.append(url);return original(url,**kwargs)
            with patch.object(f,'get',side_effect=get):row=research({'organisation_number':ORG},f)
        return events,provider,row
    def test_missing_website_search_precedes_guesses_and_runs_once(self):
        events,p,row=self.run_case({})
        self.assertEqual(p.calls,1)
        self.assertLess(events.index('search'),events.index('https://exampleplant.no/'))
    def test_successful_declared_website_keeps_path_without_search(self):
        events,p,row=self.run_case({'hjemmeside':'https://official.test/'})
        self.assertEqual(p.calls,0)
        self.assertEqual(next(c['value'] for c in row['claims'] if c['field']=='website.verified_url'),'https://official.test/')
    def test_successful_email_path_keeps_path_without_search(self):
        events,p,row=self.run_case({'epostadresse':'office@email.test'})
        self.assertEqual(p.calls,0)
        self.assertEqual(next(c['value'] for c in row['claims'] if c['field']=='website.verified_url'),'https://email.test')
    def test_search_lead_requires_independent_matching_org(self):
        for foreign in [False,True]:
            events,p,row=self.run_case({},True,foreign)
            c=next(c for c in row['claims'] if c['field']=='website.verified_url')
            self.assertEqual(p.calls,1)
            self.assertEqual(c['availability']=='available',not foreign)
            if not foreign:self.assertEqual(c['value'],'https://unusual-trade.test/')
    def test_empty_search_falls_through_without_claim_from_query(self):
        events,p,row=self.run_case({})
        self.assertTrue(any('exampleplant.no' in e for e in events))
        self.assertNotEqual(next(c['availability'] for c in row['claims'] if c['field']=='website.verified_url'),'available')
