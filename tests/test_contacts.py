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
