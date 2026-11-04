import json,unittest
from agent import Page,activity_candidates
from publication import publication_block

class EditorialQuality(unittest.TestCase):
    url='https://example.test/news/new-project'
    def page(self,date='1.10.2026',extra=''):
        ld={'@type':'NewsArticle','headline':'A company project','url':self.url,'datePublished':'2026-10-19T10:00:00Z'}
        return Page('<script type="application/ld+json">'+json.dumps(ld)+'</script><main><div class="tag-date-container"><div>'+date+'</div></div><div class="tag-date-container">Projects &amp; innovation</div><h1>A company project</h1><p>'+('Example Company is developing new technologies for its own project. '*4)+'</p></main>'+extra,self.url)
    def test_article_header_numeric_date_wins_over_import_metadata(self):
        p=self.page();self.assertEqual(publication_block(p)['date'],'2026-10-01')
        articles,_=activity_candidates(p,{'url':self.url});self.assertTrue(articles);self.assertTrue(all(a['datePublished']=='2026-10-01' for a in articles))
    def test_sidebar_and_event_dates_do_not_supply_publication(self):
        for body in ['<aside><div class="tag-date-container">1.10.2026</div></aside>','<main><p>Event date: 1.10.2026</p></main>','<main><div class="tag-date-container">31.2.2026</div></main>']:
            self.assertIsNone(publication_block(Page(body,self.url)))
    def test_conflicting_header_dates_are_not_selected(self):
        p=self.page();p=Page(p.raw_html.replace('<h1>', '<div class="tag-date-container">2.10.2026</div><h1>'),self.url)
        self.assertIsNone(publication_block(p))
    def test_reference_gallery_wordcount_two_does_not_borrow_contact_boilerplate(self):
        ld={'@type':'Article','headline':'Steel frame','datePublished':'2026-10-01','wordCount':2,'url':self.url,'articleSection':['References']}
        html='<body class="single-post"><h1>Steel frame</h1><img src="frame.jpg"><section><h2>Contact</h2><p>Interested in working with us? Contact our team for more information about our services and a free consultation.</p></section><script type="application/ld+json">'+json.dumps(ld)+'</script></body>'
        articles,limits=activity_candidates(Page(html,self.url),{'url':self.url});self.assertFalse(articles);self.assertTrue(any('gallery' in x for x in limits))
    def test_short_actual_project_narrative_is_preserved(self):
        ld={'@type':'Article','headline':'Completed new staircase','datePublished':'2026-10-01','wordCount':17,'url':self.url}
        body='<body class="single-post"><h1>Completed new staircase</h1><p>We completed a staircase for a local customer. The installed staircase is now open to visitors at the shopping centre.</p><script type="application/ld+json">'+json.dumps(ld)+'</script></body>'
        self.assertTrue(activity_candidates(Page(body,self.url),{'url':self.url})[0])
    def test_declared_wordcount_equal_to_long_title_has_no_narrative(self):
        title='Lifting certified frames made from steel'
        ld={'@type':'Article','headline':title,'datePublished':'2026-10-01','wordCount':6,'url':self.url}
        body='<body class="single-post"><h1>'+title+'</h1><img src="frame.jpg"><p>Interested in working together? Contact our team for information about our services.</p><script type="application/ld+json">'+json.dumps(ld)+'</script></body>'
        self.assertFalse(activity_candidates(Page(body,self.url),{'url':self.url})[0])
if __name__=='__main__':unittest.main()
