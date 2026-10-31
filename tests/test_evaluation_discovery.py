"""Regressions from independent public-reference diagnostics, no company allowlists."""
import unittest
from agent import Page,activity_candidates,link_family,article_detail
from test_agent import R5Precision

class IndependentDiagnostics(unittest.TestCase):
    def candidates(self,body,path='news-presse/factory'):
        url='https://example.test/'+path
        return activity_candidates(Page(body,url),{'url':url})

    def test_search_overlay_heading_does_not_hide_main_article(self):
        body='<main><article><h1>Example AS opens factory</h1><p>'+('Example AS announced a factory opening. '*4)+'</p><time class="published" datetime="2026-09-01">Published</time></article></main><div><h1>Search</h1><input></div>'
        c,_=self.candidates(body)
        self.assertEqual(len(c),1);self.assertEqual(c[0]['headline'],'Example AS opens factory')

    def test_two_real_main_headings_remain_ambiguous(self):
        body='<main><h1>One</h1><h1>Two</h1><p>'+('Example AS news. '*20)+'</p><time class="published" datetime="2026-09-01">Published</time></main>'
        c,_=self.candidates(body);self.assertEqual(c,[])

    def test_visible_published_date_beats_cms_migration_date(self):
        body='<meta property="article:published_time" content="2026-10-01"><main><h1>Example AS opens factory</h1><p>'+('Example AS announced a factory opening. '*4)+'</p><time itemprop="datePublished" datetime="2021-01-20">20 January 2021</time></main>'
        c,reasons=self.candidates(body)
        self.assertEqual([x['datePublished'] for x in c],['2021-01-20'])
        self.assertTrue(any('differs' in x for x in reasons))

    def test_modified_only_still_not_publication(self):
        body='<main><h1>Example AS opens factory</h1><p>'+('Example AS announced a factory opening. '*4)+'</p><time class="updated" datetime="2026-09-01">Updated</time></main>'
        c,_=self.candidates(body);self.assertEqual(c,[])

    def test_search_header_time_cannot_become_article_time(self):
        body='<main><h1>Example AS opens factory</h1><p>'+('Example AS announced a factory opening. '*4)+'</p></main><header><h1>Search</h1><time class="published" datetime="2026-09-01">Published</time></header>'
        c,_=self.candidates(body);self.assertEqual(c,[])

    def test_norwegian_orders_not_hiring(self):
        self.assertIsNone(link_family('https://example.test/bestillinger'))
        self.assertEqual(link_family('https://example.test/ledige-stillinger'),'hiring')
        self.assertEqual(link_family('https://example.test/about/careers'),'hiring')
        self.assertEqual(link_family('https://example.test/om-oss/nyheter-presse/one'),'activity')
        self.assertTrue(article_detail('https://example.test/nyheter-og-presse/one'))
        self.assertFalse(article_detail('https://example.test/newsletter/one'))

    def test_unnamed_employer_is_not_inferred_from_group_footer(self):
        import json
        h=R5Precision();u=h.HOME+'jobs/developer'
        row=h.observe({h.HOME:'Org nr '+h.ORG+'<a href="/jobs/developer">Careers</a>',u:'<h1>Developer</h1><script type="application/ld+json">'+json.dumps({'@type':'JobPosting','title':'Developer','datePosted':'2026-09-01'})+'</script>'})
        self.assertIsNone(h.by_field(row,'website.hiring')['value'])

if __name__=='__main__':unittest.main()

