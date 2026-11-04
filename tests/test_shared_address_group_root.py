"""A menu mention cannot borrow a differently named legal owner's address."""
import unittest
from agent import Page,corroborated_site
from registry_discovery import scoped_entity_candidates

class SharedAddressOwnerTests(unittest.TestCase):
    data={'organisasjonsnummer':'810034882','navn':'EXAMPLE ARCHITECTS AS','hjemmeside':'example.no','forretningsadresse':{'adresse':['Storgata 3'],'postnummer':'0001'}}
    def test_parent_contact_address_and_subsidiary_menu_do_not_bind_root(self):
        page=Page('<title>Example Norway</title><nav><a href="/example-architects/">Example Architects</a></nav><main>We serve all customers.</main><footer>Example Norway AS Storgata 3, 0001 Oslo Phone: +47 22222222</footer>','https://example.no/')
        self.assertFalse(corroborated_site(self.data,page))
        self.assertEqual(scoped_entity_candidates(self.data,page),['https://example.no/example-architects/'])
    def test_real_own_legal_contact_footer_still_binds_root(self):
        page=Page('<title>Example Architects</title><footer>Example Architects AS Storgata 3, 0001 Oslo</footer>','https://example.no/')
        self.assertTrue(corroborated_site(self.data,page))
    def test_scoped_entity_page_is_not_the_whole_group(self):
        page=Page('<title>Example Architects</title><main>Example Architects Storgata 3, 0001 Oslo</main><footer>Example Norway AS Storgata 3, 0001 Oslo</footer>','https://example.no/example-architects/')
        self.assertTrue(corroborated_site(self.data,page))
    def test_foreign_address_only_does_not_veto_the_own_address(self):
        page=Page('<title>Example Architects</title><main>Example Architects Storgata 3, 0001 Oslo</main><footer>Example Norway AS Another road 9, 9999 Oslo</footer>','https://example.no/')
        self.assertTrue(corroborated_site(self.data,page))
    def test_observed_scope_retains_every_name_component(self):
        page=Page('<a href="/example-architects/">Example Architects</a><a href="/architects/">Architects</a><a href="/example/">Example</a><a href="https://other.no/example-architects/">Example Architects</a><a href="/example-architects/?preview=1">Example Architects</a>','https://example.no/')
        self.assertEqual(scoped_entity_candidates(self.data,page),['https://example.no/example-architects/'])
    def test_full_name_on_own_root_with_additional_entity_is_preserved(self):
        page=Page('<title>Example Architects</title><main>Example Architects AS Storgata 3, 0001 Oslo</main><footer>Example Architects AS Storgata 3, 0001 Oslo. Example Norway AS Storgata 3, 0001 Oslo</footer>','https://example.no/')
        self.assertTrue(corroborated_site(self.data,page))
if __name__=='__main__':unittest.main()
