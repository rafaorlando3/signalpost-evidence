import unittest
from agent import Page,activity_candidates
from publication import publication_block
from hiring_discovery import direct_recruiting_post

class PublicationBlocks(unittest.TestCase):
    url='https://example.test/news/update'
    def block(self,html):return publication_block(Page(html,self.url))
    def test_published_label_wins_over_other_preview_dates(self):
        body='<div class="publish-date publish-date--article"><p>Published on August 12th, 2026</p></div><aside><time>October 5th, 2026</time></aside><div class="news-preview"><div class="publish-date--article">Published on September 11th, 2026</div></div>'
        self.assertEqual(self.block(body)['date'],'2026-08-12')
    def test_span_published_is_separate_from_hidden_updated(self):
        body='<span class="meta-date date published">20. oktober 2026</span><span class="meta-date date updated rich-snippet-hidden">oktober 21st, 2026</span>'
        self.assertEqual(self.block(body)['date'],'2026-10-20')
    def test_post_info_and_post_date_formats(self):
        self.assertEqual(self.block('<p class="smalltext postInfoText"><span>24/01/2024</span></p>')['date'],'2024-01-24')
        self.assertEqual(self.block('<li class="post-date meta-wrapper"><span class="meta-text">September 23, 2026</span></li>')['date'],'2026-09-23')
    def test_invalid_conflicting_chrome_or_unlabelled_date_is_not_publication(self):
        for body in ['<p>26. september 2026</p>','<p class="postInfoText">31/02/2026</p>',
                     '<footer><p class="postInfoText">24/01/2024</p></footer>',
                     '<p class="postInfoText">24/01/2024</p><p class="postInfoText">25/01/2024</p>']:
            self.assertIsNone(self.block(body))
    def test_showing_comments_body_is_not_the_comments_section(self):
        html='<body class="single-post showing-comments"><article><header><h1>Update</h1></header><p>Example AS publishes a business update.</p></article></body>'
        self.assertEqual(Page(html,self.url).content_headings,['Update'])
    def test_semantic_article_header_inside_main_is_content_not_site_navigation(self):
        body='<header><h1>Global navigation</h1></header><main class="posts-entry"><div class="article"><header class="article__header"><h1>Example AS announces a new product line</h1></header><p>'+('Example AS has launched a new product line. '*4)+'</p></div></main><div class="publish-date--article">Published on August 12th, 2026</div>'
        p=Page(body,self.url);self.assertEqual(p.content_headings,['Example AS announces a new product line']);self.assertTrue(activity_candidates(p,{'url':self.url})[0])

class RecruitingPosts(unittest.TestCase):
    url='https://example.test/new-role'
    body='<body class="single-post"><main><h1>Vi søker en utvikler</h1><div class="entry-content"><p>Example Services utvikler systemer og søker nye kolleger.</p><p>Søknadsfrist: 08.11.2026</p><p>Send søknad og CV til <a href="mailto:jobs@example.test">jobs@example.test</a></p></div><span class="meta-date date published">20. oktober 2026</span></main></body>'
    def candidates(self,body=None,verified=True):
        return direct_recruiting_post(Page(body or self.body,self.url),{'url':self.url,'retrieved_at':'2026-10-31T12:00:00Z','identity_verified':verified},{'navn':'Example Services AS'})
    def test_named_direct_employer_deadline_and_publication_remain_distinct(self):
        job=self.candidates()[0];self.assertEqual(job['datePosted'],'2026-10-20');self.assertEqual(job['validThrough'],'2026-11-08')
    def test_customer_mention_foreign_mailbox_and_unverified_site_are_insufficient(self):
        self.assertFalse(self.candidates(self.body.replace('Example Services utvikler','Other Employer arbeider for Example Services og utvikler')))
        self.assertFalse(self.candidates(self.body.replace('jobs@example.test','jobs@other.test')))
        self.assertFalse(self.candidates(verified=False))
        self.assertFalse(self.candidates(self.body.replace('Example Services utvikler','Example Services SA utvikler')))
    def test_expired_spontaneous_and_undated_post_are_not_current_named_vacancies(self):
        self.assertFalse(self.candidates(self.body.replace('08.11.2026','01.10.2026')))
        self.assertFalse(self.candidates(self.body.replace('Send søknad og CV','Åpen søknad')))
        self.assertFalse(self.candidates(self.body.replace('meta-date date published','meta-date date updated')))

class DiscoveryAndWidgets(unittest.TestCase):
    def test_taxonomy_links_are_not_article_detail_pages(self):
        from agent import article_detail,activity_taxonomy
        self.assertTrue(activity_taxonomy('https://example.test/news/post-tags/service'))
        self.assertFalse(article_detail('https://example.test/news/post-tags/service'))
        self.assertTrue(article_detail('https://example.test/news/new-service'))

    def test_facebook_widget_needs_full_registered_domain_profile_and_no_other_entity(self):
        from social_ownership import asserted_profiles
        import json
        data={'navn':'Example Services AS','organisasjonsnummer':'810034882','hjemmeside':'https://differentbrand.test/'}
        url='https://differentbrand.test/';profile='https://facebook.com/differentbrand.test'
        html='<h2>Vår Facebookside!</h2><div class="fb-page" data-href="'+profile+'"></div>'
        def assertions(html):
            page=Page(html,url);return asserted_profiles([(page,{'url':url,'text':html})],data)[0]
        self.assertIn(profile,assertions(html))
        self.assertIn(profile,assertions('<body class="single-post showing-comments">'+html+'</body>'))
        self.assertFalse(assertions('<div id="comments">'+html+'</div>'))
        self.assertTrue(any(x['url']==profile for x in Page(html,url).links))
        self.assertFalse(assertions(html.replace('differentbrand.test"','unrelatedbrand"')))
        self.assertFalse(assertions('<div class="customer">'+html+'</div>'))
        person='<script type="application/ld+json">'+json.dumps({'@type':'Person','name':'Someone','sameAs':profile})+'</script>'
        self.assertFalse(assertions(html+person))

    def test_deep_editorial_links_are_found_but_catalog_and_taxonomy_are_not_posts(self):
        from agent import crawl_company
        from test_discovery import Pages,ORG
        f=Pages({'https://example.test/news':'<a href="/b/deep-story">A company update</a><a href="/products/pump">Pumps available</a><a href="/news/post-tags/service">Service</a>'})
        crawl_company(ORG,{}, {'url':'https://example.test/','text':'Org nr '+ORG+' <a href="/news">News</a>'},f)
        self.assertIn('https://example.test/b/deep-story',f.visited)
        self.assertNotIn('https://example.test/products/pump',f.visited)