class ExtraEvidence(unittest.TestCase):
    def test_semantic_article_headline_survives_search_modal_inside_main(self):
        body='<main><h1 itemprop="headline">Example AS opens factory</h1><p>'+('Example AS announced a factory opening. '*4)+'</p><time itemprop="datePublished" datetime="2026-09-01">Published</time><div class="modal-body"><h1>Search</h1><form role="search"></form></div></main>'
        u='https://example.test/nyheter-presse/factory'
        c,_=activity_candidates(Page(body,u),{'url':u})
        self.assertEqual(len(c),1);self.assertEqual(c[0]['headline'],'Example AS opens factory')

    def test_short_brand_requires_full_legal_name_and_registered_postal_address(self):
        from agent import corroborated_site
        data={'navn':'ABC AS','hjemmeside':'https://example.test','forretningsadresse':{'adresse':['Road 12'],'postnummer':'1234'}}
        self.assertTrue(corroborated_site(data,Page('ABC AS, Road 12, 1234 Oslo','https://example.test')))
        self.assertFalse(corroborated_site(data,Page('ABC, Road 12, 1234 Oslo','https://example.test')))
        self.assertFalse(corroborated_site(data,Page('ABC AS, Road 12, 1234 Oslo','https://other.test')))

    def test_gzip_decode_is_bounded_and_wire_hash_preserved(self):
        import gzip,hashlib,tempfile
        from unittest.mock import MagicMock,patch
        from urllib.parse import urlsplit
        from agent import Fetcher
        payload=gzip.compress(b'<h1>Example AS</h1>')
        response=MagicMock();response.status=200;response.read.return_value=payload
        response.getheader.side_effect=lambda k:'gzip' if k=='Content-Encoding' else None
        response.headers.get_content_charset.return_value='utf-8'
        conn=MagicMock();conn.getresponse.return_value=response
        with tempfile.TemporaryDirectory() as d,patch('agent.safe_url',return_value=(urlsplit('https://example.test'),'example.test',443,'8.8.8.8')),patch('agent.http.client.HTTPSConnection',return_value=conn):
            r=Fetcher(d).get('https://example.test',raw=True)
        self.assertEqual(r['text'],'<h1>Example AS</h1>');self.assertEqual(r['content_sha256'],hashlib.sha256(payload).hexdigest())
        response.read.return_value=gzip.compress(b'x'*2_000_100)
        with tempfile.TemporaryDirectory() as d,patch('agent.safe_url',return_value=(urlsplit('https://example.test'),'example.test',443,'8.8.8.8')),patch('agent.http.client.HTTPSConnection',return_value=conn):
            r=Fetcher(d).get('https://example.test',raw=True)
        self.assertEqual(r['status'],'blocked');self.assertNotIn('text',r)

    def test_external_career_delegation_does_not_publish_wrong_employer(self):
        import json
        from test_agent import R5Precision as Helper
        h=Helper();home='Org nr '+h.ORG+'<a href="https://careers.test/">Careers</a>'
        posting={'@type':'JobPosting','title':'Engineer','datePosted':'2026-09-01','hiringOrganization':{'name':'Other Company AS'}}
        page='<h1>Engineer</h1><script type="application/ld+json">'+json.dumps(posting)+'</script>'
        r=h.observe({h.HOME:home,'https://careers.test/':page})
        self.assertIsNone(h.by_field(r,'website.hiring')['value'])
        posting['hiringOrganization']['name']='Example AS'
        page='<h1>Engineer</h1><script type="application/ld+json">'+json.dumps(posting)+'</script>'
        r=h.observe({h.HOME:home,'https://careers.test/':page})
        self.assertEqual(h.by_field(r,'website.hiring')['value'][0]['hiring_organisation'],'Example AS')
        # Delegated ATS content must not become company description or news.
        self.assertIsNone(h.by_field(r,'website.activity')['value'])

class LegalFooterIdentity(unittest.TestCase):
    def test_email_domain_requires_full_legal_footer_address_and_matching_brand(self):
        from agent import corroborated_site
        d={'navn':'Example Business AS','epostadresse':'office@example.test','forretningsadresse':{'adresse':['Road 12'],'postnummer':'1234'}}
        good='<title>Example Business - home</title><footer>Example Business AS Road 12, 1234 Oslo</footer>'
        self.assertTrue(corroborated_site(d,Page(good,'https://example.test/')))
        self.assertFalse(corroborated_site(d,Page(good.replace('<footer>','<div>').replace('</footer>','</div>'),'https://example.test/')))
        self.assertFalse(corroborated_site(d,Page(good.replace('Example Business - home','Parent Group'),'https://example.test/')))
        # A full legal imprint with exact registered address is independent
        # ownership evidence even when the URL began as an untrusted lead.
        self.assertTrue(corroborated_site(d,Page(good,'https://other.test/')))
        self.assertFalse(corroborated_site(d,Page(good.replace('1234','9999'),'https://example.test/')))
        self.assertFalse(corroborated_site({**d,'epostadresse':'a@gmail.com'},Page(good,'https://gmail.com/')))

