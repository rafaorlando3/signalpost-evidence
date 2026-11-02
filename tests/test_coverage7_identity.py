import unittest

from agent import Page, website_identity
from business_identity import business_identity, street_span


class ContactIdentity(unittest.TestCase):
    DATA = {'organisasjonsnummer': '810034882', 'navn': 'Example Services AS',
            'forretningsadresse': {'adresse': ['Exampleveien 61'], 'postnummer': '2010'}}

    def test_parenthesized_checksum_needs_full_self_name_contact_role_and_brand(self):
        text = '<title>Kontakt – Example Services</title><main><p>Example Services AS (810034882) Exampleveien 61, 2010 Oslo</p></main>'
        def identity(body=text, url='https://example.test/kontakt/'):
            return website_identity('810034882', Page(body, url), self.DATA)
        self.assertEqual(identity(), 'exact')
        for body in [text.replace('810034882','810034883'),
                     text.replace('<p>','<blockquote><p>').replace('</p>','</p></blockquote>'),
                     text.replace('<p>','<div class="customer"><p>').replace('</p>','</p></div>'),
                     text.replace('Example Services AS (','Phone ('),
                     text.replace('Kontakt – Example Services','Contact – Another Brand')]:
            self.assertNotEqual(identity(body), 'exact')
        self.assertNotEqual(identity(url='https://example.test/customer-case/'), 'exact')

    def test_house_first_exact_address_and_theme_flags_preserve_linked_legal_proof(self):
        root = 'https://example.test/'
        def proof(street='61 Exampleveien', wrapper=''):
            home = Page('<body class="hide-article-author product-social-sharing"><title>Example Services</title><a href="/om-oss">Om oss</a></body>',root)
            body = '<body class="hide-article-author product-social-sharing"><title>Om oss</title>'+wrapper+'<p>Example Services AS utfører byggearbeid.</p><p>Example Services '+street+', 2010 Oslo</p>'+('</div>' if wrapper else '')+'</body>'
            about = Page(body,root+'om-oss')
            return business_identity(self.DATA,[(home,{'url':root}),(about,{'url':about.url})],lambda page:True)
        self.assertIsNotNone(proof())
        self.assertIsNone(proof('62 Exampleveien'))
        self.assertIsNone(proof('61 Differentveien'))
        self.assertIsNone(proof(wrapper='<div class="customer-testimonial">'))
        self.assertEqual(street_span('61 Exampleveien','Exampleveien 61')['text'],'61 Exampleveien')
        self.assertIsNone(street_span('61 Exampleveien','Exampleveien 61A'))
        page = Page('<body class="hide-article-author product-social-sharing"><a href="/om-oss">About us</a><div class="author-card"><a href="https://facebook.com/person">Author</a></div></body>',root)
        self.assertFalse(page.links[0]['third_party_context'])
        self.assertTrue(page.links[1]['third_party_context'])
