import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.robotparser import RobotFileParser
from agent import Fetcher, Page, website_identity, crawl_company, research
from search import TavilySearch, identity_candidates
from test_discovery import Pages, ORG

class AdaptiveDiscovery(unittest.TestCase):
    def test_number_query_cache_retains_urls_not_snippets(self):
        calls=[]
        def post(payload,timeout):
            calls.append(payload)
            return {'results':[{'url':'https://ours.test/contact','content':'Org '+ORG+' secret-search-snippet'}],'usage':{'credits':1}}
        with tempfile.TemporaryDirectory() as d:
            s=TavilySearch(d,key='fixture-key',strategy='adaptive',transport=post)
            f=Fetcher(d)
            results=list(s.iter_candidates(ORG,'Example AS',f))
            self.assertEqual(len(calls),2)
            self.assertEqual(results[-1][2],['https://ours.test/contact'])
            self.assertIn(ORG,calls[1]['query'])
            self.assertEqual(calls[1]['search_depth'],'basic')
            self.assertEqual(f.discovery['credits_reported'],2)
            self.assertEqual(f.discovery['request_attempts'],2)
            self.assertIsNone(f.discovery['paid_cost_usd'])
            for file in Path(d).rglob('*.json'):
                self.assertNotIn('secret-search-snippet',file.read_text())
                self.assertNotIn('fixture-key',file.read_text())
            list(s.iter_candidates(ORG,'Example AS',Fetcher(d,replay=True)))
            self.assertEqual(len(calls),2)

    def test_stop_after_first_confirmed_candidate_avoids_second_query(self):
        calls=[]
        def post(p,t):calls.append(p);return {'results':[{'url':'https://ours.test/'}],'usage':{'credits':1}}
        with tempfile.TemporaryDirectory() as d:
            s=TavilySearch(d,key='fixture',strategy='adaptive',transport=post)
            iterator=s.iter_candidates(ORG,'Example AS',Fetcher(d))
            self.assertEqual(next(iterator)[0],'https://ours.test/')
            iterator.close()
            self.assertEqual(len(calls),1)

    def test_global_cap_includes_both_stages(self):
        with tempfile.TemporaryDirectory() as d:
            s=TavilySearch(d,limit=1,key='fixture',strategy='adaptive',transport=lambda p,t:{'results':[],'usage':{'credits':1}})
            f=Fetcher(d)
            self.assertEqual(list(s.iter_candidates(ORG,'Example AS',f)),[])
            self.assertEqual(s.attempts,1)
            self.assertEqual(f.discovery['request_attempts'],1)
            self.assertEqual(f.discovery['stages'][1]['state'],'budget_exhausted')

    def test_directories_and_case_studies_cannot_seed_legal_identity(self):
        data=[{'url':'https://io.no/example','content':ORG},
              {'url':'https://wrong.test/customers/example/contact','content':ORG},
              {'url':'https://ours.test/privacy','content':'Example AS '+ORG},
              {'url':'https://user:password@bad.test/contact'}]
        candidates=identity_candidates(data,ORG,'Example AS')
        self.assertEqual(candidates[0],{'url':'https://ours.test/','hints':['https://ours.test/privacy']})
        self.assertEqual(candidates[1]['hints'],[])
        self.assertEqual(len(candidates),2)

    def test_robots_custom_sitemap_and_safe_seed(self):
        home={'url':'https://ours.test/','text':'<h1>Example</h1>'}
        f=Pages({'https://ours.test/map-index.xml':'<urlset><url><loc>https://ours.test/personvern</loc></url></urlset>',
                 'https://ours.test/personvern':'Org. nr.: '+ORG})
        robot=RobotFileParser();robot.parse(['User-agent: *','Allow: /','Sitemap: https://ours.test/map-index.xml'])
        f.robots={'https://ours.test':robot}
        verified,_=crawl_company(ORG,{},home,f,seed_urls=['https://third.test/contact'])
        self.assertTrue(verified)
        self.assertNotIn('https://third.test/contact',f.visited)
        self.assertIn('https://ours.test/map-index.xml',f.visited)

    def test_explicit_dotted_number_not_order_or_phone(self):
        self.assertEqual(website_identity(ORG,Page('Org. nr.: 810.034.882','https://a.test')),'exact')
        self.assertEqual(website_identity(ORG,Page('Company registration no: 810 034 882','https://a.test')),'exact')
        self.assertEqual(website_identity(ORG,Page('Order 810.034.882','https://a.test')),'ambiguous')

    def test_budget_reserves_next_candidate(self):
        f=Pages({});f.requests=4
        home={'url':'https://first.test/','text':''.join(f'<a href="/contact/{n}">Contact</a>' for n in range(15))}
        crawl_company(ORG,{},home,f,reserve_requests=6)
        self.assertLessEqual(f.requests,14)
        self.assertGreaterEqual(f.limit-f.requests,6)

    def test_malformed_optional_attributes_do_not_abort_html_collection(self):
        p=Page('<link rel><meta name><meta name="description" content><time class itemprop datetime="2026-09-26">Today</time>Org nr '+ORG,'https://example.test')
        self.assertEqual(website_identity(ORG,p),'exact')
        self.assertEqual(p.description,'')
        self.assertEqual(p.times,[])
