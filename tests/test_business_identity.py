import unittest
import tempfile,copy
from pathlib import Path
from unittest.mock import patch
from agent import Page,website_identity,site_operator_identity
from business_identity import business_identity
from registry_discovery import industry_city_candidates

class BusinessIdentity(unittest.TestCase):
    DATA={'organisasjonsnummer':'810034882','navn':'Example Therapy AS',
          'forretningsadresse':{'adresse':['Road 12'],'postnummer':'1426','poststed':'SOLBERG'}}
    def proof(self,html,data=None):
        data=data or self.DATA
        pages=[(Page(body,url),{'url':url,'text':body}) for url,body in html]
        compatible=lambda pg:website_identity(data['organisasjonsnummer'],pg,data)!='conflict' and site_operator_identity(data['organisasjonsnummer'],pg,data)['state'] not in {'different','unresolved'}
        return business_identity(data,pages,compatible)
    def bundle(self):
        return [('https://clinic.test/','<title>Example Therapy</title><a href="/about">About</a><a href="/contact">Contact</a>'),
                ('https://clinic.test/about','<p>Example Therapy AS har levert behandling siden 2016.</p>'),
                ('https://clinic.test/contact','<h1>Contact</h1><p>Example Therapy Road 12, entrance A, 1423 Ski/1426 Solberg</p>')]
    def test_linked_about_name_and_contact_address_with_dual_postcode(self):
        p=self.proof(self.bundle());self.assertIsNotNone(p)
        self.assertEqual(p['address_source']['registered_postcode'],'1426')
        self.assertEqual(p['legal_name_source']['source_url'],'https://clinic.test/about')
        self.assertEqual(p['address_source']['source_url'],'https://clinic.test/contact')
    def test_unlinked_address_foreign_host_wrong_street_or_postcode_rejected(self):
        for replacement in ['https://other.test/contact','https://clinic.test/unlinked-contact']:
            h=self.bundle();h[-1]=(replacement,h[-1][1]);self.assertIsNone(self.proof(h))
        for value in ['Road 13','9999']:
            h=self.bundle();h[-1]=(h[-1][0],h[-1][1].replace('Road 12' if value.startswith('Road') else '1426',value));self.assertIsNone(self.proof(h))
    def test_customer_quotes_cannot_supply_business_role(self):
        for wrapper in ['<blockquote>{}</blockquote>','<section class="customer">{}</section>','<section class="testimonial">{}</section>']:
            h=self.bundle();h[1]=(h[1][0],wrapper.format(h[1][1]));self.assertIsNone(self.proof(h))
    def test_same_address_sister_legal_name_not_dropped_to_brand(self):
        h=self.bundle();h[1]=(h[1][0],h[1][1].replace('Example Therapy AS','Example Therapy North AS'))
        self.assertIsNone(self.proof(h))
    def test_conflicting_explicit_identity_is_not_overridden(self):
        h=self.bundle();h[2]=(h[2][0],h[2][1]+'<footer>Org.nr. 974 761 076</footer>');self.assertIsNone(self.proof(h))
    def test_generic_service_city_domain_still_needs_own_legal_statement(self):
        data={'organisasjonsnummer':'810034882','navn':'Example Moving AS','forretningsadresse':{'adresse':['Street 22'],'postnummer':'5132'}}
        body='<title>Moving in Town | Example Moving AS</title><p>Vi i Example Moving AS har lang erfaring med flytting.</p><footer>Example Moving AS Street 22, 5132 Town</footer>'
        self.assertIsNotNone(self.proof([('https://moving-town.test/',body)],data))
        self.assertIsNone(self.proof([('https://moving-town.test/',body.replace('Vi i Example Moving AS har lang erfaring med flytting.','Client: Example Moving AS'))],data))
    def test_only_current_same_site_paths_support_bundle(self):
        h=self.bundle();h[1]=('https://clinic.test/customers/example',h[1][1]);h[0]=(h[0][0],h[0][1].replace('/about','/customers/example'))
        self.assertIsNone(self.proof(h))
    def test_cms_plain_div_font_blocks_are_visible_self_description(self):
        h=self.bundle();h[1]=(h[1][0],'<div><font>Example Therapy AS har levert behandling siden 2016.</font></div>')
        self.assertIsNotNone(self.proof(h))
        h[1]=(h[1][0],'<meta name="description" content="Example Therapy AS har levert behandling siden 2016."><p>Page unavailable</p>')
        self.assertIsNone(self.proof(h))
    def test_customer_blocks_do_not_leak_through_parent_div(self):
        h=self.bundle();h[1]=(h[1][0],'<div><div class="customer"><font>Example Therapy AS har levert behandling siden 2016.</font></div></div>')
        self.assertIsNone(self.proof(h))
    def test_generic_category_city_leads_use_registry_and_are_bounded(self):
        data={'navn':'Unrelated Legal Name AS','naeringskode1':{'kode':'49.420'},'forretningsadresse':{'kommune':'SANDNES'}}
        self.assertEqual(industry_city_candidates(data),['https://flyttebyra-sandnes.no/','https://flyttebyrasandnes.no/'])
        self.assertEqual(industry_city_candidates({**data,'naeringskode1':{'kode':'68.200'}}),[])
        self.assertEqual(industry_city_candidates({**data,'forretningsadresse':{}}),[])
        self.assertEqual(industry_city_candidates({**data,'forretningsadresse':{'kommune':'LØRENSKOG'}})[0],'https://flyttebyra-lorenskog.no/')

