import unittest
from agent import Page,website_identity,link_family,article_detail,social_profile,crawl_company

ORG='810034882'

class Pages:
    requests=0
    limit=20
    def __init__(self,pages):self.pages=pages;self.visited=[]
    def get(self,url,**kwargs):
        self.visited.append(url);self.requests+=1
        return {'url':url,'status':'available','text':self.pages.get(url,''),'retrieved_at':'2026-09-26T00:00:00+00:00'}

class Discovery(unittest.TestCase):
    def test_english_and_norwegian_tax_labels(self):
        for text in ('Org. no. 810 034 882','Organisation number: 810034882','NO 810034882 MVA','Org.nr - 810 034 882','Org: 810034882'):
            self.assertEqual(website_identity(ORG,Page(text,'https://example.test')),'exact')
        self.assertEqual(website_identity(ORG,Page('order no 810034882','https://example.test')),'ambiguous')

    def test_distinguish_news_from_newsletter_and_static_index(self):
        self.assertEqual(link_family('https://example.test/personvern'),'identity')
        self.assertIsNone(link_family('https://example.test/nyhetsbrev'))
        self.assertFalse(article_detail('https://example.test/nyheter/'))
        self.assertTrue(article_detail('https://example.test/nyheter/new-factory/'))

    def test_share_controls_are_not_company_profiles(self):
        self.assertTrue(social_profile('https://www.instagram.com/example/'))
        self.assertTrue(social_profile('https://www.linkedin.com/company/example/'))
        self.assertFalse(social_profile('https://facebook.com/sharer.php?u=x'))
        self.assertFalse(social_profile('https://x.com/intent/tweet'))
        self.assertFalse(social_profile('https://youtube.com/watch?v=123'))
        self.assertFalse(social_profile('https://evil.test/facebook.com/example'))

    def test_follow_privacy_identity_then_news_detail(self):
        home={'url':'https://example.test/','status':'available','text':'<a href="/personvern">Privacy</a><a href="/nyheter/">News</a>'}
        f=Pages({'https://example.test/personvern':'Org. no. '+ORG,
            'https://example.test/nyheter/':'<a href="/nyheter/new-factory/">New factory</a>',
            'https://example.test/nyheter/new-factory/':'<h1>New factory</h1><meta property="article:published_time" content="2026-09-01">'})
        verified,all_pages=crawl_company(ORG,{},home,f)
        self.assertTrue(verified)
        self.assertIn('https://example.test/nyheter/new-factory/',f.visited)
        self.assertEqual(next(p for p,r,i in all_pages if p.url.endswith('new-factory/')).meta['article:published_time'],'2026-09-01')

    def test_wrong_company_does_not_trigger_deeper_crawl(self):
        f=Pages({});home={'url':'https://example.test/','text':'Org no 987654321 <a href="/personvern">Privacy</a>'}
        verified,pages=crawl_company(ORG,{},home,f)
        self.assertEqual(verified,[]);self.assertEqual(f.visited,[])

    def test_contact_anchor_works_with_opaque_php_url(self):
        f=Pages({'https://example.test/page3.php':'Org nr '+ORG})
        home={'url':'https://example.test/','text':'<a href="page3.php">Kontakt</a>'}
        verified,_=crawl_company(ORG,{},home,f)
        self.assertEqual(len(verified),1)

    def test_crawl_has_page_bound(self):
        links=' '.join(f'<a href="/nyheter/post-{i}">Post</a>' for i in range(100))
        f=Pages({});home={'url':'https://example.test/','text':'Org no '+ORG+links}
        crawl_company(ORG,{},home,f)
        self.assertLessEqual(len([u for u in f.visited if not u.endswith('.xml')]),8)
        self.assertLessEqual(len(f.visited),11)

if __name__=='__main__':unittest.main()

class ThirdPartySocialLinks(unittest.TestCase):
    def test_share_home_and_posts_are_not_profiles(self):
        for url in ('https://twitter.com/home?status=example','https://www.instagram.com/p/example/',
                    'https://x.com/example/status/123','https://linkedin.com/shareArticle?url=x'):
            self.assertFalse(social_profile(url))
        self.assertTrue(social_profile('https://facebook.com/p/Example-Business-123/'))

    def test_sponsor_context_does_not_leak_to_next_own_social_link(self):
        page=Page('<section class="sponsors"><a href="https://facebook.com/other">Sponsor</a></section>'
                  '<footer><a href="https://facebook.com/ours">Our Facebook</a></footer>','https://example.test')
        self.assertTrue(page.links[0]['third_party_context'])
        self.assertFalse(page.links[1]['third_party_context'])

    def test_sponsor_image_alt_also_identifies_third_party_link(self):
        page=Page('<a href="https://facebook.com/other"><img alt="Sponsor logo #7" src="x"></a>', 'https://example.test')
        self.assertTrue(page.links[0]['third_party_context'])

    def test_empty_boolean_html_attributes_do_not_abort_company(self):
        page=Page('<section class><a href="https://facebook.com/ours"><img alt src="x"></a></section>', 'https://example.test')
        self.assertEqual(len(page.links),1)
        self.assertFalse(page.links[0]['third_party_context'])
