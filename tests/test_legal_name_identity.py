import unittest
from agent import Page, website_identity, site_operator_identity
from legal_name_identity import legal_name_identity,literal_name

class LegalNameIdentityTests(unittest.TestCase):
    data={'organisasjonsnummer':'967292907','navn':'STARINA AS'}
    def proof(self,html,data=None):
        data=data or self.data;p=Page(html,'https://example.no/');rsp={'url':p.url}
        return legal_name_identity(data,[(p,rsp)],lambda pg:website_identity(data['organisasjonsnummer'],pg,data)!='conflict' and site_operator_identity(data['organisasjonsnummer'],pg,data)['state'] not in {'different','unresolved'})
    def test_scoped_legal_self_description(self):
        self.assertIsNotNone(self.proof('<title>Starina</title><main><p>Starina AS består av to avdelinger som leverer mat.</p></main>'))
    def test_short_complete_legal_name_with_own_business_statement(self):
        data={**self.data,'navn':'NORDIK AS'}
        self.assertIsNotNone(self.proof('<title>Nordik</title><main><p>Nordik AS ble etablert i Norge og leverer byggtjenester.</p></main>',data))
        self.assertIsNone(self.proof('<title>Nordik</title><main><p>Nordik Industries LLC supplies outdoor equipment.</p></main>',data))

    def test_brand_or_registry_link_alone_is_insufficient(self):
        self.assertIsNone(self.proof('<title>Starina</title><main><p>Velkommen til vår nye hjemmeside.</p></main>'))
    def test_customers_quotes_and_web_agency_do_not_establish_identity(self):
        for context in ['blockquote','aside','footer','div class="customer"','div class="testimonial"','div class="webdesign"']:
            with self.subTest(context=context):
                tag=context.split()[0]
                self.assertIsNone(self.proof('<title>Starina</title><'+context+'><p>Starina AS er vår gode samarbeidspartner i Norge.</p></'+tag+'>'))
    def test_other_org_vetoes_name(self):
        self.assertIsNone(self.proof('<title>Starina</title><main><p>Starina AS er en bedrift.</p><p>Org.nr 913 884 213</p></main>'))
    def test_legal_differentiators_not_dropped(self):
        self.assertIsNone(self.proof('<title>Starina</title><main><p>Starina AS er en bedrift.</p></main>',{**self.data,'navn':'STARINA OSLO AS'}))
    def test_norwegian_equivalence_preserves_source_offsets(self):
        text='Kontakt: ÆØÅ Elektriske AS i Norge'
        span=literal_name(text,'AEOA ELEKTRISKE AS')
        self.assertEqual(span['text'],'ÆØÅ Elektriske AS');self.assertEqual(text[span['start']:span['end']],span['text'])
        self.assertIsNotNone(self.proof('<title>AEOA Elektriske</title><main><p>ÆØÅ Elektriske AS er en bedrift i Norge.</p></main>',{**self.data,'navn':'AEOA ELEKTRISKE AS'}))
    def test_contact_requires_observed_same_host_link(self):
        home=Page('<title>Starina</title><a href="/contact/">Kontakt</a>','https://example.no/')
        contact=Page('<main><div>Starina AS Telefon: 12345678 Storgata 1, 1234 Oslo</div></main>','https://example.no/contact/')
        pairs=[(p,{'url':p.url}) for p in [home,contact]]
        self.assertIsNotNone(legal_name_identity(self.data,pairs,lambda p:True))
        unlinked=Page('<title>Starina</title>','https://example.no/')
        self.assertIsNone(legal_name_identity(self.data,[(unlinked,{'url':unlinked.url}),pairs[1]],lambda p:True))

if __name__=='__main__':unittest.main()
