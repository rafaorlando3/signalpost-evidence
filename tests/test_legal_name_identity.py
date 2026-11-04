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

class CopyrightOwnerTests(unittest.TestCase):
    data=LegalNameIdentityTests.data
    proof=LegalNameIdentityTests.proof
    def test_full_copyright_owner_plus_own_business_introduction(self):
        html='<title>Starina</title><main><p>Vi tilbyr servering og catering for bedrifter over hele landet.</p></main><footer>All Rights Reserved. Starina AS © 2026</footer>'
        p=self.proof(html)
        self.assertIsNotNone(p);self.assertIn('copyright',p['scope']);self.assertEqual(p['copyright_statement'],'All Rights Reserved. Starina AS © 2026')
    def test_copyright_without_own_business_or_with_partial_name_is_insufficient(self):
        self.assertIsNone(self.proof('<title>Starina</title><main>Welcome</main><footer>Starina AS © 2026</footer>'))
        self.assertIsNone(self.proof('<title>Starina</title><main><p>Vi tilbyr servering og catering for bedrifter over hele landet.</p></main><footer>Starina © 2026</footer>'))
    def test_customer_and_agency_copyright_cannot_supply_an_own_introduction(self):
        self.assertIsNone(self.proof('<title>Starina</title><div class="customer"><p>Vi tilbyr servering og catering for bedrifter over hele landet.</p></div><footer>Starina AS © 2026</footer>'))
    def test_parent_brand_is_not_proof_of_a_subsidiary_copyright(self):
        self.assertIsNone(self.proof('<title>Parent Group</title><main><h1>Starina</h1><p>Vi tilbyr servering og catering for bedrifter over hele landet.</p></main><footer>Starina AS © 2026</footer>'))
    def test_duplicate_document_titles_are_not_concatenated(self):
        p=Page('<title>Starina</title><title>Another organisation</title>','https://example.no/')
        self.assertEqual(p.title,'Starina')
    def test_conflicting_operator_overrides_copyright(self):
        self.assertIsNone(self.proof('<title>Starina</title><main><p>Vi tilbyr servering og catering for bedrifter over hele landet.</p>Org.nr 913 884 213</main><footer>Starina AS © 2026</footer>'))

if __name__=='__main__':unittest.main()


class ContactFooterOwner(unittest.TestCase):
    data=LegalNameIdentityTests.data
    proof=LegalNameIdentityTests.proof
    def test_full_legal_contact_footer_and_same_host_email(self):
        p=self.proof('<title>Starina</title><main>Our business</main><footer>Contact Starina AS office@example.no</footer>')
        self.assertIsNotNone(p);self.assertEqual(p['same_host_contact_email'],'office@example.no')
    def test_foreign_email_agency_partial_name_and_parent_brand_do_not_bind(self):
        for html in ['<title>Starina</title><footer>Contact Starina AS office@other.no</footer>',
                     '<title>Starina</title><footer>Website by Contact Starina AS office@example.no</footer>',
                     '<title>Starina</title><footer>Contact Starina office@example.no</footer>',
                     '<title>Parent Group</title><footer>Contact Starina AS office@example.no</footer>',
                     '<title>Starina</title><p>Org.nr 913 884 213</p><footer>Contact Starina AS office@example.no</footer>']:
            with self.subTest(html=html):self.assertIsNone(self.proof(html))


class ContactFooterDescription(unittest.TestCase):
    def test_visible_company_intro_is_selected_instead_of_homepage_news(self):
        from legal_name_identity import contact_footer_business_description
        text='Starina, established in 1986, is a catering business serving Norwegian customers.'
        page=Page('<meta property="og:description" content="'+text+' The president announced a report."><blockquote>'+text+'</blockquote><p>The president announced a report.</p>','https://example.no/')
        self.assertEqual(contact_footer_business_description({'navn':'Starina AS'},page),text)
    def test_metadata_alone_and_another_company_or_news_are_withheld(self):
        from legal_name_identity import contact_footer_business_description as describe
        text='Starina is a catering business serving Norwegian customers across the country.'
        for body,meta in [('<p>Unrelated news story.</p>',text),('<p>'+text+'</p>','Other Company is a different business serving customers across the country.'),('<p>Starina announced a new factory yesterday.</p>','Starina announced a new factory yesterday with a launch party.')]:
            page=Page('<meta property="og:description" content="'+meta+'">'+body,'https://example.no/')
            self.assertIsNone(describe({'navn':'Starina AS'},page))