class LinkedIdentityPipeline(unittest.TestCase):
    def test_org_only_discovery_audits_every_linked_source_and_rejects_tampered_proof(self):
        from agent import Fetcher,research,encode,digest
        from audit import audit
        from test_pipeline import Pipeline,save,BASE,ORG
        with tempfile.TemporaryDirectory() as folder,patch('socket.getaddrinfo',side_effect=AssertionError('network forbidden')):
            Pipeline().fixture(folder)
            data={**BusinessIdentity.DATA,'organisasjonsnummer':ORG}
            save(folder,BASE,data)
            sources=[('https://exampletherapy.no/robots.txt','User-agent: *\nDisallow:'),
                     ('https://exampletherapy.no/','<title>Example Therapy</title><meta name="description" content="05.10.26: We currently have short waiting times for all ages."><a href="/about">About</a><a href="/contact">Contact</a>'),
                     ('https://exampletherapy.no/about','<div><font>Example Therapy AS har levert behandling siden 2016.</font></div>'),
                     ('https://exampletherapy.no/contact','<p>Example Therapy Road 12, 1426 Solberg</p><a href="mailto:office@exampletherapy.no">Email</a><a href="tel:12345678">Call</a>')]
            for url,text in sources:
                rsp={'url':url,'requested_url':url,'text':text,'status':'available','status_code':200,'retrieved_at':'2026-11-01T00:00:00Z','content_sha256':digest(text.encode())}
                (Path(folder)/(digest(url.encode())+'.json')).write_text(encode(rsp))
            row=research({'organisation_number':ORG},Fetcher(folder,replay=True))
            claims={c['field']:c for c in row['claims']}
            self.assertEqual(claims['website.verified_url']['value'],'https://exampletherapy.no/')
            self.assertEqual(claims['website.description']['value'],'Example Therapy AS har levert behandling siden 2016.')
            self.assertEqual(len(claims['website.contact_channels']['value']),2)
            self.assertTrue(audit([row],folder)['passed'])
            changed=copy.deepcopy(row)
            claim=next(c for c in changed['claims'] if c['field']=='website.verified_url')
            claim['identity_support']['address_source']['registered_postcode']='9999'
            self.assertFalse(audit([changed],folder)['passed'])
            # A useful service description need not repeat the legal name.
            # New identity proof must not replace it with a different sentence.
            url,text=sources[1]
            useful='Professional therapy and rehabilitation for adults and children.'
            text=text.replace('05.10.26: We currently have short waiting times for all ages.',useful)
            rsp={'url':url,'requested_url':url,'text':text,'status':'available','status_code':200,'retrieved_at':'2026-11-01T00:00:00Z','content_sha256':digest(text.encode())}
            (Path(folder)/(digest(url.encode())+'.json')).write_text(encode(rsp))
            preserved=research({'organisation_number':ORG},Fetcher(folder,replay=True))
            self.assertEqual(next(c['value'] for c in preserved['claims'] if c['field']=='website.description'),useful)
