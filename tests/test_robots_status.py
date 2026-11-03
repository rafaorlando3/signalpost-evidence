import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from agent import Fetcher,digest,encode

class RobotsStatus(unittest.TestCase):
    HOME='https://example.test/'
    def put(self,d,url,code,text):
        row={'url':url,'requested_url':url,'status':'available' if 200<=code<300 else 'blocked' if code in (401,403,429) else 'failed',
             'status_code':code,'text':text,'retrieved_at':'2026-11-03T00:00:00Z','content_sha256':digest(text.encode())}
        (Path(d)/(digest(url.encode())+'.json')).write_text(encode(row))
    def test_client_error_robots_does_not_block_a_public_page(self):
        for code in (400,401,403,404,410,429,451):
            with self.subTest(code=code),tempfile.TemporaryDirectory() as d,patch('socket.getaddrinfo',side_effect=AssertionError('offline')):
                self.put(d,self.HOME+'robots.txt',code,'Access denied')
                self.put(d,self.HOME,200,'Public company website')
                f=Fetcher(d,replay=True);response=f.get(self.HOME,site=True,raw=True)
                self.assertEqual(response['status'],'available')
                self.assertEqual(f.robots_observations[self.HOME.rstrip('/')]['policy_state'],'unavailable_allow')
                self.assertEqual(f.robots_observations[self.HOME.rstrip('/')]['status_code'],code)
    def test_server_error_and_missing_robots_still_stop_before_page(self):
        for code in (0,500,502,503):
            with self.subTest(code=code),tempfile.TemporaryDirectory() as d,patch('socket.getaddrinfo',side_effect=AssertionError('offline')):
                if code:self.put(d,self.HOME+'robots.txt',code,'Temporary outage')
                self.put(d,self.HOME,200,'Public page is in cache but must not be used')
                f=Fetcher(d,replay=True);response=f.get(self.HOME,site=True,raw=True)
                self.assertEqual(response['status'],'blocked')
                self.assertEqual(f.robots_observations[self.HOME.rstrip('/')]['policy_state'],'unreachable_disallow')
    def test_successful_robots_rules_and_homepage_waf_remain_enforced(self):
        with tempfile.TemporaryDirectory() as d,patch('socket.getaddrinfo',side_effect=AssertionError('offline')):
            self.put(d,self.HOME+'robots.txt',200,'User-agent: *\nDisallow: /private')
            self.put(d,self.HOME,403,'WAF denied the actual homepage')
            self.put(d,self.HOME+'private',200,'Private cached text')
            f=Fetcher(d,replay=True)
            self.assertEqual(f.get(self.HOME,site=True)['status_code'],403)
            self.assertEqual(f.get(self.HOME+'private',site=True)['status'],'blocked')
            self.assertEqual(f.requests,0)

if __name__=='__main__':unittest.main()
