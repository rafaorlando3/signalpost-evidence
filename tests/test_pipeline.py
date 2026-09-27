import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from agent import Fetcher, OFFICIAL, digest, encode, research
from audit import audit

ORG='810034882'
BASE=OFFICIAL+'/enhetsregisteret/api/enheter/'+ORG

def save(folder,url,value):
    text=encode(value)
    record={'url':url,'requested_url':url,'status':'available','status_code':200,
        'retrieved_at':'2026-09-26T00:00:00+00:00','content_sha256':digest(text.encode()),'text':text,'json':value}
    (Path(folder)/(digest(url.encode())+'.json')).write_text(encode(record))

class Pipeline(unittest.TestCase):
    def fixture(self,d,revenue=100,employees=3):
        save(d,BASE,{'organisasjonsnummer':ORG,'navn':'Fixture AS','antallAnsatte':employees})
        save(d,OFFICIAL+'/regnskapsregisteret/regnskap/'+ORG,[
            {'virksomhet':{'organisasjonsnummer':ORG},'regnskapstype':'KONSERN','regnskapsperiode':{'tilDato':'2025-12-31'},'valuta':'NOK','resultatregnskapResultat':{'driftsresultat':{'driftsinntekter':{'sumDriftsinntekter':99999}}}},
            {'virksomhet':{'organisasjonsnummer':ORG},'regnskapstype':'SELSKAP','regnskapsperiode':{'fraDato':'2025-01-01','tilDato':'2025-12-31'},'valuta':'NOK','resultatregnskapResultat':{'driftsresultat':{'driftsinntekter':{'sumDriftsinntekter':revenue}}}}
        ])
        save(d,BASE+'/roller',{'rollegrupper':[]})
        save(d,OFFICIAL+'/enhetsregisteret/api/underenheter?overordnetEnhet='+ORG+'&size=100',{'page':{'totalPages':0}})

    def test_replay_refresh_and_source_audit(self):
        with tempfile.TemporaryDirectory() as d,patch('socket.getaddrinfo',side_effect=AssertionError('network forbidden')):
            self.fixture(d)
            a=research({'organisation_number':ORG},Fetcher(d,replay=True))
            b=research({'organisation_number':ORG},Fetcher(d,replay=True),a)
            self.assertEqual(b['changes'],[])
            self.assertEqual(b['operations']['requests'],0)
            self.assertTrue(audit([a],d)['passed'])
            revenue=next(c for c in a['claims'] if c['field']=='financials.revenue')
            self.assertEqual(revenue['value'],100)
            self.assertTrue(revenue['source_pointer'].startswith('/1/'))
            self.fixture(d,revenue=0,employees=4)
            c=research({'organisation_number':ORG},Fetcher(d,replay=True),a)
            self.assertEqual({x['field'] for x in c['changes']},{'employees','financials.revenue','financials.history'})
            self.assertEqual(c['previous_snapshot'],a)

    def test_wrong_entity_response_cannot_publish_identity(self):
        with tempfile.TemporaryDirectory() as d:
            self.fixture(d)
            save(d,BASE,{'organisasjonsnummer':'999999999','navn':'Wrong Company'})
            result=research({'organisation_number':ORG},Fetcher(d,replay=True))
            name=next(c for c in result['claims'] if c['field']=='legal_name')
            self.assertEqual(name['availability'],'ambiguous')
            self.assertIsNone(name['value'])

    def test_recovery_compares_last_supported_observation_after_outage(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as missing, patch('socket.getaddrinfo',side_effect=AssertionError('network forbidden')):
            self.fixture(d,revenue=100)
            first=research({'organisation_number':ORG},Fetcher(d,replay=True))
            outage=research({'organisation_number':ORG},Fetcher(missing,replay=True),first)
            outage2=research({'organisation_number':ORG},Fetcher(missing,replay=True),outage)
            self.assertEqual(outage['changes'],[])
            self.assertEqual(outage2['changes'],[])
            self.fixture(d,revenue=200)
            recovered=research({'organisation_number':ORG},Fetcher(d,replay=True),outage2)
            self.assertEqual({c['field'] for c in recovered['changes']},{'financials.revenue','financials.history'})
            event=next(c for c in recovered['changes'] if c['field']=='financials.revenue')
            self.assertEqual((event['old_value'],event['new_value']),(100,200))
            prior_claim=next(c for c in first['claims'] if c['field']=='financials.revenue')
            self.assertEqual(event['old_evidence_ids'],prior_claim['evidence_ids'])
            self.assertEqual(recovered['previous_snapshot'],outage2)

    def test_recovery_without_change_is_idempotent(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as missing, patch('socket.getaddrinfo',side_effect=AssertionError('network forbidden')):
            self.fixture(d)
            first=research({'organisation_number':ORG},Fetcher(d,replay=True))
            outage=research({'organisation_number':ORG},Fetcher(missing,replay=True),first)
            recovered=research({'organisation_number':ORG},Fetcher(d,replay=True),outage)
            self.assertEqual(recovered['changes'],[])
            self.assertTrue(audit([recovered],d)['passed'])

    def test_request_limit_blocks_before_network(self):
        with tempfile.TemporaryDirectory() as d,patch('socket.getaddrinfo',side_effect=AssertionError('network forbidden')):
            f=Fetcher(d,limit=0)
            self.assertEqual(f.get('https://example.test')['status'],'failed')
            self.assertEqual(f.requests,0)

    def test_robots_denial_prevents_page_fetch(self):
        with tempfile.TemporaryDirectory() as d,patch('socket.getaddrinfo',side_effect=AssertionError('network forbidden')):
            url='https://example.test/robots.txt'
            save(d,url,{})
            p=Path(d)/(digest(url.encode())+'.json');r=json.loads(p.read_text())
            r['text']='User-agent: *\nDisallow: /';p.write_text(encode(r))
            f=Fetcher(d,replay=True)
            self.assertEqual(f.get('https://example.test/contact',site=True)['status'],'blocked')

    def test_official_timeout_has_one_bounded_retry(self):
        conn=MagicMock();conn.request.side_effect=[TimeoutError('transient'),None]
        response=conn.getresponse.return_value;response.status=200
        response.read.return_value=b'{}';response.headers.get_content_charset.return_value='utf-8'
        with tempfile.TemporaryDirectory() as d,patch('agent.safe_url',return_value=(__import__('urllib.parse',fromlist=['urlsplit']).urlsplit(BASE),'data.brreg.no',443,'8.8.8.8')),patch('agent.http.client.HTTPSConnection',return_value=conn):
            f=Fetcher(d);result=f.get(BASE)
            self.assertEqual(result['status'],'available');self.assertEqual(f.requests,2)

    def test_official_repeated_timeout_stops_after_two_attempts(self):
        conn=MagicMock();conn.request.side_effect=TimeoutError('transient')
        with tempfile.TemporaryDirectory() as d,patch('agent.safe_url',return_value=(__import__('urllib.parse',fromlist=['urlsplit']).urlsplit(BASE),'data.brreg.no',443,'8.8.8.8')),patch('agent.http.client.HTTPSConnection',return_value=conn):
            f=Fetcher(d);self.assertEqual(f.get(BASE)['status'],'failed');self.assertEqual(f.requests,2)

    def test_cross_host_redirect_survives_offline_replay(self):
        from urllib.parse import urlsplit
        first=MagicMock();first.status=301;first.getheader.return_value='https://other.test/'
        second=MagicMock();second.status=200;second.read.return_value=b'<p>Org nr: 810034882</p>'
        second.headers.get_content_charset.return_value='utf-8'
        conn=MagicMock();conn.getresponse.side_effect=[first,second]
        with tempfile.TemporaryDirectory() as d:
            for url in ('https://example.test/robots.txt','https://other.test/robots.txt'):
                save(d,url,{})
                p=Path(d)/(digest(url.encode())+'.json');r=json.loads(p.read_text());r['text']='User-agent: *\nAllow: /';p.write_text(encode(r))
            with patch('agent.safe_url',side_effect=lambda u:(urlsplit(u),urlsplit(u).hostname,443,'8.8.8.8')),patch('agent.http.client.HTTPSConnection',return_value=conn):
                live=Fetcher(d).get('https://example.test/',site=True,raw=True)
            with patch('socket.getaddrinfo',side_effect=AssertionError('network forbidden')):
                f=Fetcher(d,replay=True);again=f.get('https://example.test/',site=True,raw=True)
            self.assertEqual(live,again);self.assertEqual(f.requests,0)

if __name__=='__main__':unittest.main()
