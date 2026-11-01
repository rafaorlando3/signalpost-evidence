import unittest
from agent import Page,activity_candidates


class EditorialIndex(unittest.TestCase):
    def test_wordpress_listing_cannot_borrow_child_post_marker_or_collection_date(self):
        url='https://example.test/blog/'
        for attrs in ['class="blog wp-theme-astra"','class="archive"','itemtype="https://schema.org/Blog"','itemtype="https://schema.org/CollectionPage"']:
            body='<body '+attrs+'><meta property="article:published_time" content="2026-03-04"><h1>Latest news at Example AS</h1><article class="type-post"><h2>Office parking</h2><p>'+('A post preview with details and a link to the full post. '*3)+'</p><a href="/office-parking/">Read post</a></article></body>'
            page=Page(body,url);self.assertTrue(page.post_container)
            candidates,reasons=activity_candidates(page,{'url':url})
            self.assertFalse(candidates);self.assertTrue(any('index or archive' in r for r in reasons))
            self.assertIn('https://example.test/office-parking/',{link['url'] for link in page.links})
            self.assertFalse(activity_candidates(Page(body,'https://example.test/'),{'url':'https://example.test/'})[0])

    def test_single_post_still_uses_own_content_date(self):
        url='https://example.test/office-parking/'
        # Several WordPress themes declare the global Blog vocabulary on each
        # genuine single-post body; that alone must not classify it as a list.
        body='<body class="single-post" itemtype="https://schema.org/Blog"><meta property="article:published_time" content="2026-03-04"><article class="type-post"><h1>New office at Example AS</h1><p>'+('Example AS now has new office facilities. '*4)+'</p></article></body>'
        candidates,_=activity_candidates(Page(body,url),{'url':url})
        self.assertEqual(candidates[0]['datePublished'],'2026-03-04')
