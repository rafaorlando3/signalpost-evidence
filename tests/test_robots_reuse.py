import threading
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
from urllib.parse import urlsplit
from agent import Fetcher
from transport_policy import RunRobotsCache


class RobotsReuse(unittest.TestCase):
    def record(self,code=200,text='User-agent: *\nDisallow: /private'):
        return {'url':'https://example.no/robots.txt','status_code':code,
                'status':'available' if code==200 else 'blocked','text':text}

    def test_reuses_policy_and_returns_independent_copy(self):
        cache=RunRobotsCache();calls=[]
        one,hit=cache.get('https://example.no',lambda:(calls.append(1) or self.record()),cache.clock()+10)
        one['text']='changed'
        two,hit=cache.get('https://example.no',lambda:self.fail('must reuse valid policy'),cache.clock()+10)
        self.assertTrue(hit);self.assertEqual(len(calls),1);self.assertIn('Disallow: /private',two['text'])

    def test_expiry_revalidates_and_retains_new_disallow(self):
        clock=[0];cache=RunRobotsCache(ttl=300,clock=lambda:clock[0])
        cache.get('https://example.no',lambda:self.record(text='User-agent: *\nDisallow:'),10)
        clock[0]=301
        record,hit=cache.get('https://example.no',lambda:self.record(text='User-agent: *\nDisallow: /'),310)
        self.assertFalse(hit);self.assertEqual(record['text'],'User-agent: *\nDisallow: /')

    def test_protection_rate_limit_and_network_failures_are_not_reused(self):
        for code in [401,403,429,500,503,None]:
            with self.subTest(code=code):
                cache=RunRobotsCache();calls=[]
                def load():calls.append(1);return self.record(code=code)
                cache.get('https://example.no',load,cache.clock()+10)
                cache.get('https://example.no',load,cache.clock()+10)
                self.assertEqual(len(calls),2)

    def test_unavailable_404_410_reuse_is_scoped_to_exact_origin(self):
        for code in [404,410]:
            cache=RunRobotsCache();calls=[]
            def load():calls.append(1);return self.record(code=code)
            cache.get('https://example.no',load,cache.clock()+10)
            self.assertTrue(cache.get('https://example.no',load,cache.clock()+10)[1])
            self.assertFalse(cache.get('http://example.no',load,cache.clock()+10)[1])
            self.assertEqual(len(calls),2)

    def test_no_load_after_deadline_or_when_policy_lock_exceeds_deadline(self):
        cache=RunRobotsCache(clock=lambda:0)
        with self.assertRaises(TimeoutError):cache.get('https://example.no',lambda:self.fail('deadline'),0)
        with cache.lock:lock=cache.host_locks['https://example.no']
        lock.acquire()
        try:
            with self.assertRaises(TimeoutError):cache.get('https://example.no',lambda:self.fail('lock'),0)
        finally:lock.release()

    def test_concurrent_same_origin_loads_only_once(self):
        cache=RunRobotsCache();started=threading.Event();release=threading.Event();calls=[];results=[]
        def load():calls.append(1);started.set();release.wait(2);return self.record()
        one=threading.Thread(target=lambda:results.append(cache.get('https://example.no',load,cache.clock()+3)))
        two=threading.Thread(target=lambda:results.append(cache.get('https://example.no',load,cache.clock()+3)))
        one.start();self.assertTrue(started.wait(1));two.start();release.set();one.join();two.join()
        self.assertEqual(len(calls),1);self.assertEqual(sorted(x[1] for x in results),[False,True])

    def test_cache_control_prohibitions_and_short_max_age_are_respected(self):
        for control in ['no-store','private','public, no-cache','public,max-age=0']:
            cache=RunRobotsCache();calls=[]
            def load():
                calls.append(1);return {**self.record(),'response_headers':{'cache-control':control}}
            cache.get('https://example.no',load,cache.clock()+10)
            cache.get('https://example.no',load,cache.clock()+10)
            self.assertEqual(len(calls),2)
        clock=[0];cache=RunRobotsCache(clock=lambda:clock[0]);calls=[]
        def load():
            calls.append(1);return {**self.record(),'response_headers':{'cache-control':'public, max-age=10','age':'3'}}
        cache.get('https://example.no',load,10);clock[0]=6
        self.assertTrue(cache.get('https://example.no',load,10)[1]);clock[0]=8
        self.assertFalse(cache.get('https://example.no',load,10)[1]);self.assertEqual(len(calls),2)

    def response(self,status=200,body=b'User-agent: *\nDisallow: /private'):
        r=MagicMock();r.status=status;r.read.return_value=body;r.getheader.return_value=None;r.headers.get_content_charset.return_value='utf-8'
        return r

    def safe(self,url):return urlsplit(url),urlsplit(url).hostname,443,'8.8.8.8'

    def test_fetchers_share_robots_but_keep_page_destination_validation(self):
        Fetcher.host_last.clear();Fetcher.host_retry_not_before.clear()
        with tempfile.TemporaryDirectory() as td:
            cache=RunRobotsCache();connection=MagicMock();connection.getresponse.side_effect=[self.response(),self.response(body=b'<h1>Company</h1>')]
            with patch('agent.safe_url',side_effect=self.safe),patch('agent.http.client.HTTPSConnection',return_value=connection):
                a=Fetcher(Path(td)/'a',fresh=True,robots_cache=cache);self.assertEqual(a.get('https://example.no/',site=True)['status'],'available')
            b=Fetcher(Path(td)/'b',fresh=True,robots_cache=cache)
            with patch('agent.safe_url',side_effect=ValueError('Non-public destination blocked')):
                result=b.get('https://example.no/',site=True)
            self.assertEqual(result['status'],'failed');self.assertEqual(result['error_kind'],'url_policy_or_decode')
            self.assertEqual(a.requests,2);self.assertEqual(b.requests,0)
            self.assertEqual(b.robots_reuse_hits,1)

    def test_cached_disallow_still_prevents_the_page_request(self):
        Fetcher.host_last.clear();Fetcher.host_retry_not_before.clear()
        with tempfile.TemporaryDirectory() as td:
            cache=RunRobotsCache();connection=MagicMock();connection.getresponse.return_value=self.response(200,b'User-agent: *\nDisallow: /')
            with patch('agent.safe_url',side_effect=self.safe),patch('agent.http.client.HTTPSConnection',return_value=connection):
                a=Fetcher(Path(td)/'a',fresh=True,robots_cache=cache);b=Fetcher(Path(td)/'b',fresh=True,robots_cache=cache)
                self.assertEqual(a.get('https://example.no/private',site=True)['status'],'blocked')
                self.assertEqual(b.get('https://example.no/private',site=True)['status'],'blocked')
            self.assertEqual(a.requests,1);self.assertEqual(b.requests,0);self.assertEqual(b.robots_reuse_hits,1)
