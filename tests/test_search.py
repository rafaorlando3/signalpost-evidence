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


class FreeSearchTests(unittest.TestCase):
    def make(self, directory, credits=3, **kwargs):
        from search import FreeTavilySearch
        return FreeTavilySearch(directory, limit=10, key='fixture-not-a-real-key',
                                free_credit_limit=credits, **kwargs)

    def test_allowance_is_exact_integer_not_bool_and_no_call_is_implicit(self):
        from search import FreeTavilySearch
        for value in (True, False, 1.0, '3', None, -1, 1001):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as d:
                with self.assertRaises(ValueError):
                    FreeTavilySearch(d, free_credit_limit=value)
        with tempfile.TemporaryDirectory() as d:
            s=self.make(d, credits=0, transport=lambda *a: self.fail('no provider call'))
            f=Fetcher(d, fresh=True)
            self.assertEqual(s.discover(ORG, 'Example AS', f), [])
            self.assertEqual(s.attempts, 0)
            self.assertEqual(f.discovery['state'], 'free_credit_budget_exhausted')

    def test_global_free_cap_and_company_http_cap_are_reserved_before_transport(self):
        calls=[]
        def post(payload, timeout):
            calls.append(payload)
            return {'results':[{'url':'https://candidate.test/'}], 'usage':{'credits':1}}
        with tempfile.TemporaryDirectory() as d, patch('search.time.sleep'):
            s=self.make(d, credits=2, transport=post)
            for index in range(3):
                s.discover(str(index), 'Example '+str(index), Fetcher(d, fresh=True))
            self.assertEqual(len(calls), 2)
            self.assertEqual(s.attempts, 2)
            f=Fetcher(d, fresh=True);f.requests=20
            self.assertEqual(s.discover('other', 'Other AS', f), [])
            self.assertEqual(f.requests, 20)
            self.assertEqual(len(calls), 2)

    def test_three_search_attempts_max_per_company_even_with_new_queries(self):
        calls=[]
        def post(payload, timeout):
            calls.append(payload)
            return {'results':[], 'usage':{'credits':1}}
        with tempfile.TemporaryDirectory() as d, patch('search.time.sleep'):
            s=self.make(d, credits=10, transport=post)
            for index in range(4):
                f=Fetcher(d, fresh=True)
                s.discover(ORG, 'Query '+str(index), f)
            self.assertEqual(len(calls), 3)
            self.assertEqual(s.attempts, 3)
            self.assertEqual(f.discovery['state'], 'company_search_budget_exhausted')

    def test_missing_boolean_or_unexpected_usage_halts_further_calls_without_refund(self):
        for credits in (None, True, False, 1.0, '1', 0, 2):
            with self.subTest(credits=credits), tempfile.TemporaryDirectory() as d:
                calls=[]
                def post(payload, timeout):
                    calls.append(payload)
                    return {'results':[{'url':'https://candidate.test/'}],
                            'usage':{} if credits is None else {'credits':credits}}
                s=self.make(d, transport=post)
                f=Fetcher(d, fresh=True)
                self.assertEqual(s.discover(ORG, 'Example AS', f), ['https://candidate.test/'])
                self.assertEqual(f.requests, 1)
                self.assertIsNone(f.discovery['credits_reported'])
                self.assertIsNone(f.discovery['paid_cost_usd'])
                self.assertEqual(s.discover('other', 'Other AS', Fetcher(d, fresh=True)), [])
                self.assertEqual(s.attempts, 1)
                self.assertEqual(len(calls), 1)
                self.assertEqual(s.free_halted, 'free_usage_unknown')

    def test_uncertain_timeout_consumes_reservation_and_stops_next_search(self):
        calls=[]
        def post(payload, timeout):
            calls.append(payload)
            raise TimeoutError('sensitive-provider-body')
        with tempfile.TemporaryDirectory() as d:
            s=self.make(d, transport=post);f=Fetcher(d, fresh=True)
            self.assertEqual(s.discover(ORG, 'Example AS', f), [])
            self.assertEqual(f.requests, 1)
            self.assertEqual(s.attempts, 1)
            self.assertEqual(s.discover('other', 'Other AS', Fetcher(d, fresh=True)), [])
            self.assertEqual(len(calls), 1)
            self.assertNotIn('sensitive-provider-body', json.dumps(f.discovery))
            self.assertNotIn('fixture-not-a-real-key', json.dumps(f.discovery))

    def test_free_payload_never_expands_to_advanced_or_auto_parameters(self):
        with tempfile.TemporaryDirectory() as d:
            s=self.make(d, transport=lambda *a: self.fail('no paid fallback'))
            s.payload=lambda *a: {'query':'fixture', 'search_depth':'advanced',
                                  'auto_parameters':False}
            f=Fetcher(d, fresh=True)
            self.assertEqual(s.discover(ORG, 'Example AS', f), [])
            self.assertEqual(s.free_halted, 'free_payload_not_permitted')
            self.assertEqual(s.attempts, 1)

    def test_free_cache_replay_retains_candidates_without_keys_snippets_or_calls(self):
        calls=[]
        def post(payload, timeout):
            calls.append(payload)
            return {'results':[{'url':'https://candidate.test/contact',
                                'content':'private-search-snippet'}], 'usage':{'credits':1}}
        with tempfile.TemporaryDirectory() as d:
            first=self.make(d, transport=post)
            first.discover(ORG, 'Example AS', Fetcher(d, fresh=True))
            replay=self.make(d, credits=0, transport=lambda *a: self.fail('replay network'))
            f=Fetcher(d, replay=True)
            self.assertEqual(replay.discover(ORG, 'Example AS', f), ['https://candidate.test/'])
            self.assertEqual(f.requests, 0)
            self.assertEqual(replay.attempts, 0)
            self.assertEqual(len(calls), 1)
            for path in (Path(d)/'search-free').glob('*.json'):
                self.assertNotIn('private-search-snippet', path.read_text())
                self.assertNotIn('fixture-not-a-real-key', path.read_text())

    def test_threaded_reservations_never_exceed_free_cap(self):
        import concurrent.futures
        calls=[]
        def post(payload, timeout):
            calls.append(payload)
            return {'results':[], 'usage':{'credits':1}}
        with tempfile.TemporaryDirectory() as d, patch('search.time.sleep'):
            s=self.make(d, credits=2, transport=post)
            def work(index):
                return s.discover(str(index), 'Example '+str(index), Fetcher(d, fresh=True))
            with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
                list(pool.map(work, range(6)))
            self.assertEqual(len(calls), 2)
            self.assertEqual(s.attempts, 2)
            self.assertEqual(s.free_credits_reported, 2)

    def test_lazy_free_adaptive_still_stops_when_caller_accepts_first_site(self):
        calls=[]
        def post(payload, timeout):
            calls.append(payload)
            return {'results':[{'url':'https://candidate.test/'}], 'usage':{'credits':1}}
        with tempfile.TemporaryDirectory() as d:
            s=self.make(d, strategy='adaptive', transport=post)
            iterator=s.iter_candidates(ORG, 'Example AS', Fetcher(d, fresh=True))
            self.assertEqual(next(iterator)[0], 'https://candidate.test/')
            iterator.close()
            self.assertEqual(len(calls), 1)
            self.assertEqual(s.attempts, 1)


    def test_unknown_usage_stops_other_workers_before_another_reservation(self):
        import concurrent.futures
        calls=[]
        def post(payload, timeout):
            calls.append(payload)
            return {'results':[], 'usage':{}}
        with tempfile.TemporaryDirectory() as d, patch('search.time.sleep'):
            s=self.make(d, credits=3, transport=post)
            def work(index):
                return s.discover(str(index), 'Example '+str(index), Fetcher(d, fresh=True))
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(work, range(4)))
            self.assertEqual(len(calls), 1)
            self.assertEqual(s.attempts, 1)
            self.assertEqual(s.free_halted, 'free_usage_unknown')
