import unittest
from agent import Page,website_identity,site_operator_identity
from legal_name_identity import legal_name_identity

class EmailBrandIdentity(unittest.TestCase):
    data={'organisasjonsnummer':'810034882','navn':'ABC AS','epostadresse':'registry@abc.test',
          'forretningsadresse':{'adresse':['Testveien 10'],'postnummer':'4460'}}
    raw='''<title>Produksjonsstyring - ABC AS</title><meta property="og:site_name" content="ABC AS">
    <main><p>Vi utvikler programvare for produksjon.</p></main><footer>
    <h2>Besøksadresse</h2><p>ABC AS, Testveien 10, 4460 Moi</p>
    <p>Telefon 51409500</p></footer>'''
    def proof(self,raw=None,data=None,url='https://abc.test/'):
        data=self.data if data is None else data;pg=Page(self.raw if raw is None else raw,url)
        compatible=lambda p:website_identity(data['organisasjonsnummer'],p,data)!='conflict' and site_operator_identity(data['organisasjonsnummer'],p,data)['state'] not in {'different','unresolved'}
        return legal_name_identity(data,[(pg,{'url':url})],compatible)
    def test_complete_short_legal_name_domain_and_labelled_address_are_reproducible(self):
        p=self.proof();self.assertEqual(p['registry_email_domain_binding'],'abc.test')
        self.assertEqual(p['registered_street'],'Testveien 10')
        self.assertNotIn('registry@abc.test',str(p))
        self.assertIsNotNone(self.proof(self.raw.replace('4460 Moi','NO-4460 Moi')))
    def test_negative_controls(self):
        for raw in [self.raw.replace('4460','4461'),self.raw.replace('Testveien 10','Testveien 12'),
                    self.raw.replace('content="ABC AS"','content="ABC Group"'),
                    self.raw.replace('Besøksadresse','Kunde'),self.raw.replace('<footer>','<aside>').replace('</footer>','</aside>'),
                    self.raw+'<p>Org.nr. 913884213</p>',self.raw.replace('Vi utvikler programvare','Our group consists of several companies. Vi utvikler programvare'),
                    self.raw.replace('ABC AS, Testveien','OTHER AS, Testveien')]:
            with self.subTest(raw=raw):self.assertIsNone(self.proof(raw))
        for patch in [{'epostadresse':'registry@gmail.com'},{'epostadresse':'registry@parent.test'},
                      {'epostadresse':None},{'navn':'ABC BERGEN AS'},{'navn':'ABC ASA'}]:
            with self.subTest(patch=patch):self.assertIsNone(self.proof(data={**self.data,**patch}))
        self.assertIsNone(self.proof(url='https://abc.test/news/customer-abc'))

if __name__=='__main__':unittest.main()
