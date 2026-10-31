import unittest
from agent import Page
from contacts import contact_links

class Contacts(unittest.TestCase):
    def test_links_are_literal_and_queries_are_not_contact_data(self):
        p=Page('<a href="mailto:info@example.no?subject=Hello">Email</a><a href="tel:+47%2041234567">Call</a>','https://example.no')
        c=contact_links(p)
        self.assertEqual([i['value'] for i in c],['info@example.no','+47 41234567'])
        self.assertEqual(c[0]['source_href'],'mailto:info@example.no?subject=Hello')
        self.assertEqual(c[0]['source_url'],'https://example.no')

    def test_no_fabrication_and_no_sponsor_contact(self):
        p=Page('<p>Guess: support@example.no</p><section class="sponsor"><a href="mailto:other@example.no">Sponsor</a></section>','https://ours.no')
        self.assertEqual(contact_links(p),[])

    def test_reject_invalid_header_injection_and_short_phone(self):
        p=Page('<a href="mailto:info@example.no%0d%0aBcc:other@example.no">No</a><a href="tel:123">No</a><a href="mailto:first@example.no,second@example.no">No</a>','https://ours.no')
        self.assertEqual(contact_links(p),[])

    def test_contact_reordering_does_not_create_refresh_change(self):
        from agent import compare
        def row(values):return {'organisation_number':'810034882','claims':[{'field':'website.contact_channels','value':values,'availability':'available','evidence_ids':['e']}]}
        a={'type':'email','value':'a@example.no'};b={'type':'phone','value':'+4712345678'}
        self.assertEqual(compare(row([a,b]),row([b,a])),[])

    def test_audit_rejects_contact_changed_away_from_source(self):
        from pathlib import Path
        import tempfile,json
        from agent import Fetcher,digest,claim
        from audit import audit
        with tempfile.TemporaryDirectory() as d:
            f=Fetcher(d,replay=True)
            text='<a href="mailto:info@example.no">Email</a>'
            s={'url':'https://example.no','text':text,'content_sha256':digest(text.encode()),'retrieved_at':'2026-09-26T00:00:00Z','status':'available'}
            f.retain(s);ev={};c=claim('website.contact_channels',contact_links(Page(text,s['url'])),s,ev)
            r={'organisation_number':'810034882','evidence':list(ev.values()),'claims':[c]}
            self.assertTrue(audit([r],d)['passed'])
            c['value'][0]['value']='other@example.no'
            self.assertFalse(audit([r],d)['passed'])

class ExactEntityBlocks(unittest.TestCase):
    DATA={'navn':'Example AS','forretningsadresse':{'adresse':['Road 12'],'postnummer':'9015','poststed':'TROMSØ','kommune':'TROMSØ'}}
    def test_shared_page_does_not_merge_other_legal_company_contacts(self):
        from contacts import entity_contacts
        p=Page('<section><h3>Contact Example Tromsø</h3><p><a href="mailto:ours@example.no">Email</a></p><p>Road 12</p><p>9015 Tromsø</p><h3>Contact Example Bodø</h3><p><a href="mailto:bodo@example.no">Email</a></p><p>Road 52</p><p>8006 Bodø</p></section>','https://example.no/contact')
        keep,held=entity_contacts(p,self.DATA)
        self.assertEqual([x['value'] for x in keep],['ours@example.no'])
        self.assertEqual([x['value'] for x in held],['bodo@example.no'])

    def test_registered_target_subunit_is_not_treated_as_another_company(self):
        from contacts import entity_contacts
        p=Page('<h3>Contact Bodø</h3><a href="mailto:bodo@example.no">Email</a><p>8006 Bodø</p>','https://example.no/contact')
        keep,held=entity_contacts(p,self.DATA,[{'address':{'postnummer':'8006','poststed':'BODØ'}}])
        self.assertEqual(len(keep),1);self.assertEqual(held,[])

    def test_unregistered_regional_staff_page_stays_unresolved(self):
        from contacts import entity_contacts
        body='<title>Ansatte i Bodø | Example AS</title><h1>Ansatte i Bodø</h1><a href="tel:12345678">Call</a>'
        keep,held=entity_contacts(Page(body,'https://example.no/staff'),self.DATA)
        self.assertEqual(keep,[]);self.assertEqual(len(held),1)
        body=body.replace('Bodø','Tromsø')
        keep,held=entity_contacts(Page(body,'https://example.no/staff'),self.DATA)
        self.assertEqual(len(keep),1);self.assertEqual(held,[])

class VisibleCompanyContacts(unittest.TestCase):
    DATA={'navn':'Example AS','forretningsadresse':{'adresse':['Road 12'],'postnummer':'9015','poststed':'TROMSØ'}}
    def test_visible_contacts_are_literal_not_invented_mailto_links(self):
        from contacts import entity_contacts
        html='<h2>Contact</h2><p>info@example.no</p><p>Telefon: +47 12345678</p>'
        items,_=entity_contacts(Page(html,'https://example.no'),self.DATA)
        self.assertEqual({i['value'] for i in items},{'info@example.no','+47 12345678'})
        self.assertTrue(all(i['source_href'] is None and i['source_kind']=='literal_visible_text' for i in items))

    def test_visible_other_regional_company_contacts_are_still_withheld(self):
        from contacts import entity_contacts
        html='<h3>Contact Tromsø</h3><p>ours@example.no</p><p>9015 Tromsø</p><h3>Contact Bodø</h3><p>other@example.no</p><p>8006 Bodø</p>'
        items,held=entity_contacts(Page(html,'https://example.no/contact'),self.DATA)
        self.assertEqual([i['value'] for i in items],['ours@example.no'])
        self.assertEqual([i['value'] for i in held],['other@example.no'])

    def test_unlabelled_body_and_telephone_like_identifiers_are_not_contacts(self):
        from contacts import entity_contacts
        p=Page('<p>support@example.no</p><h2>Contact</h2><p>Org nr 810034882</p><p>Year 2026</p>','https://example.no')
        items,_=entity_contacts(p,self.DATA);self.assertEqual(items,[])

class VisibleThirdPartyExclusion(unittest.TestCase):
    def test_plain_agency_contact_in_company_footer_is_not_promoted(self):
        from contacts import entity_contacts
        p=Page('<footer><h3>Contact</h3><p>office@example.no</p><div class="webdesign agency"><p>agency@other.no</p><p>Tel: 12345678</p></div></footer>','https://example.no')
        items,_=entity_contacts(p,{'navn':'Example AS'})
        self.assertEqual([x['value'] for x in items],['office@example.no'])

class SemanticContactContainers(unittest.TestCase):
    def test_builder_footer_and_contact_component_preserve_literal_channels(self):
        from contacts import entity_contacts
        html='<div class="siteFooter"><div class="contactInfo"><p>office@example.no</p><p>+4712345678</p><p>Org nr 810034882</p></div><div class="agency"><p>agency@other.no</p></div></div>'
        items,_=entity_contacts(Page(html,'https://example.no'),{'navn':'Example AS'})
        self.assertEqual({x['value'] for x in items},{'office@example.no','+4712345678'})
        html='<article><div class="entryFooter"><p>author@other.no</p></div></article>'
        items,_=entity_contacts(Page(html,'https://example.no/news/post'),{'navn':'Example AS'})
        self.assertEqual(items,[])
