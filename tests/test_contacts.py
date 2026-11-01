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

class ArchiveContacts(unittest.TestCase):
    def test_archive_mentions_do_not_turn_other_businesses_into_company_contacts(self):
        from agent import Page
        from contacts import entity_contacts
        page=Page('<a href="mailto:staff@example.test">Staff</a><p>Office tenant <a href="mailto:tenant@other.test">Tenant</a></p>','https://example.test/news/page/2/')
        accepted,held=entity_contacts(page,{'navn':'Example AS'},[])
        self.assertIn('staff@example.test',[c['value'] for c in accepted])
        self.assertNotIn('tenant@other.test',[c['value'] for c in accepted])
        self.assertTrue(any('archive' in c['reason'] for c in held))

class CrossPageContactIdentity(unittest.TestCase):
    DATA={'navn':'Example AS'}

    def test_foreign_subsidiary_vetoes_repeated_staff_card_and_local_phone(self):
        from contacts import collect_entity_contacts
        staff=Page('<h1>Employees</h1><div class="employee"><p>Jane</p><a href="mailto:jane@example.no">Email</a><a href="tel:021 5046 0806">Phone</a></div><div class="employee"><a href="mailto:ours@example.no">Email</a><a href="tel:+47 12345678">Call</a></div>','https://example.no/contact')
        offices=Page('<article><h3>Foreign office</h3><div><p>Example Shanghai Co., Ltd.<br>Shanghai</p><p>Tel: +86 21 5046 0806<br>Email: jane@example.no</p></div></article>','https://example.no/offices')
        items,held,sources=collect_entity_contacts([(staff,{'url':staff.url}),(offices,{'url':offices.url})],self.DATA)
        self.assertEqual({x['value'] for x in items},{'ours@example.no','+47 12345678'})
        self.assertTrue(any(x['value']=='021 5046 0806' and x.get('conflicting_entity_binding') for x in held))
        self.assertEqual(len(sources),2)

    def test_exact_target_foreign_branch_is_not_a_separate_entity(self):
        from contacts import entity_contacts
        page=Page('<article><p>Example AS<br>China Office</p><p><a href="tel:+86 21 1234 5678">Call</a><a href="mailto:china@example.no">Email</a></p></article>','https://example.no/contact')
        items,held=entity_contacts(page,self.DATA)
        self.assertIn('china@example.no',{x['value'] for x in items})
        self.assertFalse(held)

    def test_other_entity_channel_cannot_return_from_literal_footer(self):
        from contacts import collect_entity_contacts
        a=Page('<footer><p>Contact</p><p>subsidiary@example.no</p></footer>','https://example.no/')
        b=Page('<div><p>Example Subsidiary AS</p><p>Email: subsidiary@example.no</p></div>','https://example.no/offices')
        channels,held,_=collect_entity_contacts([(a,{'url':a.url}),(b,{'url':b.url})],self.DATA)
        self.assertFalse(channels)
        self.assertTrue(held)

    def test_global_dedup_keeps_literal_sources_and_distinct_extensions(self):
        from contacts import collect_entity_contacts,contact_key
        a=Page('<a href="tel:12345678">Call</a><a href="mailto:Info@example.no">Email</a><a href="tel:+4712345678;ext=1">Desk1</a>','https://example.no/')
        b=Page('<a href="tel:0047 12 34 56 78">Call</a><a href="mailto:info@example.no">Email</a><a href="tel:+4712345678;ext=2">Desk2</a>','https://example.no/contact')
        channels,held,sources=collect_entity_contacts([(a,{'url':a.url}),(b,{'url':b.url})],self.DATA)
        self.assertEqual(len(channels),4)
        self.assertEqual(len({contact_key(x) for x in channels}),4)
        self.assertEqual(sum(len(x.get('additional_source_variants',[])) for x in channels),2)
        self.assertEqual(len(sources),2)
        self.assertEqual(held,[])

    def test_own_imprint_label_and_provider_credit_do_not_steal_contacts(self):
        from contacts import collect_entity_contacts
        for label in ['Bedrift: Example AS','Om Example AS','EVP Communications officer, Example AS']:
            page=Page('<footer><p>'+label+'</p><a href="mailto:ours@example.no">Email</a><p>Website by Other Studio AS</p></footer>','https://example.no/')
            channels,held,_=collect_entity_contacts([(page,{'url':page.url})],self.DATA)
            self.assertEqual([x['value'] for x in channels],['ours@example.no'])
            self.assertEqual(held,[])

    def test_similarly_named_other_company_is_not_own_and_neighbour_is_preserved(self):
        from contacts import collect_entity_contacts
        page=Page('<section><div><p>Northern Example AS</p><a href="mailto:other@example.no">Other</a><a href="tel:+4711111111">Call</a></div><div><a href="mailto:ours@example.no">Ours</a><a href="tel:+4722222222">Call</a></div></section>','https://example.no/contact')
        channels,held,_=collect_entity_contacts([(page,{'url':page.url})],self.DATA)
        self.assertEqual({x['value'] for x in channels},{'ours@example.no','+4722222222'})

    def test_accent_variant_with_exact_registered_id_is_not_another_legal_entity(self):
        from contacts import collect_entity_contacts
        page=Page('<div><p>Bodèn Example AS</p><p>Org nr 810 034 882</p><a href="tel:12345678">Call</a></div>','https://example.no/contact')
        channels,held,_=collect_entity_contacts([(page,{'url':page.url})],{'navn':'BODEN EXAMPLE AS','organisasjonsnummer':'810034882'})
        self.assertEqual(len(channels),1)
        self.assertEqual(held,[])

    def test_outlets_only_recover_target_registered_city_and_footer_cannot_reenter(self):
        from contacts import entity_contacts
        data={'navn':'Example AS','forretningsadresse':{'postnummer':'4950','poststed':'RISØR'}}
        page=Page('<h2>Example Risør</h2><p>Tel: 47 47 11 25</p><h2>Example Sannidal</h2><p>Tel: 45 97 86 71</p><footer><h3>Contact</h3><p>3766 Sannidal</p><a href="mailto:group@other.no">Email</a><p>Example AS</p><p>group@other.no</p></footer>','https://example.no/utsalgene')
        channels,held=entity_contacts(page,data)
        self.assertEqual([c['value'] for c in channels],['47 47 11 25'])
        self.assertTrue(any(c['value']=='group@other.no' for c in held))
