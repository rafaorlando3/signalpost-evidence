import unittest
from agent import Page
from contacts import collect_entity_contacts

class RegionalContactCards(unittest.TestCase):
    DATA={'navn':'Example Norway AS','organisasjonsnummer':'810034882','forretningsadresse':{'postnummer':'0250','poststed':'OSLO'}}
    def collect(self,body):
        p=Page(body,'https://example.com/contact')
        return collect_entity_contacts([(p,{'url':p.url})],self.DATA)
    def test_foreign_region_mailbox_vetoes_repeated_unlabelled_staff_phone(self):
        body='''<div><p>Marie</p><p>CEO, Example Sweden</p><a href="mailto:marie@example.se">Email</a></div>
        <div><p>Marie</p><p>CEO</p><a href="mailto:marie@example.se">Email</a><a href="tel:+46701961011">Phone</a></div>
        <div><p>Christian</p><p>CEO, Example Norway</p><a href="mailto:christian@example.no">Email</a><a href="tel:+4793486848">Phone</a></div>'''
        items,held,_=self.collect(body)
        self.assertEqual({x['value'] for x in items},{'christian@example.no','+4793486848'})
        self.assertTrue(any(x['value']=='+46701961011' for x in held))
    def test_foreign_number_alone_does_not_remove_own_company_contact(self):
        items,_,_=self.collect('<div>Example Norway AS<a href="mailto:ours@example.se">Email</a><a href="tel:+46701961011">Phone</a></div>')
        self.assertEqual(len(items),2)
    def test_country_word_without_matching_mailbox_is_not_an_entity_veto(self):
        items,_,_=self.collect('<div>CEO, Example Sweden<a href="mailto:ours@example.no">Email</a><a href="tel:+4793486848">Phone</a></div>')
        self.assertEqual(len(items),2)
    def test_parent_container_does_not_capture_neighbouring_region(self):
        items,_,_=self.collect('<section><div>CEO, Example Sweden<a href="mailto:foreign@example.se">Email</a></div><div>CEO, Example Norway<a href="mailto:ours@example.no">Email</a></div></section>')
        self.assertEqual([x['value'] for x in items],['ours@example.no'])
    def test_plain_target_without_region_keeps_own_foreign_branch(self):
        self.DATA={**self.DATA,'navn':'Example AS'}
        items,_,_=self.collect('<div>CEO, Example Sweden<a href="mailto:ours@example.se">Email</a></div>')
        self.assertEqual(len(items),1)
    def test_other_staff_country_domain_needs_explicit_regional_owner_first(self):
        proof='<div>CEO, Example Sweden<a href="mailto:ceo@example.se">Email</a></div>'
        card='<div><h3>Finance officer</h3><a href="mailto:finance@example.se">Email</a><a href="tel:+46706394439">Phone</a></div>'
        items,_,_=self.collect(card)
        self.assertEqual(len(items),2)
        items,held,_=self.collect(proof+card)
        self.assertEqual(items,[])
        self.assertTrue(any(x['value']=='+46706394439' for x in held))
    def test_target_named_card_preserves_shared_country_mailbox(self):
        body='<div>CEO, Example Sweden<a href="mailto:ceo@example.se">Email</a></div><div>Example Norway AS<a href="mailto:ours@example.se">Email</a><a href="tel:+46706394439">Phone</a></div>'
        items,_,_=self.collect(body)
        self.assertEqual({x['value'] for x in items},{'ours@example.se','+46706394439'})
    def test_explicit_group_director_is_separate_from_regional_company(self):
        body='<div>CEO, Example Group<a href="mailto:group@example.com">Email</a></div><div><p>Group director</p><a href="mailto:group@example.com">Email</a><a href="tel:+447778686763">Phone</a></div><div>Example Norway AS<a href="mailto:ours@example.com">Email</a></div>'
        items,_,_=self.collect(body)
        self.assertEqual([x['value'] for x in items],['ours@example.com'])
    def test_scoped_foreign_office_phone_cannot_return_via_unscoped_footer(self):
        body='<div><p>Example Finland</p><p>00100 Helsinki</p><a href="tel:+358500482454">Call</a></div><footer>Contact<p>+358 50 048 2454</p></footer>'
        items,held,_=self.collect(body)
        self.assertEqual(items,[])
        self.assertTrue(held)
    def test_unregistered_address_without_foreign_phone_does_not_create_domain_veto(self):
        items,_,_=self.collect('<footer>Contact<p>+358 50 048 2454</p></footer>')
        self.assertEqual(len(items),1)
