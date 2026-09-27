import unittest
from site_discovery import xml_candidates
from agent import Page,crawl_company,identity_excerpt
from test_discovery import Pages,ORG

class SiteDiscovery(unittest.TestCase):
    def test_sitemap_filters_hosts_credentials_and_duplicates(self):
        text='<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+''.join('<url><loc>'+u+'</loc></url>' for u in ['https://example.test/news/a','https://example.test/news/a#same','https://other.test/news/b','https://x:secret@example.test/news/c','file:///etc/passwd'])+'</urlset>'
        pages,maps=xml_candidates(text,'https://example.test/sitemap.xml','example.test')
        self.assertEqual(pages,['https://example.test/news/a']);self.assertEqual(maps,[])

    def test_xml_entities_and_unexpected_documents_are_rejected(self):
        for text in ['<!DOCTYPE x [<!ENTITY a "test">]><urlset/>','<html><loc>https://example.test/news/x</loc></html>','broken']:
            self.assertEqual(xml_candidates(text,'https://example.test/sitemap.xml','example.test'),([],[]))

    def test_feed_is_discovery_and_does_not_export_dates_as_claims(self):
        pages,maps=xml_candidates('<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>News</title><updated>2026-01-01</updated><link href="/news/one"/><link rel="self" href="/feed"/></entry></feed>','https://example.test/feed','example.test')
        self.assertEqual(pages,['https://example.test/news/one']);self.assertEqual(maps,[])

    def test_nested_sitemap_discovers_unlinked_contact(self):
        home={'url':'https://example.test/','text':'<h1>Example</h1>'}
        f=Pages({'https://example.test/sitemap.xml':'<sitemapindex><sitemap><loc>https://example.test/pages.xml</loc></sitemap></sitemapindex>',
            'https://example.test/pages.xml':'<urlset><url><loc>https://example.test/contact</loc></url></urlset>',
            'https://example.test/contact':'Org nr '+ORG})
        verified,pages=crawl_company(ORG,{},home,f)
        self.assertTrue(verified);self.assertIn('https://example.test/contact',f.visited)

    def test_sitemap_cycles_are_bounded(self):
        home={'url':'https://example.test/','text':'<h1>Example</h1>'}
        f=Pages({'https://example.test/sitemap.xml':'<sitemapindex><sitemap><loc>https://example.test/sitemap.xml</loc></sitemap></sitemapindex>'})
        crawl_company(ORG,{},home,f)
        self.assertEqual(f.visited,['https://example.test/sitemap.xml'])

    def test_visible_article_metadata_does_not_take_script_text(self):
        p=Page('<h1>Factory <b>opens</b></h1><time itemprop="datePublished" datetime="2026-09-01">1 September</time><script><h1>Fake</h1></script>','https://example.test/news/factory')
        self.assertEqual(p.headings,['Factory opens']);self.assertEqual(p.times,['2026-09-01'])

    def test_modification_dates_are_not_publication_dates(self):
        p=Page('<time class="updated" datetime="2026-09-01">Updated</time><time datetime="2026-09-02">Unlabelled</time>','https://example.test/news/a')
        self.assertEqual(p.times,[])

    def test_identity_excerpt_contains_footer_proof_after_long_content(self):
        p=Page('<p>'+'Text '*1000+'</p><footer>Org.nr 810 034 882</footer>','https://example.test')
        excerpt=identity_excerpt(ORG,p)
        self.assertIn('810 034 882',excerpt);self.assertLess(len(excerpt),400)

if __name__=='__main__':unittest.main()
