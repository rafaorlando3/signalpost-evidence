import unittest
from agent import Page,corroborated_site,corroboration_evidence

class MultilineRegistryAddress(unittest.TestCase):
    data={'organisasjonsnummer':'810034882','navn':'EXAMPLE BARNEHAGE AS','hjemmeside':'example.test',
          'forretningsadresse':{'adresse':['Bråstadhuset','Frolandsveien 307'],'postnummer':'4848'}}
    raw='<title>Example Barnehage</title><h1>Example Barnehage</h1><p>Kontakt Example Barnehage Frolandsveien 307 4848 Arendal</p>'
    def test_second_registered_line_is_literal_street_proof_not_a_guess(self):
        p=Page(self.raw,'https://example.test/')
        self.assertTrue(corroborated_site(self.data,p))
        proof=corroboration_evidence(self.data,p,{'url':p.url})
        self.assertEqual(proof['registry_street'],'Frolandsveien 307')
        self.assertTrue(all(p.text[s['start']:s['end']]==s['text'] for s in proof['literal_spans']))
    def test_group_mention_shared_address_and_partial_street_do_not_establish_identity(self):
        for raw in [self.raw.replace('<title>Example Barnehage</title>','<title>Example Group</title>'),
                    self.raw.replace('Frolandsveien 307','Frolandsveien 309'),self.raw.replace('4848','4849'),
                    self.raw+'<p>Org.nr 913884213</p>']:
            with self.subTest(raw=raw):self.assertFalse(corroborated_site(self.data,Page(raw,'https://example.test/')))
        self.assertFalse(corroborated_site({**self.data,'hjemmeside':'parent.test'},Page(self.raw,'https://example.test/')))

if __name__=='__main__':unittest.main()
