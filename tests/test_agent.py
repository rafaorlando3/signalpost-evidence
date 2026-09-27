import copy
import json
import tempfile
import unittest
from unittest.mock import patch
from agent import Page, website_identity, corroborated_site, valid_org, compare, claim, redact, safe_url, Fetcher, research, typed_json

class Core(unittest.TestCase):
    def test_checksum(self):
        self.assertTrue(valid_org('810034882'))
        self.assertFalse(valid_org('810034883'))
        self.assertFalse(valid_org('123'))

    def test_identity_exact(self):
        self.assertEqual(website_identity('810034882',Page('<footer>Org.nr: 810 034 882</footer>','https://example.test')),'exact')

    def test_identity_rejects_joined_fragments(self):
        self.assertEqual(website_identity('810034882',Page('Products 810. Orders 034. Clients 882.','https://example.test')),'ambiguous')

    def test_identity_conflict(self):
        self.assertEqual(website_identity('810034882',Page('Org nr: 810034882; Org nr: 987654321','https://example.test')),'conflict')

    def test_identity_long_number(self):
        self.assertEqual(website_identity('810034882',Page('Org nr: 8100348821','https://example.test')),'ambiguous')

    def test_structured_tax_id(self):
        page=Page('<script type="application/ld+json">{"@type":"Organization","vatID":"NO810034882MVA"}</script>','https://example.test')
        self.assertEqual(website_identity('810034882',page),'exact')

    def test_structured_type_array(self):
        page=Page('<script type="application/ld+json">{"@type":["LocalBusiness","Organization"],"vatID":"NO810034882MVA"}</script>','https://example.test')
        self.assertEqual(website_identity('810034882',page),'exact')

    def test_hidden_script_not_identity(self):
        page=Page('<script>Org nr: 810034882</script><p>Unknown</p>','https://example.test')
        self.assertEqual(website_identity('810034882',page),'ambiguous')

    def test_identity_label_variants(self):
        for text in ('Organisasjonsnr.: NO 810 034 882 MVA','Org. nummer: 810034882'):
            self.assertEqual(website_identity('810034882',Page(text,'https://example.test')),'exact')

    def test_corroboration_requires_registered_domain_name_and_address(self):
        data={'navn':'Example Company AS','hjemmeside':'www.example.test','forretningsadresse':{'adresse':['Main gate 12'],'postnummer':'1234'}}
        self.assertTrue(corroborated_site(data,Page('Example Company, Main gate 12, 1234 Oslo','https://example.test')))
        self.assertFalse(corroborated_site(data,Page('Example Company, Main gate 12, 1234 Oslo','https://other.test')))
        self.assertFalse(corroborated_site(data,Page('Example Company','https://example.test')))
        self.assertFalse(corroborated_site({**data,'hjemmeside':None},Page('Example Company, Main gate 12, 1234 Oslo','https://example.test')))

    def test_schema_mismatch_is_failed(self):
        self.assertEqual(typed_json({'status':'available','json':[]},dict,'navn')['status'],'failed')
        self.assertEqual(typed_json({'status':'available','json':{}},dict,'navn')['status'],'failed')

    def observation(self,value,state='available',field='roles'):
        return {'claims':[{'field':field,'value':value,'availability':state,'evidence_ids':['e']}]}

    def test_reorder_no_change(self):
        self.assertEqual(compare(self.observation([{'n':'A'},{'n':'B'}]),self.observation([{'n':'B'},{'n':'A'}])),[])

    def test_real_removal(self):
        self.assertEqual(len(compare(self.observation(['A']),self.observation([]))),1)

    def test_failure_not_removal(self):
        self.assertEqual(compare(self.observation(['A']),self.observation(None,'failed')),[])

    def test_zero_change(self):
        self.assertEqual(len(compare(self.observation(5,field='employees'),self.observation(0,field='employees'))),1)

    def test_duplicate_change_preserved(self):
        self.assertEqual(len(compare(self.observation(['A']),self.observation(['A','A']))),1)

    def test_reporting_period_change_is_preserved(self):
        a=self.observation(10,field='financials.revenue');b=copy.deepcopy(a)
        a['claims'][0]['reporting_period']={'year':2024};b['claims'][0]['reporting_period']={'year':2025}
        self.assertEqual(len(compare(a,b)),1)

    def test_source_dates(self):
        evidence={}; rsp={'status':'available','url':'https://example.test','retrieved_at':'2026-09-01','content_sha256':'abc'}
        result=claim('employees',0,rsp,evidence)
        self.assertEqual(result['value'],0)
        self.assertEqual(next(iter(evidence.values()))['retrieved_at'],'2026-09-01')
        self.assertEqual(claim('x',None,rsp,evidence)['availability'],'not_available')

    def test_redaction(self):
        self.assertEqual(redact({'person':{'navn':'A','fodselsdato':'1990-01-01'}}),{'person':{'navn':'A'}})

    def test_private_addresses_blocked(self):
        for address in ('127.0.0.1','10.0.0.1','169.254.169.254','::1'):
            with patch('socket.getaddrinfo',return_value=[(2,1,6,'',(address,443))]):
                with self.assertRaises(ValueError): safe_url('https://example.test')

    def test_url_credentials_and_schemes(self):
        for url in ('file:///etc/passwd','https://user:pass@example.test','https://example.test:1234'):
            with self.assertRaises(ValueError): safe_url(url)

    def test_missing_replay_is_no_network(self):
        with tempfile.TemporaryDirectory() as d, patch('socket.getaddrinfo',side_effect=AssertionError('network')):
            f=Fetcher(d,replay=True)
            self.assertEqual(f.get('https://example.test')['status'],'failed')
            self.assertEqual(f.requests,0)

    def test_full_pipeline_failure_keeps_unknowns(self):
        with tempfile.TemporaryDirectory() as d:
            f=Fetcher(d,replay=True)
            result=research({'organisation_number':'810034882'},f)
            self.assertTrue(all(c['value'] is None for c in result['claims']))
            self.assertFalse(result['changes'])
            self.assertEqual(result['operations']['requests'],0)

if __name__=='__main__': unittest.main()
