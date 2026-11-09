import copy,json,unittest
from agent import Page
from legal_name_identity import legal_name_identity
from contact_map_identity import contact_map_identity,contact_map_records

class ScopedPrivacyMapIdentity(unittest.TestCase):
    def data(self):return {'navn':'EXAMPLE WORKS AS','organisasjonsnummer':'810034882','hjemmeside':'www.example.test','forretningsadresse':{'adresse':['Road 12'],'postnummer':'1234'}}
    def privacy(self,body=None):
        root=Page('<title>Example Works</title><a href="/personvernerklaering/">Personvern</a>','https://example.test/')
        text=body or '<p>Denne personvernerklæringen forteller om hvordan Example Works AS samler inn og bruker personopplysninger.</p><p>Vi behandler opplysninger på www.example.test.</p>'
        privacy=Page('<main>'+text+'</main>','https://example.test/personvernerklaering/')
        return [(root,{'url':root.url}),(privacy,{'url':privacy.url})]
    def test_exact_privacy_self_collector_and_literal_host_bind_site(self):
        proof=legal_name_identity(self.data(),self.privacy(),lambda p:True)
        self.assertTrue(proof);self.assertEqual(proof['source_url'],'https://example.test/personvernerklaering/')
        self.assertIn('Example Works AS',proof['self_identification']);self.assertEqual(len(proof['links']),1)
    def test_vendor_different_collector_foreign_host_and_conflict_never_bind(self):
        for body in ['<p>Example Works AS er leverandør av markedsføringstjenester på www.example.test.</p>',
                     '<p>Denne personvernerklæringen forteller om hvordan Parent Group AS samler inn og bruker personopplysninger.</p><p>Example Works AS er leverandør på www.example.test.</p>',
                     '<p>Denne personvernerklæringen forteller om hvordan Example Works AS samler inn og bruker personopplysninger på www.foreign.test.</p>']:
            self.assertIsNone(legal_name_identity(self.data(),self.privacy(body),lambda p:True))
        self.assertIsNone(legal_name_identity(self.data(),self.privacy(),lambda p:False))
    def maps(self,markers=None,host='example.test',brand='Example Works AS',target=True):
        root=Page('<title>'+brand+'</title><a href="/contact">Contact</a>','https://'+host+'/')
        records=markers or [{'title':'Other Subsidiary AS','html':'Other Subsidiary AS<br>Wrong road 99<br>9876 City'}, {'title':'EXAMPLE WORKS AS','html':'<strong>Example Works AS</strong><br>Road 12<br>N-1234 City'}]
        config=json.dumps({'options':{},'markers':records})
        body=('<div id="map42"></div>' if target else '')+"<script>eds1_11(function($){$('#map42').data('mapObject',new edMap_1($('#map42')[0], "+config+"));});</script>"
        contact=Page(body,'https://'+host+'/contact')
        return [(root,{'url':root.url}),(contact,{'url':contact.url})]
    def test_contact_map_selects_one_exact_legal_record_not_other_offices(self):
        proof=contact_map_identity(self.data(),self.maps(),lambda p:True)
        self.assertTrue(proof);self.assertEqual(proof['marker']['json_pointer'],'/markers/1')
        self.assertEqual(proof['registered_street'],'Road 12');self.assertNotIn('Other Subsidiary',proof['marker']['text'])
    def test_map_requires_declared_host_full_brand_marker_address_and_dom(self):
        for pages in [self.maps(host='foreign.test'),self.maps(brand='Parent Group'),self.maps(target=False),
                      self.maps([{'title':'EXAMPLE WORKS AS','html':'Example Works AS Road 12 9999 City'}]),
                      self.maps([{'title':'EXAMPLE WORKS AS','html':'Example Works AS Wrong road 12 1234 City'}]),
                      self.maps([{'title':'Other Subsidiary AS','html':'Example Works AS Road 12 1234 City'}])]:
            self.assertIsNone(contact_map_identity(self.data(),pages,lambda p:True))
        self.assertIsNone(contact_map_identity(self.data(),self.maps(),lambda p:False))
    def test_same_values_in_unrelated_script_are_not_map_proof(self):
        page=Page('<div id="map42"></div><script>var unrelated='+json.dumps({'options':{},'markers':[{'title':'EXAMPLE WORKS AS','html':'Example Works AS Road 12 1234 City'}]})+';</script>','https://example.test/contact')
        self.assertEqual(contact_map_records(page),[])
    def test_record_name_and_address_cannot_be_joined_across_markers(self):
        pages=self.maps([{'title':'EXAMPLE WORKS AS','html':'Example Works AS Wrong road 22 9999 City'}, {'title':'Other AS','html':'Other AS Road 12 1234 City'}])
        self.assertIsNone(contact_map_identity(self.data(),pages,lambda p:True))

    def test_explicit_conflicting_number_inside_marker_overrides_name_and_address(self):
        pages=self.maps([{'title':'EXAMPLE WORKS AS','html':'Example Works AS<br>Road 12<br>1234 City<br>Org.nr. 974 761 076'}])
        self.assertIsNone(contact_map_identity(self.data(),pages,lambda p:True))

    def test_literal_host_boundary_allows_sentence_stop_but_rejects_foreign_suffix_and_email(self):
        good=self.privacy()
        self.assertIsNotNone(legal_name_identity(self.data(),good,lambda p:True))
        for mention in ['www.example.test.foreign.test','office@example.test']:
            body='<p>Denne personvernerklæringen forteller om hvordan Example Works AS samler inn og bruker personopplysninger.</p><p>'+mention+'</p>'
            self.assertIsNone(legal_name_identity(self.data(),self.privacy(body),lambda p:True))
