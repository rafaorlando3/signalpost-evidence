import tempfile,unittest
from unittest.mock import MagicMock,patch
from urllib.parse import urlsplit
from agent import Fetcher
from transport_policy import request_target
class UnicodeRequestTarget(unittest.TestCase):
    def test_observed_norwegian_path_is_utf8_percent_encoded(self):
        self.assertEqual(request_target('https://example.no/post/langø-søker-på-åsen'),'/post/lang%C3%B8-s%C3%B8ker-p%C3%A5-%C3%A5sen')
    def test_existing_escapes_and_query_structure_are_preserved(self):
        self.assertEqual(request_target('https://example.no/a%2Fb?q=blå+bil&next=%2Fhome#ignored'),'/a%2Fb?q=bl%C3%A5+bil&next=%2Fhome')
    def test_ascii_request_target_is_unchanged(self):
        self.assertEqual(request_target('https://example.no/roles?id=7&f=a:b,c;d@e/x?y'),'/roles?id=7&f=a:b,c;d@e/x?y')
        self.assertEqual(request_target('https://example.no'),'/')
    def test_control_characters_are_not_turned_into_http_payload(self):
        for url in ['https://example.no/\x00path','https://example.no/?q=\x7f']:
            with self.assertRaises(ValueError):request_target(url)
    def test_fetcher_sends_encoded_path_and_preserves_observed_source_url(self):
        conn=MagicMock();response=MagicMock();response.status=200;response.read.return_value=b'<p>Role</p>';response.getheader.return_value=None;response.headers.get_content_charset.return_value='utf-8';conn.getresponse.return_value=response
        url='https://unicode.test/karriere/sjåfør?sted=Gjøvik'
        with tempfile.TemporaryDirectory() as d,patch('agent.safe_url',return_value=(urlsplit(url),'unicode.test',443,'8.8.8.8')),patch('agent.http.client.HTTPSConnection',return_value=conn):
            result=Fetcher(d).get(url,raw=True)
        self.assertEqual(conn.request.call_args.args[:2],('GET','/karriere/sj%C3%A5f%C3%B8r?sted=Gj%C3%B8vik'))
        self.assertEqual(result['requested_url'],url);self.assertEqual(result['status'],'available')
