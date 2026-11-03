import unittest
from agent import Page,corroborated_site
from attribution import group_site_reason
from registry_discovery import scoped_entity_candidates
class ScopedRegistryIdentityTests(unittest.TestCase):
    data={'organisasjonsnummer':'810034882','navn':'EXAMPLE SERVICES BERGEN AS','hjemmeside':'example.no','forretningsadresse':{'adresse':['Storgata 3'],'postnummer':'0001'}}
    def test_group_management_does_not_establish_subsidiary(self):
        p=Page('<title>Om Kompetansehuset Example</title><main><h1>Ledelsen i Example Gruppen</h1>We serve all subsidiaries.</main>','https://example.no/about')
        self.assertIn('differently named group',group_site_reason(p,self.data))
    def test_identity_section_heading_does_not_reject_the_actual_parent_company(self):
        p=Page('<title>Our history</title><meta name="description" content="Our group employs 900 people."><h1>Our history</h1><main>Example Group AS was founded in 1998.</main>','https://example.no/about')
        self.assertIsNone(group_site_reason(p,{'navn':'EXAMPLE GROUP AS'},identity_page=True))
    def test_observed_entity_page_is_preferred_to_generic_root(self):
        from test_agent import R5Precision
        helper=R5Precision()
        row=helper.observe({helper.HOME:'<title>Example</title><a href="/services/bergen">Example Services Bergen</a>',
            helper.HOME+'services/bergen':'<title>Example Services Bergen</title><main>Example Services Bergen AS Storgata 3, 0001 Bergen</main>'},
            {**self.data,'organisasjonsnummer':helper.ORG,'hjemmeside':helper.HOME})
        website=next(c for c in row['claims'] if c['field']=='website.verified_url')
        self.assertEqual(website['value'],helper.HOME+'services/bergen')
        self.assertEqual(website['qualifiers']['site_scope'],'specific company page on a shared host; ownership of the whole host is not inferred')
    def test_local_name_address_block_is_supported(self):
        p=Page('<title>Contact - Example</title><main>Example Services Bergen Storgata 3, 0001 Oslo</main>','https://example.no/contact')
        self.assertTrue(corroborated_site(self.data,p))
    def test_global_legal_entity_directory_is_not_an_own_site(self):
        p=Page('<title>Locations</title><main>Explore our global footprint. Operating Company One Norway AS Storgata 3. Branch Office Two Europe GmbH Another street 5.</main>','https://example.no/locations')
        self.assertIn('global locations directory',group_site_reason(p,self.data))
    def test_single_entity_offices_do_not_trigger_directory_veto(self):
        p=Page('<title>Locations</title><main>Our global footprint: Operating Company One Norway AS Bergen. Operating Company One Norway AS Oslo.</main>','https://example.no/locations')
        self.assertIsNone(group_site_reason(p,self.data))
    def test_only_observed_exact_legal_scope_path_is_a_lead(self):
        p=Page('<a href="/services/bergen">Bergen</a><a href="/services/oslo">Oslo</a><a href="https://other.no/services/bergen">Example Services Bergen</a>','https://example.no/')
        self.assertEqual(scoped_entity_candidates(self.data,p),['https://example.no/services/bergen'])
if __name__=='__main__':unittest.main()
