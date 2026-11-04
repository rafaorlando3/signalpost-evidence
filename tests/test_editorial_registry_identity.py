import unittest
from agent import Page,corroborated_site


class EditorialRegistryIdentity(unittest.TestCase):
    data={'organisasjonsnummer':'810034882','navn':'Example North AS',
          'hjemmeside':'www.group.test',
          'postadresse':{'adresse':['Postboks 20'],'postnummer':'1234'}}
    raw=('<title>Places in our network</title><meta property="og:site_name" content="Example Group">'
         '<main><h1>Places available</h1><p>Our network includes Example North, Example South and Example East.</p></main>'
         '<footer>Example Group Postboks 20, 1234 Oslo</footer>')

    def test_subsidiary_mention_in_group_article_plus_shared_postal_address_is_not_owner(self):
        self.assertFalse(corroborated_site(self.data,Page(self.raw,'https://group.test/news/places')))

    def test_full_legal_footer_owner_or_complete_own_site_brand_preserves_corroboration(self):
        for raw in [self.raw.replace('Example Group Postboks','Example North AS Postboks'),
                    self.raw.replace('content="Example Group"','content="Example North"')]:
            self.assertTrue(corroborated_site(self.data,Page(raw,'https://group.test/news/places')))

    def test_full_brand_does_not_override_foreign_corporate_number(self):
        raw=self.raw.replace('content="Example Group"','content="Example North"')+'<footer>Org.nr 913884213</footer>'
        self.assertFalse(corroborated_site(self.data,Page(raw,'https://group.test/news/places')))


if __name__=='__main__':unittest.main()
