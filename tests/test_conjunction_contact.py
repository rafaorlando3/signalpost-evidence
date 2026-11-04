import unittest
from agent import Page,website_identity,site_operator_identity
from legal_name_identity import legal_name_identity
from registry_discovery import conjunction_name_candidates

class ConjunctionContact(unittest.TestCase):
    data={'organisasjonsnummer':'810034882','navn':'MUR & FLIS AS',
          'forretningsadresse':{'adresse':['Testveien 13'],'postnummer':'4313'}}
    raw='''<title>Mur &amp; Flis – Arbeid i mur</title><h1>Mur &amp; Flis</h1>
    <section><h2>Kontakt oss for et tilbud</h2><h3>Mur &amp; Flis AS, Testveien 13, 4013 Sandnes</h3>
    <p>Ansatt A Tlf. 92606710 Epost: a@murogflis.test</p></section>'''
    def proof(self,raw=None,data=None):
        data=data or self.data;p=Page(self.raw if raw is None else raw,'https://murogflis.test/')
        return legal_name_identity(data,[(p,{'url':p.url})],lambda pg:website_identity(data['organisasjonsnummer'],pg,data)!='conflict' and site_operator_identity(data['organisasjonsnummer'],pg,data)['state'] not in {'different','unresolved'})
    def test_conjunction_is_only_an_untrusted_full_name_url_lead(self):
        self.assertEqual(conjunction_name_candidates(self.data),['https://murogflis.no/','https://mur-og-flis.no/'])
        for name in ['Mur Flis AS','Mur & Flis & Bygg AS','Mur & Flis Holding AS','Mur & Flis Bergen AS']:
            result=conjunction_name_candidates({'navn':name})
            if 'Bergen' in name:self.assertTrue(all('bergen' in u for u in result))
            else:self.assertEqual(result,[])
    def test_explicit_legal_owner_is_not_a_claim_that_postcode_agrees(self):
        p=self.proof();self.assertIsNotNone(p)
        self.assertEqual(p['published_postcode'],'4013');self.assertEqual(p['registered_postcode'],'4313')
        self.assertEqual(p['postcode_state'],'conflicts_with_registry; address not verified')
    def test_negative_contact_identity_controls(self):
        for raw in [self.raw.replace('Mur &amp; Flis AS,','Mur &amp; Flis Bergen AS,'),
                    self.raw.replace('Testveien 13','Otherveien 13'),
                    self.raw.replace('a@murogflis.test','a@parent.test'),
                    self.raw.replace('Tlf. 92606710',''),self.raw.replace('<section>','<section class="customer">'),
                    self.raw.replace('<section>','<form>').replace('</section>','</form>'),
                    self.raw.replace('<section>','<blockquote><section>').replace('</section>','</section></blockquote>'),
                    self.raw.replace('<section>','<aside><section>').replace('</section>','</section></aside>'),
                    self.raw.replace('Kontakt oss for et tilbud','Våre kunder'),self.raw+'<p>Org.nr913884213</p>',
                    self.raw.replace('<title>Mur &amp; Flis','<title>Group Company')]:
            with self.subTest(raw=raw):self.assertIsNone(self.proof(raw))

if __name__=='__main__':unittest.main()
