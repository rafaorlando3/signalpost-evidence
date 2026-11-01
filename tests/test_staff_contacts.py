import unittest
from agent import Page
from contacts import collect_entity_contacts
class StaffContactCards(unittest.TestCase):
    data={'navn':'Example AS','forretningsadresse':{'postnummer':'1234'}}
    def collect(self,body,url='https://example.no/kontakt'):
        p=Page(body,url);return collect_entity_contacts([(p,{'url':url})],self.data)
    def test_formatted_mobile_in_named_role_card_is_literal_contact(self):
        c,held,_=self.collect('<div><h3>Jane Example</h3><p>Daglig leder</p><div>90 86 30 86</div><a href="mailto:jane@example.no">jane@example.no</a></div>')
        self.assertEqual({x['value'] for x in c},{'jane@example.no','90 86 30 86'});self.assertFalse(held)
    def test_id_date_unscoped_bio_and_other_domain_mailbox_are_not_phone_evidence(self):
        body='<div>Jane<p>CEO</p><div>{}</div><a href="mailto:jane@example.no">jane@example.no</a></div>'
        for value in ['90863086','01.11.2026','123 45 678']:
            self.assertFalse(any(x['type']=='phone' for x in self.collect(body.format(value))[0]))
        for html,url in [(body.format('90 86 30 86').replace('CEO','Customer'),'https://example.no/kontakt'),(body.format('90 86 30 86'),'https://example.no/news/jane'),(body.format('90 86 30 86').replace('@example.no','@partner.no'),'https://example.no/kontakt'),('<form>'+body.format('90 86 30 86')+'</form>','https://example.no/kontakt')]:
            self.assertFalse(any(x['type']=='phone' for x in self.collect(html,url)[0]))
    def test_customer_and_foreign_entity_card_cannot_leak_phone(self):
        body='<div><p>Example Shanghai Ltd.</p><p>CEO</p><div>90 86 30 86</div><a href="mailto:jane@example.no">jane@example.no</a></div>'
        c,held,_=self.collect(body);self.assertFalse(c);self.assertTrue(held)
        self.assertFalse(self.collect('<div class="customer">'+body+'</div>')[0])
    def test_foreign_postcode_still_vetoes_card_and_dedup_remains_global(self):
        body='<div><p>CEO</p><p>9999 Othercity</p><div>90 86 30 86</div><a href="mailto:jane@example.no">jane@example.no</a></div>'
        c,held,_=self.collect(body);self.assertFalse(c);self.assertTrue(held)
