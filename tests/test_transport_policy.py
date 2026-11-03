import datetime as dt
import json
import socket
import ssl
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
from urllib.parse import urlsplit
from agent import Fetcher,UA,digest
from registry_discovery import declared_url_variants,additional_name_domain_candidates
from transport_policy import error_kind,retry_delay,request_headers

class TransportPolicyTests(unittest.TestCase):
    def setUp(self):
        Fetcher.host_last.clear();Fetcher.host_retry_not_before.clear()
    def response(self,status=200,body=b'<p>Example</p>',headers=None):
        r=MagicMock();r.status=status;r.read.return_value=body;r.getheader.side_effect=lambda name:(headers or {}).get(name);r.headers.get_content_charset.return_value='utf-8';return r
    def safe(self,url):return urlsplit(url),urlsplit(url).hostname,443,'8.8.8.8'
    def test_retry_after_seconds_and_http_date(self):
        at=dt.datetime(2026,11,3,12,tzinfo=dt.timezone.utc)
        self.assertEqual(retry_delay('3',at),3)
        self.assertEqual(retry_delay('Tue, 03 Nov 2026 12:00:05 GMT',at),5)
        self.assertEqual(retry_delay('invalid',at),1)
    def test_identified_headers_and_secret_header_exclusion(self):
        self.assertEqual(request_headers('https://example.no',UA)['User-Agent'],UA)
        self.assertEqual(request_headers('https://example.no',UA)['Accept-Language'],'nb,en;q=0.8')
        conn=MagicMock();conn.getresponse.return_value=self.response(headers={'Set-Cookie':'secret','Server':'cloudflare','CF-Ray':'public-ray'})
        with tempfile.TemporaryDirectory() as d,patch('agent.safe_url',side_effect=self.safe),patch('agent.http.client.HTTPSConnection',return_value=conn):
            r=Fetcher(d).get('https://example.test/',raw=True)
        self.assertNotIn('set-cookie',r['response_headers']);self.assertTrue(r['protection']['cf_ray_present'])
    def test_429_and_503_retry_once_then_stop(self):
        for status in [429,503]:
            with self.subTest(status=status),tempfile.TemporaryDirectory() as d,patch('agent.safe_url',side_effect=self.safe),patch('agent.time.sleep'):
                Fetcher.host_retry_not_before.clear();conn=MagicMock();conn.getresponse.side_effect=[self.response(status,headers={'Retry-After':'0'}),self.response(status)]
                with patch('agent.http.client.HTTPSConnection',return_value=conn):r=Fetcher(d).get('https://retry.test/',raw=True)
                self.assertEqual(conn.request.call_count,2);self.assertEqual(r['status_code'],status)
    def test_long_retry_after_is_deferred_not_ignored(self):
        conn=MagicMock();conn.getresponse.return_value=self.response(429,headers={'Retry-After':'3600'})
        with tempfile.TemporaryDirectory() as d,patch('agent.safe_url',side_effect=self.safe),patch('agent.http.client.HTTPSConnection',return_value=conn):
            f=Fetcher(d,deadline=2);r=f.get('https://cooldown.test/',raw=True);again=f.get('https://cooldown.test/next',raw=True)
        self.assertEqual(conn.request.call_count,1);self.assertEqual(r['status_code'],429);self.assertEqual(again['error_kind'],'retry_after_deferred')
    def test_robots_timeout_or_tls_retry_with_longer_timeout_and_keep_disallow(self):
        for error in [TimeoutError(),ssl.SSLError('test'),ssl.SSLCertVerificationError('test')]:
            with self.subTest(error=type(error).__name__),tempfile.TemporaryDirectory() as d,patch('agent.safe_url',side_effect=self.safe):
                conn=MagicMock();conn.request.side_effect=error
                with patch('agent.http.client.HTTPSConnection',return_value=conn) as factory:
                    f=Fetcher(d);r=f.get('https://failure.test/',site=True)
                self.assertEqual(conn.request.call_count,2);self.assertEqual(r['status'],'blocked')
                self.assertGreater(factory.call_args_list[1].kwargs['timeout'],factory.call_args_list[0].kwargs['timeout'])
                self.assertEqual(f.robots_observations['https://failure.test']['policy_state'],'unreachable_disallow')
    def test_dns_failure_replays_as_dns_but_live_can_retry_later(self):
        with tempfile.TemporaryDirectory() as d:
            with patch('agent.safe_url',side_effect=socket.gaierror()):
                failed=Fetcher(d).get('https://dns.test/robots.txt',raw=True)
            with patch('agent.safe_url',side_effect=AssertionError('network forbidden')):
                replay=Fetcher(d,replay=True).get('https://dns.test/robots.txt',raw=True)
            self.assertEqual(replay['error_kind'],'dns');self.assertEqual(failed['error_kind'],replay['error_kind'])
            conn=MagicMock();conn.getresponse.return_value=self.response(body=b'User-agent: *\nAllow: /')
            with patch('agent.safe_url',side_effect=self.safe),patch('agent.http.client.HTTPSConnection',return_value=conn):
                recovered=Fetcher(d).get('https://dns.test/robots.txt',raw=True)
            self.assertEqual(recovered['status'],'available')
    def test_url_aliases_keep_path_query_and_require_safe_url(self):
        variants=declared_url_variants('https://www.example.no/entity?a=1')
        self.assertIn('http://example.no/entity?a=1',variants)
        self.assertIn('https://example.no/entity?a=1',variants)
        self.assertEqual(declared_url_variants('https://name:secret@example.no/'),[])
        self.assertEqual(additional_name_domain_candidates({'navn':'Example Services AS'}),['https://exampleservices.com/'])
        self.assertEqual(additional_name_domain_candidates({'navn':'Example AS'}),[])
    def test_failure_taxonomy(self):
        self.assertEqual(error_kind(socket.gaierror()),'dns');self.assertEqual(error_kind(TimeoutError()),'timeout')
        self.assertEqual(error_kind(ssl.SSLCertVerificationError()),'tls_certificate')

if __name__=='__main__':unittest.main()