class SocialControlTokens(unittest.TestCase):
    def test_youtube_legacy_user_handle_still_needs_own_social_declaration(self):
        from social_ownership import asserted_profiles
        data={'navn':'Example Business AS','organisasjonsnummer':'810034882'}
        def observe(body):
            u='https://example.test';return asserted_profiles([(Page(body,u),{'url':u,'text':body})],data)[0]
        good='<footer><div class="footer__socialIcons"><a href="https://youtube.com/user/ExampleBusiness">YouTube</a></div></footer>'
        self.assertIn('https://youtube.com/user/ExampleBusiness',observe(good))
        self.assertNotIn('https://youtube.com/user/ExampleBusiness',observe(good.replace('footer__socialIcons','plain')))
        self.assertFalse(observe(good.replace('ExampleBusiness','OtherGroup')))
        self.assertFalse(observe(good.replace('footer__socialIcons','sponsor__socialIcons')))

class UsefulDescription(unittest.TestCase):
    def test_menu_footer_and_placeholder_are_not_company_descriptions(self):
        from test_agent import R5Precision as Helper
        h=Helper();body='<title>Example AS</title><nav><p>'+('Menu '*25)+'</p></nav><footer>Org nr '+h.ORG+'</footer>'
        r=h.observe({h.HOME:body});self.assertIsNone(h.by_field(r,'website.description')['value'])
        body+='<main><p>Example AS develops reliable tools that help engineering teams monitor and improve their daily operations.</p></main>'
        r=h.observe({h.HOME:body});self.assertTrue(h.by_field(r,'website.description')['value'].startswith('Example AS develops'))
        r=h.observe({h.HOME:body+'<meta name="description" content="Lorem ipsum dolor sit amet, consectetur adipiscing elit.">'})
        self.assertIsNone(h.by_field(r,'website.description')['value'])

class MalformedContactURLs(unittest.TestCase):
    def test_malformed_phone_port_cannot_abort_career_discovery(self):
        from hiring_discovery import delegated_hiring_pages
        from unittest.mock import Mock
        page=Page('<a href="https://example.test:+4735069000/">Careers</a>','https://example.test/')
        f=Mock();f.requests=0;f.limit=20
        self.assertEqual(delegated_hiring_pages([(page,{'url':page.url})],f,Page),[])
        f.get.assert_not_called()

class RootSlugNews(unittest.TestCase):
    def test_root_wordpress_post_requires_real_post_container_not_static_page(self):
        import json
        u='https://example.test/new-factory'
        metadata={'@type':'Article','url':u,'headline':'Example AS opens factory','datePublished':'2026-09-01'}
        body='<article class="singlePostSection" data-template="single"><h1>Example AS opens factory</h1><p>'+('Example AS has opened its new factory. '*4)+'</p></article><script type="application/ld+json">'+json.dumps(metadata)+'</script>'
        cs,_=activity_candidates(Page(body,u),{'url':u});self.assertTrue(cs)
        cs,_=activity_candidates(Page(body.replace('singlePostSection','page type-page'),u),{'url':u});self.assertFalse(cs)

    def test_sitemap_prioritizes_recent_leads_without_publishing_lastmod(self):
        from site_discovery import xml_candidates
        xml='<urlset xmlns:image="https://example.test/image"><url><loc>https://example.test/old</loc><lastmod>2020-01-01</lastmod><image:loc>https://example.test/image.jpg</image:loc></url><url><loc>https://example.test/new</loc><lastmod>2026-09-01</lastmod></url></urlset>'
        pages,_=xml_candidates(xml,'https://example.test/sitemap.xml','example.test')
        self.assertEqual(pages,['https://example.test/new','https://example.test/old'])

class NetworkAndImprint(unittest.TestCase):
    def test_public_dual_stack_prefers_reachable_ipv4_without_weakening_private_ip_gate(self):
        from agent import safe_url
        from unittest.mock import patch
        with patch('socket.getaddrinfo',return_value=[(10,1,6,'',('2001:4860:4860::8888',443)),(2,1,6,'',('8.8.8.8',443))]):
            self.assertEqual(safe_url('https://example.test')[3],'8.8.8.8')
        with patch('socket.getaddrinfo',return_value=[(10,1,6,'',('2001:4860:4860::8888',443)),(2,1,6,'',('127.0.0.1',443))]):
            with self.assertRaises(ValueError):safe_url('https://example.test')

    def test_neutral_homepage_needs_adjacent_exact_legal_imprint(self):
        from agent import legal_footer_identity
        d={'navn':'Example Business AS','organisasjonsnummer':'810034882','forretningsadresse':{'adresse':['Road 12'],'postnummer':'1234'}}
        html='<title>Hjem</title><p>New website under construction</p><p>Example Business AS</p><p>Road 12</p><p>1234 Oslo</p>'
        self.assertTrue(legal_footer_identity(d,Page(html,'https://example.test/')))
        self.assertFalse(legal_footer_identity(d,Page(html.replace('Hjem','Different Parent Group'),'https://example.test/')))
        self.assertFalse(legal_footer_identity(d,Page(html.replace('Example Business AS','Our client Example Business AS'),'https://example.test/')))
        self.assertFalse(legal_footer_identity(d,Page(html,'https://example.test/customers/one')))

