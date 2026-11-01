import json
import unittest
from agent import Page,activity_candidates


class CMSArticleViews(unittest.TestCase):
    @staticmethod
    def helper():
        from test_agent import R5Precision
        return R5Precision()

    url='https://example.test/company-update'
    article={'@type':'Article','url':url,'headline':'Example AS expands its workshop','datePublished':'2026-09-01'}

    def body(self,classes='single single-post postid-12',metadata=None,extra=''):
        return ('<body class="'+classes+'"><main><h1>Example AS expands its workshop</h1><p>'+('Example AS has expanded its workshop to serve its customers. '*4)+'</p>'+extra+
                '</main><script type="application/ld+json">'+json.dumps(self.article if metadata is None else metadata)+'</script></body>')

    def candidates(self,body,url=None):
        u=url or self.url
        return activity_candidates(Page(body,u),{'url':u})

    def test_wordpress_individual_view_accepts_root_slug_with_real_article(self):
        values,_=self.candidates(self.body())
        self.assertEqual(values[0]['datePublished'],'2026-09-01')
        self.assertEqual(values[0]['headline'],self.article['headline'])

    def test_squarespace_individual_blog_view_has_same_requirements(self):
        self.assertTrue(self.candidates(self.body(classes='view-item collection-type-blog'))[0])
        self.assertFalse(self.candidates(self.body(classes='view-list collection-type-blog'))[0])

    def test_static_page_blog_index_and_homepage_are_not_detail_views(self):
        for classes in ['page type-page','blog archive','single-product','single single-page']:
            self.assertFalse(self.candidates(self.body(classes=classes))[0])
        metadata={**self.article,'url':'https://example.test/'}
        self.assertFalse(self.candidates(self.body(metadata=metadata),'https://example.test/')[0])

    def test_product_and_collection_metadata_still_veto_editorial_claim(self):
        for kind in ['Product','Offer','CollectionPage','ItemList']:
            body=self.body(metadata=[self.article,{'@type':kind,'name':'Catalog'}])
            self.assertFalse(self.candidates(body)[0])

    def test_article_for_a_different_url_is_not_promoted(self):
        self.assertFalse(self.candidates(self.body(metadata={**self.article,'url':'https://example.test/elsewhere'}))[0])

    def test_visible_published_date_overrides_structured_migration_date(self):
        body=self.body(metadata={**self.article,'datePublished':'2026-09-10'},extra='<time itemprop="datePublished" datetime="2026-09-01">Published 1 September</time>')
        values,reasons=self.candidates(body)
        self.assertEqual({x['datePublished'] for x in values},{'2026-09-01'})
        self.assertTrue(any('structured article' in x for x in reasons))

    def test_foreign_company_post_does_not_inherit_legal_footer(self):
        h=self.helper();body=self.body().replace('Example AS expands its workshop','Other Company AS expands its workshop').replace('Example AS has expanded','Other Company AS has expanded')
        row=h.observe({h.HOME:'Org nr '+h.ORG+'<a href="/company-update">News</a>',self.url:body+'<footer>Org nr '+h.ORG+'</footer>'})
        self.assertIsNone(h.by_field(row,'website.activity')['value'])

    def test_modified_only_schema_does_not_gain_publication_date(self):
        h=self.helper();metadata={**self.article};metadata.pop('datePublished');metadata['dateModified']='2026-09-01'
        row=h.observe({h.HOME:'Org nr '+h.ORG+'<a href="/company-update">News</a>',self.url:self.body(metadata=metadata)})
        self.assertIsNone(h.by_field(row,'website.activity')['value'])

    def test_catalog_paths_are_not_news_even_when_theme_calls_them_posts(self):
        for path in ['produkter/forskaling/beam','products/new-pump','services/consulting','shop/tool']:
            u='https://example.test/'+path
            self.assertFalse(self.candidates(self.body(metadata={**self.article,'url':u}),u)[0])

    def test_placeholder_titles_are_not_company_activity(self):
        for title in ['TestPostMobil','Test post']:
            body=self.body(metadata={**self.article,'headline':title}).replace('Example AS expands its workshop',title)
            self.assertFalse(self.candidates(body)[0])

    def test_seo_brand_suffix_is_not_proof_that_other_post_concerns_the_company(self):
        h=self.helper();metadata={**self.article,'headline':'Other Company expands its workshop - Example AS'}
        body=self.body(metadata=metadata).replace('Example AS expands its workshop</h1>','Other Company expands its workshop</h1>').replace('Example AS has expanded','Other Company has expanded')
        body='<meta property="og:title" content="Other Company expands its workshop - Example AS">'+body
        row=h.observe({h.HOME:'Org nr '+h.ORG+'<a href="/company-update">News</a>',self.url:body})
        self.assertIsNone(h.by_field(row,'website.activity')['value'])

    def test_wordpress_entry_content_after_main_header_is_retained_as_post_body(self):
        body='<body class="single-post"><main><h1>New workshop</h1></main><div class="entry-content"><p>Example AS has expanded its workshop to serve its customers and hired new staff.</p></div><footer>Other Company AS</footer></body>'
        page=Page(body,self.url)
        self.assertIn('Example AS has expanded',' '.join(page.article_parts))
        self.assertNotIn('Other Company AS',' '.join(page.article_parts))

    def test_comment_heading_and_published_date_are_not_post_content(self):
        body=self.body(extra='<div id="comments"><article class="comment"><h1>Another company launches a factory</h1><time class="published" datetime="2026-09-15">Comment date</time><p>Other company launched a factory.</p></article></div>')
        page=Page(body,self.url)
        self.assertNotIn('Another company launches a factory',page.content_headings)
        self.assertNotIn('2026-09-15',page.content_times)
        self.assertNotIn('Other company launched',' '.join(page.article_parts))

    def test_cooperative_legal_suffix_does_not_hide_real_subject_or_accept_other_entity(self):
        from attribution import article_attribution
        data={'navn':'Example Workshop SA','organisasjonsnummer':'810034882'}
        page=Page('<body class="single-post"><main><h1>New apprentice</h1><p>Example Workshop welcomes a new apprentice to its team.</p></main></body>',self.url)
        obj={'headline':'New apprentice'}
        self.assertEqual(article_attribution(obj,page,data),'target_name_in_post_content')
        page=Page('<main><p>Example Workshop AS welcomes a new apprentice.</p></main>',self.url)
        self.assertIsNone(article_attribution(obj,page,data))

    def test_exact_publisher_supports_first_person_operational_announcement(self):
        from attribution import article_attribution
        publisher={'@type':'Organization','name':'Example AS','url':'https://example.test/'}
        for text in ['Våre åpningstider i påsken finner du her.','Vi har iverksatt nødvendige sikkerhetstiltak.','Her hjalp vi kunden med adkomst til byggeplassen.']:
            page=Page('<main><h1>Update</h1><p>'+text+'</p></main>',self.url)
            obj={'headline':'Update','publisher':publisher}
            self.assertEqual(article_attribution(obj,page,{'navn':'Example AS'}),'exact_entity_publisher_and_first_person_announcement')
            self.assertIsNone(article_attribution({**obj,'publisher':{**publisher,'name':'Other Group AS'}},page,{'navn':'Example AS'}))

    def test_default_hello_world_requires_template_body_not_just_a_real_launch_title(self):
        for title in ['Hello world!','Hei, verden!','Lorem ipsum']:
            metadata={**self.article,'headline':title}
            body=self.body(metadata=metadata).replace('Example AS expands its workshop',title)
            self.assertTrue(self.candidates(body)[0])
            body=body.replace('Example AS has expanded its workshop to serve its customers. '*4,'Welcome to WordPress. This is your first post. Edit or delete it and start writing.')
            self.assertFalse(self.candidates(body)[0])

    def test_current_page_publisher_chain_preserves_real_first_person_release(self):
        from attribution import page_publisher,article_attribution
        graph=[{'@type':'WebPage','url':self.url,'isPartOf':{'@id':'https://example.test/#website'}},
            {'@type':'WebSite','@id':'https://example.test/#website','url':'https://example.test/','publisher':{'@id':'https://example.test/#org'}},
            {'@type':'Organization','@id':'https://example.test/#org','name':'Example AS','url':'https://example.test/'}]
        page=Page('<main><h1>Safety update</h1><p>Vi har iverksatt nødvendige sikkerhetstiltak.</p></main><script type="application/ld+json">'+json.dumps(graph)+'</script>',self.url)
        publisher=page_publisher(page);self.assertEqual(publisher['name'],'Example AS')
        self.assertEqual(article_attribution({'headline':'Safety update','publisher':publisher},page,{'navn':'Example AS'}),'exact_entity_publisher_and_first_person_announcement')
        graph[0]['url']='https://example.test/other'
        self.assertIsNone(page_publisher(Page('<script type="application/ld+json">'+json.dumps(graph)+'</script>',self.url)))
        graph[0]['url']=self.url;graph[0].pop('isPartOf')
        self.assertIsNone(page_publisher(Page('<script type="application/ld+json">'+json.dumps(graph)+'</script>',self.url)))

    def test_other_legal_entity_quotation_is_not_publisher_announcement(self):
        from attribution import article_attribution
        page=Page('<main><h1>Other Company AS opens factory</h1><p>We have opened our new factory, says its director.</p></main>',self.url)
        obj={'headline':'Other Company AS opens factory','publisher':{'@type':'Organization','name':'Example AS','url':'https://example.test/'}}
        self.assertIsNone(article_attribution(obj,page,{'navn':'Example AS'}))
