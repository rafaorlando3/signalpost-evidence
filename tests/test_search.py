import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from agent import Fetcher, research
from search import TavilySearch, candidate_urls

ORG = '810034882'


class SearchTests(unittest.TestCase):
    def test_filter_directories_duplicates_credentials_and_non_web_urls(self):
        urls = ['https://proff.no/a', 'https://www.linkedin.com/company/a',
                'https://a.test/contact', 'https://a.test/about', 'https://b.test/',
                'https://user:password@c.test/', 'file:///secret', 'https://d.test:1234/']
        self.assertEqual(list(candidate_urls([{'url': u} for u in urls])),
                         ['https://a.test/', 'https://b.test/'])

    def test_customer_page_does_not_establish_domain_ownership(self):
        urls = list(candidate_urls([{'url': 'https://vendor.test/customers/example-company/'}]))
        self.assertEqual(urls, ['https://vendor.test/'])
        # The company's number on /customers/... cannot be consulted as identity
        # proof; the normal pipeline must instead verify the vendor's own domain.

    def test_cap_cache_replay_and_no_secret_retention(self):
        calls = []
        def transport(payload, timeout):
            calls.append(payload)
            return {'results': [{'url': 'https://a.test/', 'content': 'untrusted-secret-snippet'}],
                    'usage': {'credits': 1}}
        with tempfile.TemporaryDirectory() as d:
            s = TavilySearch(d, limit=1, key='test-not-a-real-key', transport=transport)
            f = Fetcher(d)
            self.assertEqual(s.discover(ORG, 'Example AS', f), ['https://a.test/'])
            self.assertEqual(f.requests, 1)
            self.assertIsNone(f.discovery['paid_cost_usd'])
            self.assertEqual(s.discover('987654321', 'Other AS', Fetcher(d)), [])
            replay = Fetcher(d, replay=True)
            self.assertEqual(s.discover(ORG, 'Example AS', replay), ['https://a.test/'])
            self.assertEqual(replay.requests, 0)
            self.assertEqual(len(calls), 1)
            self.assertFalse(calls[0]['include_answer'])
            self.assertEqual(calls[0]['search_depth'], 'basic')
            for path in Path(d).rglob('*.json'):
                self.assertNotIn('test-not-a-real-key', path.read_text())
                self.assertNotIn('untrusted-secret-snippet', path.read_text())

    def test_company_budget_and_missing_key_prevent_calls(self):
        with tempfile.TemporaryDirectory() as d:
            def fail(*args): raise AssertionError('unexpected network')
            s = TavilySearch(d, key='', transport=fail)
            self.assertEqual(s.discover(ORG, 'A', Fetcher(d)), [])
            self.assertEqual(s.attempts, 0)
            s.key = 'fixture'
            f = Fetcher(d); f.requests = 20
            self.assertEqual(s.discover(ORG, 'A', f), [])
            self.assertEqual(f.requests, 20)

    def test_failure_does_not_log_secrets_or_claim_zero_cost(self):
        with tempfile.TemporaryDirectory() as d:
            def fail(*args): raise ValueError('sensitive-response')
            s = TavilySearch(d, key='fixture', transport=fail); f = Fetcher(d)
            self.assertEqual(s.discover(ORG, 'A', f), [])
            self.assertEqual(f.discovery['error'], 'ValueError')
            self.assertIsNone(f.discovery['paid_cost_usd'])
            self.assertNotIn('sensitive-response', json.dumps(f.discovery))

    def test_search_match_still_requires_exact_company_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            f = Fetcher(d, replay=True)
            def get(url, **kwargs):
                rsp = {'url': url, 'status': 'available', 'status_code': 200,
                       'retrieved_at': '2026-09-26T00:00:00Z', 'content_sha256': 'fixture', 'text': ''}
                if '/enheter/' in url: rsp['json'] = {'organisasjonsnummer': ORG, 'navn': 'Example AS'}
                elif 'underenheter?' in url: rsp['json'] = {'page': {'totalPages': 0}}
                elif url.startswith('https://wrong.test'): rsp['text'] = 'Example AS; Org no 987654321'
                elif url == 'https://right.test/contact':
                    rsp['text'] = 'Org no ' + ORG + '<meta name="description" content="Privacy legal boilerplate">'
                elif url.startswith('https://right.test'):
                    rsp['text'] = '<meta name="description" content="We build useful products"><a href="/contact">Contact</a><a href="https://facebook.com/example#">Social</a>'
                else: rsp.update(status='not_available', json={})
                return rsp
            class Search:
                def discover(self, *args): return ['https://wrong.test/', 'https://right.test/']
            with patch.object(f, 'get', side_effect=get):
                result = research({'organisation_number': ORG}, f, search=Search())
            claim = next(c for c in result['claims'] if c['field'] == 'website.verified_url')
            self.assertEqual(claim['value'], 'https://right.test/')
            self.assertEqual(len([c for c in result['claims'] if c['field'] == 'website.verified_url']), 1)
            self.assertEqual(claim['source_pointer'], 'explicit_org_number')
            social = next(c for c in result['claims'] if c['field'] == 'website.social_links')
            self.assertEqual(social['value'][0]['url'], 'https://facebook.com/example')
            description = next(c for c in result['claims'] if c['field'] == 'website.description')
            self.assertEqual(description['value'], 'We build useful products')


if __name__ == '__main__': unittest.main()

class SearchStrategyIsolation(unittest.TestCase):
    def test_focus_stays_basic_and_cache_is_separate_from_legacy(self):
        calls=[]
        def transport(payload, timeout):
            calls.append(payload)
            return {'results':[{'url':'https://candidate.test/'}],'usage':{'credits':1}}
        with tempfile.TemporaryDirectory() as d:
            old=TavilySearch(d,key='fixture',transport=transport)
            new=TavilySearch(d,key='fixture',transport=transport,strategy='name_focus')
            old.discover(ORG,'Example AS',Fetcher(d));new.discover(ORG,'Example AS',Fetcher(d))
            self.assertEqual(len(calls),2)
            self.assertEqual(calls[1]['query'],'"Example AS"')
            self.assertEqual(calls[1]['search_depth'],'basic')
            self.assertEqual(calls[1]['country'],'norway')
            self.assertFalse(calls[1]['auto_parameters'])
            self.assertIn('proff.no',calls[1]['exclude_domains'])
            self.assertEqual(len(list((Path(d)/'search').glob('*.json'))),2)
            new.discover(ORG,'Example AS',Fetcher(d,replay=True))
            self.assertEqual(len(calls),2)

    def test_no_unknown_strategy_can_enable_paid_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):TavilySearch(d,strategy='advanced')