class NorwegianSocialControl(unittest.TestCase):
    def test_some_means_social_media_only_in_component_context(self):
        from social_ownership import asserted_profiles
        data={'navn':'Example Business AS'};u='https://example.test/'
        html='<footer><div class="SoMe"><a href="https://linkedin.com/company/example-business-as">LinkedIn</a></div></footer>'
        found,_=asserted_profiles([(Page(html,u),{'url':u,'text':html})],data)
        self.assertIn('https://linkedin.com/company/example-business-as',found)
        html=html.replace('class="SoMe"','')+'<p>Example Business AS offers some services.</p>'
        found,_=asserted_profiles([(Page(html,u),{'url':u,'text':html})],data)
        self.assertFalse(found)

class OperatorAudit(unittest.TestCase):
    def test_structured_operator_proof_is_audited_as_roles_not_text_offsets(self):
        import tempfile,json,hashlib
        from agent import Fetcher,claim,site_operator_identity
        from audit import audit
        org='810034882';u='https://example.test/'
        metadata={'@type':'WebSite','url':u,'publisher':{'@type':'Organization','taxID':org}}
        text='<script type="application/ld+json">'+json.dumps(metadata)+'</script>'
        with tempfile.TemporaryDirectory() as d:
            rsp={'url':u,'requested_url':u,'status':'available','status_code':200,'text':text,'retrieved_at':'2026-10-31T00:00:00Z','content_sha256':hashlib.sha256(text.encode()).hexdigest()}
            Fetcher(d,replay=True).retain(rsp);e={};c=claim('website.verified_url',u,rsp,e,pointer='explicit_site_operator')
            c['identity_support']=site_operator_identity(org,Page(text,u),{'organisasjonsnummer':org})
            row={'organisation_number':org,'claims':[c],'evidence':list(e.values())}
            self.assertTrue(audit([row],d)['passed'])
            c['identity_support']['operators'][0]['organisation_numbers']=['974761076']
            self.assertFalse(audit([row],d)['passed'])

class ArticleHeaderScope(unittest.TestCase):
    def test_post_header_has_its_own_publication_title_and_date(self):
        u='https://example.test/new-factory'
        body='<header><h1>Global brand</h1><time itemprop="datePublished" datetime="2026-01-01">Menu date</time></header><main><article class="singlePostSection"><header><h1>Example AS opens factory</h1><time itemprop="datePublished" datetime="2026-09-01">Published</time></header><p>'+('Example AS has opened its new factory. '*4)+'</p></article></main>'
        p=Page(body,u);cs,_=activity_candidates(p,{'url':u})
        self.assertEqual(p.content_headings,['Example AS opens factory'])
        self.assertEqual(p.content_times,['2026-09-01'])
        self.assertEqual([c['datePublished'] for c in cs],['2026-09-01'])
        # A global header cannot become content just by containing an article.
        p=Page('<header><article><h1>Menu headline</h1><time itemprop="datePublished" datetime="2026-09-01">Date</time></article></header>',u)
        cs,_=activity_candidates(p,{'url':u});self.assertEqual(cs,[])

class PlaceholderDescription(unittest.TestCase):
    def test_under_construction_notice_is_not_an_operational_description(self):
        from test_agent import R5Precision as Helper
        h=Helper();body='<footer>Org nr '+h.ORG+'</footer><meta name="description" content="Our new website is under construction. Follow us for future updates and more information.">'
        r=h.observe({h.HOME:body})
        self.assertEqual(h.by_field(r,'website.verified_url')['availability'],'available')
        self.assertIsNone(h.by_field(r,'website.description')['value'])
