"""Positive/negative controls for explicit site declarations, not footer-only proof."""
import json
import unittest
import test_agent
from agent import Page
from attribution import declared_profiles,canonical_profile
from social_ownership import asserted_profiles,company_labels,profile_identifier,conflicting_profiles


class SocialRecovery(unittest.TestCase):
    def observe(self,body,extra=None):
        h=test_agent.R5Precision()
        row=h.observe({h.HOME:'Org nr '+h.ORG+body},extra)
        return h.by_field(row,'website.social_links')

    def test_follow_statement_and_complete_legal_identifier(self):
        c=self.observe('<p>Follow us on <a href="https://facebook.com/example">Facebook</a>.</p>')
        self.assertEqual(c['value'][0]['url'],'https://facebook.com/example')
        self.assertIn('follow_statement',c['value'][0]['ownership_evidence'][0]['method'])

    def test_possessive_company_page_declaration_requires_matching_entity_and_not_another_party(self):
        for prefix,suffix in [('på vår','side'),('on our','page')]:
            c=self.observe('<p>'+prefix+' <a href="https://facebook.com/example">Facebook</a> '+suffix+'</p>')
            self.assertEqual(c['value'][0]['url'],'https://facebook.com/example')
            self.assertIn('company_profile_reference',c['value'][0]['ownership_evidence'][0]['method'])
        for body in ['<p>on their <a href="https://facebook.com/example">Facebook</a> page</p>',
                     '<p>on our <a href="https://facebook.com/othercompany">Facebook</a> page</p>',
                     '<section class="partner"><p>on our <a href="https://facebook.com/example">Facebook</a> page</p></section>']:
            self.assertIsNone(self.observe(body)['value'])

    def test_possessive_declaration_excerpt_keeps_the_literal_phrase_in_long_blocks(self):
        c=self.observe('<div>'+('General company information. '*35)+'<p>på vår <a href="https://facebook.com/example">Facebook</a> side</p></div>')
        proof=c['value'][0]['ownership_evidence'][0]
        self.assertIn('vår Facebook side',proof['context_excerpt'])

    def test_footer_link_alone_stays_unresolved_even_when_name_matches(self):
        c=self.observe('<footer><a href="https://facebook.com/example">Facebook</a></footer>')
        self.assertIsNone(c['value'])

    def test_foreign_template_link_is_not_rescued_by_follow_label(self):
        c=self.observe('<footer><p>Follow us on <a href="https://facebook.com/wix">Facebook</a>.</p></footer>')
        self.assertIsNone(c['value'])

    def test_agency_context_vetoes_even_exact_legal_identifier(self):
        c=self.observe('<section class="webdesign"><p>Follow us <a href="https://facebook.com/example">Facebook</a></p></section>')
        self.assertIsNone(c['value'])

    def test_person_sameAs_overrides_company_follow_statement(self):
        node={'@type':'Person','name':'Example','sameAs':'https://instagram.com/example'}
        c=self.observe('<p>Follow us <a href="https://instagram.com/example">Instagram</a></p>'
                       '<script type="application/ld+json">'+json.dumps(node)+'</script>')
        self.assertIsNone(c['value'])
        self.assertIn('Person',c['qualifiers']['candidate_limitations'][0]['reason'])

    def test_other_organization_sameAs_overrides_matching_follow_control(self):
        node={'@type':'Corporation','legalName':'Different Group AS','sameAs':'https://instagram.com/example'}
        c=self.observe('<nav class="social"><a href="https://instagram.com/example">Instagram</a></nav>'
                       '<script type="application/ld+json">'+json.dumps(node)+'</script>')
        self.assertIsNone(c['value'])
        self.assertIn('another legal entity',c['qualifiers']['candidate_limitations'][0]['reason'])

    def test_parent_identifier_cannot_drop_regional_qualifier(self):
        data={'navn':'Example Norge AS','hjemmeside':'https://example.test/'}
        page=Page('<title>Example Group</title><footer><p>Follow us <a href="https://facebook.com/example">Facebook</a></p></footer>','https://example.test/')
        found,blocked=asserted_profiles([(page,{'url':page.url,'text':'<p>Follow us <a href="https://facebook.com/example">Facebook</a></p>'})],data)
        self.assertEqual(found,{})

    def test_schema_subtype_recovers_only_with_exact_registered_address(self):
        h=test_agent.R5Precision()
        node={'@type':'https://schema.org/Electrician','name':'Example AS','sameAs':'https://instagram.com/example',
              'address':{'streetAddress':'Main gate 12','postalCode':'1234'}}
        body='<script type="application/ld+json">'+json.dumps(node)+'</script>'
        c=self.observe(body,{'forretningsadresse':{'adresse':['Main gate 12'],'postnummer':'1234'}})
        self.assertEqual(c['value'][0]['attribution'],'exact_entity_sameAs_declaration')
        self.assertIsNone(self.observe(body,{'forretningsadresse':{'adresse':['Other street 12'],'postnummer':'1234'}})['value'])

    def test_foreign_number_vetoes_same_name_and_same_site_url(self):
        node={'@type':'Organization','name':'Example AS','url':'https://example.test/','taxID':'974761076',
              'sameAs':'https://instagram.com/example'}
        page=Page('<script type="application/ld+json">'+json.dumps(node)+'</script>','https://example.test/')
        self.assertEqual(declared_profiles([(page,{'url':page.url})],{'navn':'Example AS','organisasjonsnummer':'810034882'}),{})

    def test_norwegian_letters_and_leading_legal_form_match_complete_identity(self):
        data={'navn':'AS Østlandets Blad'}
        page=Page('<title>Østlandets Blad</title>','https://paper.test/')
        self.assertIn(profile_identifier('https://instagram.com/ostlandetsblad'),company_labels(data,page))

    def test_corporate_navigation_matches_two_platforms(self):
        c=self.observe('<header><div><a href="https://facebook.com/example">Facebook</a>'
                       '<a href="https://instagram.com/example">Instagram</a></div></header>')
        self.assertEqual(len(c['value']),2)
        self.assertTrue(all('corporate_navigation' in item['ownership_evidence'][0]['method'] for item in c['value']))

    def test_personal_linkedin_hashtag_and_media_item_are_still_not_profiles(self):
        for url in ('https://linkedin.com/in/example','https://tiktok.com/tag/example',
                    'https://instagram.com/p/example','https://youtube.com/watch?v=example'):
            self.assertIsNone(canonical_profile(url))

    def test_official_localized_linkedin_host_is_normalized(self):
        self.assertEqual(canonical_profile('https://no.linkedin.com/company/example'),'https://linkedin.com/company/example')
        self.assertIsNone(canonical_profile('https://no.linkedin.com.attacker.test/company/example'))

    def test_legacy_facebook_name_and_numeric_id_match_without_accepting_generic_id(self):
        self.assertEqual(profile_identifier('https://facebook.com/Example-AS-123456789'),'exampleas')
        self.assertIsNone(profile_identifier('https://facebook.com/profile.php?id=123456789'))
