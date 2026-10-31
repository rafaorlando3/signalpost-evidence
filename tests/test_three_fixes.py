"""Adversarial regression cases for Soham's three attribution findings."""
import json
import unittest
from unittest.mock import patch
from agent import Page, Fetcher, activity_candidates
from attribution import canonical_profile, profile_identity, declared_profiles, article_attribution
from output_contract import complete_envelope, contract_errors
import test_agent


class Attribution(unittest.TestCase):
    def test_group_entry_with_subsidiary_footer_cannot_publish_group_facts(self):
        helper=test_agent.R5Precision()
        row=helper.observe({helper.HOME:
            '<title>North Parent Group</title><h1>North Parent Group</h1>'
            '<meta name="description" content="Our group employs 500 people across ten companies.">'
            '<footer>Subsidiary Example AS Org nr 810034882 '
            '<a href="https://facebook.com/parent">Follow</a></footer>'})
        for field in ('website.verified_url','website.social_links','website.hiring','website.activity'):
            c=helper.by_field(row,field)
            self.assertEqual(c['availability'],'ambiguous',field)
            self.assertIsNone(c['value'])
        self.assertEqual(helper.by_field(row,'employees')['value'],3)

    def test_exact_organization_sameAs_not_parent_sponsor_or_web_designer(self):
        helper=test_agent.R5Precision()
        payload=[{'@type':'Organization','taxID':helper.ORG,'sameAs':'https://facebook.com/target/'},
                 {'@type':'Organization','taxID':'974761076','sameAs':'https://facebook.com/parent'}]
        row=helper.observe({helper.HOME:'Org nr '+helper.ORG+
            '<script type="application/ld+json">'+json.dumps(payload[:1])+'</script>'
            '<section class="webdesign"><a href="https://facebook.com/agency">Agency</a></section>'})
        values=helper.by_field(row,'website.social_links')['value']
        self.assertEqual([x['url'] for x in values],['https://facebook.com/target'])
        self.assertEqual(values[0]['attribution'],'exact_entity_sameAs_declaration')
        # A separate parent sameAs is not attributed to the target node.
        page=Page('<script type="application/ld+json">'+json.dumps(payload)+'</script>',helper.HOME)
        self.assertEqual(set(declared_profiles([(page,{'url':helper.HOME})],{'organisasjonsnummer':helper.ORG})),
                         {'https://facebook.com/target'})

    def test_exact_named_site_schema_declares_own_profile_without_registry_contacts(self):
        helper=test_agent.R5Precision()
        metadata={'@type':'Organization','name':'Example AS','url':helper.HOME,
                  'sameAs':['https://instagram.com/example/']}
        row=helper.observe({helper.HOME:'Org nr '+helper.ORG+
            '<script type="application/ld+json">'+json.dumps(metadata)+'</script>'})
        claim=helper.by_field(row,'website.social_links')
        self.assertEqual(claim['value'][0]['url'],'https://instagram.com/example')
        self.assertEqual(claim['value'][0]['attribution'],'exact_entity_sameAs_declaration')

    def test_malformed_schema_url_does_not_abort_company(self):
        helper=test_agent.R5Precision()
        metadata={'@type':'Organization','name':'Example AS','url':'https://[bad',
                  'sameAs':'https://facebook.com/other'}
        row=helper.observe({helper.HOME:'Org nr '+helper.ORG+
            '<script type="application/ld+json">'+json.dumps(metadata)+'</script>'})
        self.assertEqual(row['run']['terminal_status'],'completed')
        self.assertIsNone(helper.by_field(row,'website.social_links')['value'])

    def test_unlabelled_agency_destination_is_withheld(self):
        helper=test_agent.R5Precision()
        row=helper.observe({helper.HOME:'Org nr '+helper.ORG+'<footer><a href="https://facebook.com/agency">Facebook</a></footer>',
            'https://facebook.com/agency':'<title>North Web Agency</title><a href="https://example.test/">A client</a>'})
        self.assertIsNone(helper.by_field(row,'website.social_links')['value'])

    def test_public_profile_requires_both_name_and_verified_site_backlink(self):
        data={'organisasjonsnummer':'810034882','navn':'Example AS'}
        good='<title>Example AS | Facebook</title><a href="https://example.test/">Website</a>'
        self.assertEqual(profile_identity(Page(good,'https://facebook.com/example'),data,'https://example.test/'),
                         'destination_name_and_verified_site_backlink')
        for bad in ('<title>Example AS</title>', '<title>Parent Group</title><a href="https://example.test/">Subsidiary</a>'):
            self.assertIsNone(profile_identity(Page(bad,'https://facebook.com/example'),data,'https://example.test/'))

    def test_social_posts_and_malformed_schemes_are_not_profiles(self):
        for url in ('https://linkedin.com/in/person','https://youtube.com/watch?v=123',
                    'https://facebook.com/acme/posts/1','https://instagram.com/p/one',
                    'javascript://facebook.com/acme','https://user:pass@facebook.com/acme'):
            self.assertIsNone(canonical_profile(url),url)

    def test_other_company_article_not_rescued_by_target_footer(self):
        helper=test_agent.R5Precision();url=helper.HOME+'news/partner'
        row=helper.observe({helper.HOME:'Org nr '+helper.ORG+'<a href="/news/partner">News</a>',url:
            '<title>Example AS | News</title><article><h1>Other Group opens a factory</h1><p>Other Group opened a factory today to supply equipment to its many customers in the local area.</p>'
            '<time itemprop="datePublished" datetime="2026-09-01">Published</time></article><footer>Example AS Org nr '+helper.ORG+'</footer>'})
        c=helper.by_field(row,'website.activity')
        self.assertIsNone(c['value']);self.assertEqual(c['availability'],'ambiguous')

    def test_real_own_announcement_can_omit_legal_name_with_exact_publisher(self):
        helper=test_agent.R5Precision();url=helper.HOME+'news/new-service'
        metadata={'@graph':[{'@type':'NewsArticle','headline':'New service','datePublished':'2026-09-01',
            'url':url,'publisher':{'@id':'#publisher'}},
            {'@type':'Organization','@id':'#publisher','name':'Example AS','url':helper.HOME}]}
        body='<article><h1>New service</h1><p>We now offer a new support service to customers. The service includes extended assistance and new online facilities.</p></article>'
        row=helper.observe({helper.HOME:'Org nr '+helper.ORG+'<a href="/news/new-service">News</a>',
            url:body+'<script type="application/ld+json">'+json.dumps(metadata)+'</script>'})
        value=helper.by_field(row,'website.activity')['value']
        self.assertEqual(value[0]['attribution'],'exact_entity_publisher_and_first_person_announcement')
        metadata['@graph'][1]['name']='Other AS'
        row=helper.observe({helper.HOME:'Org nr '+helper.ORG+'<a href="/news/new-service">News</a>',
            url:body+'<script type="application/ld+json">'+json.dumps(metadata)+'</script>'})
        self.assertIsNone(helper.by_field(row,'website.activity')['value'])

    def test_product_even_with_article_url_and_published_time_is_not_news(self):
        url='https://example.test/news/tool'
        body='<h1>Example AS tool</h1><p>'+('Useful product description. '*6)+'</p>'
        body+='<script type="application/ld+json">'+json.dumps([
            {'@type':'Product','name':'Tool'}, {'@type':'NewsArticle','url':url,'headline':'Tool','datePublished':'2026-09-01'}])+'</script>'
        candidates,reasons=activity_candidates(Page(body,url),{'url':url})
        self.assertEqual(candidates,[]);self.assertTrue(reasons)

    def test_only_modified_date_and_header_menu_are_not_posts(self):
        helper=test_agent.R5Precision();url=helper.HOME+'news/menu'
        row=helper.observe({helper.HOME:'Org nr '+helper.ORG+'<a href="/news/menu">Menu</a>',url:
            '<header><h1>Example AS news</h1><time itemprop="datePublished" datetime="2026-09-01">Date</time></header>'
            '<script type="application/ld+json">{"@type":"Article","headline":"Example AS","dateModified":"2026-09-01"}</script>'})
        self.assertIsNone(helper.by_field(row,'website.activity')['value'])

    def test_registry_email_and_telephone_are_never_promoted_to_contact_claims(self):
        helper=test_agent.R5Precision()
        row=helper.observe({helper.HOME:'Org nr '+helper.ORG},
                           {'epostadresse':'private-registry@example.test','telefon':'12345678'})
        claim=helper.by_field(row,'website.contact_channels')
        self.assertIsNone(claim['value'])
        self.assertNotIn('private-registry@example.test',json.dumps(row['claims']))

    def test_output_contract_alias_and_required_keys(self):
        row=test_agent.R5Precision().observe({test_agent.R5Precision.HOME:'Org nr '+test_agent.R5Precision.ORG})
        self.assertEqual(contract_errors(row),[])
        original=next(c for c in row['claims'] if c['field']=='website.verified_url')
        alias=next(c for c in row['claims'] if c['field']=='official_website')
        self.assertEqual(alias['value'],original['value'])
        self.assertEqual(alias['evidence_ids'],original['evidence_ids'])
        before=json.loads(json.dumps(row));complete_envelope(row)
        self.assertEqual(row,before)
        self.assertTrue(any(e['claim_span'] for e in row['evidence']))
