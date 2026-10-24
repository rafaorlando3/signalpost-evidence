import copy
import json
import tempfile
import unittest
from unittest.mock import patch
from agent import Page, website_identity, corroborated_site, valid_org, compare, claim, redact, safe_url, Fetcher, research, typed_json

class Core(unittest.TestCase):
    def test_checksum(self):
        self.assertTrue(valid_org('810034882'))
        self.assertFalse(valid_org('810034883'))
        self.assertFalse(valid_org('123'))

    def test_identity_exact(self):
        self.assertEqual(website_identity('810034882',Page('<footer>Org.nr: 810 034 882</footer>','https://example.test')),'exact')

    def test_identity_rejects_joined_fragments(self):
        self.assertEqual(website_identity('810034882',Page('Products 810. Orders 034. Clients 882.','https://example.test')),'ambiguous')

    def test_identity_conflict(self):
        self.assertEqual(website_identity('810034882',Page('Org nr: 810034882; Org nr: 987654321','https://example.test')),'conflict')

    def test_identity_long_number(self):
        self.assertEqual(website_identity('810034882',Page('Org nr: 8100348821','https://example.test')),'ambiguous')

    def test_structured_tax_id(self):
        page=Page('<script type="application/ld+json">{"@type":"Organization","vatID":"NO810034882MVA"}</script>','https://example.test')
        self.assertEqual(website_identity('810034882',page),'exact')

    def test_structured_type_array(self):
        page=Page('<script type="application/ld+json">{"@type":["LocalBusiness","Organization"],"vatID":"NO810034882MVA"}</script>','https://example.test')
        self.assertEqual(website_identity('810034882',page),'exact')

    def test_hidden_script_not_identity(self):
        page=Page('<script>Org nr: 810034882</script><p>Unknown</p>','https://example.test')
        self.assertEqual(website_identity('810034882',page),'ambiguous')

    def test_identity_label_variants(self):
        for text in ('Organisasjonsnr.: NO 810 034 882 MVA','Org. nummer: 810034882'):
            self.assertEqual(website_identity('810034882',Page(text,'https://example.test')),'exact')

    def test_corroboration_requires_registered_domain_name_and_address(self):
        data={'navn':'Example Company AS','hjemmeside':'www.example.test','forretningsadresse':{'adresse':['Main gate 12'],'postnummer':'1234'}}
        self.assertTrue(corroborated_site(data,Page('Example Company, Main gate 12, 1234 Oslo','https://example.test')))
        self.assertFalse(corroborated_site(data,Page('Example Company, Main gate 12, 1234 Oslo','https://other.test')))
        self.assertFalse(corroborated_site(data,Page('Example Company','https://example.test')))
        self.assertFalse(corroborated_site({**data,'hjemmeside':None},Page('Example Company, Main gate 12, 1234 Oslo','https://example.test')))

    def test_schema_mismatch_is_failed(self):
        self.assertEqual(typed_json({'status':'available','json':[]},dict,'navn')['status'],'failed')
        self.assertEqual(typed_json({'status':'available','json':{}},dict,'navn')['status'],'failed')

    def observation(self,value,state='available',field='roles'):
        return {'claims':[{'field':field,'value':value,'availability':state,'evidence_ids':['e']}]}

    def test_reorder_no_change(self):
        self.assertEqual(compare(self.observation([{'n':'A'},{'n':'B'}]),self.observation([{'n':'B'},{'n':'A'}])),[])

    def test_real_removal(self):
        self.assertEqual(len(compare(self.observation(['A']),self.observation([]))),1)

    def test_failure_not_removal(self):
        self.assertEqual(compare(self.observation(['A']),self.observation(None,'failed')),[])

    def test_zero_change(self):
        self.assertEqual(len(compare(self.observation(5,field='employees'),self.observation(0,field='employees'))),1)

    def test_duplicate_change_preserved(self):
        self.assertEqual(len(compare(self.observation(['A']),self.observation(['A','A']))),1)

    def test_reporting_period_change_is_preserved(self):
        a=self.observation(10,field='financials.revenue');b=copy.deepcopy(a)
        a['claims'][0]['reporting_period']={'year':2024};b['claims'][0]['reporting_period']={'year':2025}
        self.assertEqual(len(compare(a,b)),1)

    def test_source_dates(self):
        evidence={}; rsp={'status':'available','url':'https://example.test','retrieved_at':'2026-09-01','content_sha256':'abc'}
        result=claim('employees',0,rsp,evidence)
        self.assertEqual(result['value'],0)
        self.assertEqual(next(iter(evidence.values()))['retrieved_at'],'2026-09-01')
        self.assertEqual(claim('x',None,rsp,evidence)['availability'],'not_available')

    def test_redaction(self):
        self.assertEqual(redact({'person':{'navn':'A','fodselsdato':'1990-01-01'}}),{'person':{'navn':'A'}})

    def test_private_addresses_blocked(self):
        for address in ('127.0.0.1','10.0.0.1','169.254.169.254','::1'):
            with patch('socket.getaddrinfo',return_value=[(2,1,6,'',(address,443))]):
                with self.assertRaises(ValueError): safe_url('https://example.test')

    def test_url_credentials_and_schemes(self):
        for url in ('file:///etc/passwd','https://user:pass@example.test','https://example.test:1234'):
            with self.assertRaises(ValueError): safe_url(url)

    def test_missing_replay_is_no_network(self):
        with tempfile.TemporaryDirectory() as d, patch('socket.getaddrinfo',side_effect=AssertionError('network')):
            f=Fetcher(d,replay=True)
            self.assertEqual(f.get('https://example.test')['status'],'failed')
            self.assertEqual(f.requests,0)

    def test_full_pipeline_failure_keeps_unknowns(self):
        with tempfile.TemporaryDirectory() as d:
            f=Fetcher(d,replay=True)
            result=research({'organisation_number':'810034882'},f)
            self.assertTrue(all(c['value'] is None for c in result['claims']))
            self.assertFalse(result['changes'])
            self.assertEqual(result['operations']['requests'],0)

if __name__=='__main__': unittest.main()


class R5Precision(unittest.TestCase):
    ORG='810034882'
    HOME='https://example.test/'

    def observe(self, pages):
        import hashlib
        with tempfile.TemporaryDirectory() as directory:
            fetcher=Fetcher(directory, replay=True)
            base='https://data.brreg.no/enhetsregisteret/api/enheter/'+self.ORG
            def get(url, **kwargs):
                response={'url':url,'requested_url':url,'status':'available',
                          'status_code':200,'retrieved_at':'2026-09-26T00:00:00+00:00'}
                if url==base:
                    response['json']={'organisasjonsnummer':self.ORG,'navn':'Example AS',
                                      'hjemmeside':self.HOME,'antallAnsatte':3}
                elif url==base+'/roller':response['json']={'rollegrupper':[]}
                elif '/regnskapsregisteret/' in url:response['json']=[]
                elif '/underenheter?' in url:response['json']={'page':{'totalPages':0}}
                elif url not in pages:
                    response.update(status='not_available',status_code=404)
                response['text']=pages.get(url,json.dumps(response.get('json',{})))
                response['content_sha256']=hashlib.sha256(response['text'].encode()).hexdigest()
                return response
            with patch.object(fetcher,'get',side_effect=get):
                return research({'organisation_number':self.ORG},fetcher)

    def by_field(self, row, field):
        return next(claim for claim in row['claims'] if claim['field']==field)

    def test_group_description_is_ambiguous_without_erasing_supported_families(self):
        row=self.observe({self.HOME:
            '<meta name="description" content="The group employs 900 people across 20 companies.">'
            '<footer>Org nr 810034882 <a href="mailto:office@example.test">Email</a></footer>'})
        description=self.by_field(row,'website.description')
        self.assertEqual(description['availability'],'ambiguous')
        self.assertIsNone(description['value'])
        self.assertEqual(description['qualifiers']['subject_scope'],'group')
        self.assertIn('900',description['evidence_excerpt'])
        self.assertEqual(self.by_field(row,'website.verified_url')['availability'],'available')
        self.assertEqual(self.by_field(row,'website.contact_channels')['availability'],'available')
        self.assertEqual(self.by_field(row,'employees')['value'],3)

    def test_own_description_is_not_removed_by_unrelated_group_link(self):
        row=self.observe({self.HOME:
            '<meta name="description" content="Example AS builds useful tools.">'
            '<a href="/about-parent-group">Our group</a><footer>Org nr 810034882</footer>'})
        self.assertEqual(self.by_field(row,'website.description')['value'],'Example AS builds useful tools.')

    def test_footer_profile_link_is_declared_not_owned_and_share_action_is_excluded(self):
        row=self.observe({self.HOME:
            '<footer>Org nr 810034882'
            '<a href="https://facebook.com/example">Follow us</a>'
            '<a href="https://facebook.com/foreign">Share on Facebook</a>'
            '<section class="partners"><a href="https://linkedin.com/company/partner">Partner</a></section>'
            '</footer>'})
        social=self.by_field(row,'website.social_links')
        self.assertEqual([item['url'] for item in social['value']],['https://facebook.com/example'])
        self.assertEqual(social['qualifiers']['profile_ownership'],'not_independently_verified')
        self.assertEqual(self.by_field(row,'website.verified_url')['availability'],'available')

    def test_menu_product_updated_candidates_do_not_remove_real_news(self):
        row=self.observe({
            self.HOME:'Org nr 810034882 '+''.join(
                '<a href="/news/'+name+'">'+name+'</a>' for name in ('menu','product','updated','factory')),
            self.HOME+'news/menu':
                '<nav><h1>Latest news</h1><time itemprop="datePublished" datetime="2026-09-01">Date</time></nav>',
            self.HOME+'news/product':
                '<h1>Product catalog</h1><meta property="article:published_time" content="2026-09-02">'
                '<script type="application/ld+json">{"@type":"Product","name":"Tool"}</script>',
            self.HOME+'news/updated':
                '<h1>Updated page</h1><time class="updated" datetime="2026-09-03">Updated</time>'
                '<script type="application/ld+json">{"@type":"NewsArticle","headline":"Updated page","dateModified":"2026-09-03"}</script>',
            self.HOME+'news/factory':
                '<main><h1>Factory opens</h1><time itemprop="datePublished" datetime="2026-09-04">Published</time></main>',
        })
        activity=self.by_field(row,'website.activity')
        self.assertEqual(activity['availability'],'available')
        self.assertEqual(activity['value'],[{'title':'Factory opens','date':'2026-09-04',
                                            'url':self.HOME+'news/factory'}])
        self.assertEqual(activity['qualifiers']['coverage'],'partial')
        self.assertGreaterEqual(len(activity['qualifiers']['candidate_limitations']),3)
        self.assertEqual(self.by_field(row,'website.verified_url')['availability'],'available')

    def test_only_uncertain_news_stays_ambiguous_not_absent(self):
        row=self.observe({
            self.HOME:'Org nr 810034882 <a href="/news/changed">Changed</a>',
            self.HOME+'news/changed':'<h1>Page</h1><script type="application/ld+json">'
                '{"@type":"NewsArticle","headline":"Page","dateModified":"2026-09-01"}</script>',
        })
        activity=self.by_field(row,'website.activity')
        self.assertEqual(activity['availability'],'ambiguous')
        self.assertIsNone(activity['value'])
        self.assertEqual(activity['qualifiers']['coverage'],'unresolved')
        self.assertEqual(self.by_field(row,'legal_name')['availability'],'available')

    def test_index_article_for_different_url_is_not_published_as_index_news(self):
        row=self.observe({self.HOME:'Org nr 810034882 <script type="application/ld+json">'
            '{"@type":"NewsArticle","headline":"Elsewhere","datePublished":"2026-09-01",'
            '"url":"https://example.test/news/elsewhere"}</script>'})
        activity=self.by_field(row,'website.activity')
        self.assertEqual(activity['availability'],'ambiguous')
        self.assertIsNone(activity['value'])

    def test_same_page_jsonld_article_is_still_accepted_without_visible_h1(self):
        row=self.observe({self.HOME:'Org nr 810034882 <script type="application/ld+json">'
            '{"@type":"NewsArticle","headline":"Announcement","datePublished":"2026-09-01",'
            '"url":"https://example.test/"}</script>'})
        self.assertEqual(self.by_field(row,'website.activity')['value'][0]['title'],'Announcement')

    def test_wrong_employer_posting_does_not_erase_own_posting(self):
        row=self.observe({self.HOME:'Org nr 810034882 <script type="application/ld+json">['
            '{"@type":"JobPosting","title":"Other vacancy","datePosted":"2026-09-01",'
            '"hiringOrganization":{"name":"Other AS"}},'
            '{"@type":"JobPosting","title":"Own vacancy","datePosted":"2026-09-02",'
            '"hiringOrganization":{"name":"Example AS"}}]</script>'})
        hiring=self.by_field(row,'website.hiring')
        self.assertEqual(hiring['availability'],'available')
        self.assertEqual([item['title'] for item in hiring['value']],['Own vacancy'])
        self.assertEqual(hiring['qualifiers']['coverage'],'partial')

    def test_agent_tavily_free_flag_requires_explicit_allowance(self):
        import agent
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'input.jsonl';source.write_text('')
            args=['agent.py','--input',str(source),'--output',str(Path(directory)/'out.jsonl'),
                  '--cache',str(Path(directory)/'cache'),'--replay','--search','tavily-free']
            with patch('sys.argv',args),self.assertRaises(SystemExit) as error:
                agent.main()
            self.assertEqual(error.exception.code,2)

    def test_agent_tavily_free_zero_allowance_can_replay_without_key_or_network(self):
        import agent
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'input.jsonl';source.write_text('')
            output=Path(directory)/'out.jsonl'
            args=['agent.py','--input',str(source),'--output',str(output),
                  '--cache',str(Path(directory)/'cache'),'--replay','--search','tavily-free',
                  '--search-free-credit-limit','0']
            with patch('sys.argv',args),patch('socket.getaddrinfo',side_effect=AssertionError('network')):
                agent.main()
            self.assertEqual(output.read_text(),'')


class R5OperatorIdentity(unittest.TestCase):
    """Generic operator-role fixtures; no live company/cache input."""
    ORG=R5Precision.ORG
    HOME=R5Precision.HOME
    observe=R5Precision.observe
    by_field=R5Precision.by_field
    def operator_page(self, operator, body='', relationship='publisher'):
        website={'@type':'WebSite','@id':self.HOME+'#website','url':self.HOME,
                 relationship:{'@id':self.HOME+'#operator'}}
        declaration={'@type':'Organization','@id':self.HOME+'#operator',**operator}
        # Cross-script references exercise the same local resolver as @graph.
        return ('<script type="application/ld+json">'+json.dumps(website)+'</script>'
                '<script type="application/ld+json">'+json.dumps(declaration)+'</script>'
                +body)

    def test_explicit_other_operator_is_ambiguous_despite_target_mention_and_registry_url(self):
        other='974761076'
        page=self.operator_page({'legalName':'Parent Company AS','identifier':{
            '@type':'PropertyValue','propertyID':'Norwegian organisation number','value':other}},
            '<p>Subsidiary Example AS, Org nr 810034882, Main gate 12, 1234 Oslo.</p>'
            '<a href="mailto:office@example.test">Email</a>')
        row=self.observe({self.HOME:page})
        identity=self.by_field(row,'website.verified_url')
        self.assertEqual(identity['availability'],'ambiguous')
        self.assertIsNone(identity['value'])
        self.assertEqual(identity['identity_support']['state'],'different')
        proof=identity['identity_support']['operators'][0]
        self.assertEqual(proof['organisation_numbers'],[other])
        self.assertEqual(proof['operator_script_index'],1)
        self.assertEqual(proof['operator_json_pointer'],'')
        self.assertTrue(any(e['source_url']==self.HOME for e in row['evidence']))
        self.assertTrue(any(e['source_class']=='official_registry' for e in row['evidence']
                            if e['id'] in identity['evidence_ids']))
        self.assertEqual(self.by_field(row,'website.contact_channels')['availability'],'ambiguous')
        self.assertEqual(self.by_field(row,'employees')['value'],3)
        self.assertFalse(corroborated_site({
            'organisasjonsnummer':self.ORG,'navn':'Example AS','hjemmeside':self.HOME,
            'forretningsadresse':{'adresse':['Main gate 12'],'postnummer':'1234'}},
            Page(page,self.HOME)))

    def test_target_operator_preserves_identity_with_article_group_and_sponsor_ids(self):
        other='974761076'
        article={'@type':'NewsArticle','headline':'A published company bulletin',
                 'datePublished':'2026-09-01','url':self.HOME,
                 'about':{'@type':'Organization','taxID':other,'name':'Other Group'},
                 'publisher':{'@type':'Organization','taxID':other,'name':'External Publisher'}}
        sponsor={'@type':'WebSite','url':'https://sponsor.test/','operator':{
            '@type':'Organization','identifier':{'@type':'PropertyValue',
                'propertyID':'NO:OrgNr','value':other}}}
        page=self.operator_page({'legalName':'Example AS','identifier':{
            '@type':'PropertyValue','propertyID':'NO:OrgNr','value':int(self.ORG)}},
            '<meta name="description" content="Example AS builds useful tools.">'
            '<p>News about our group. Sponsor Org nr 974761076.</p>'
            '<script type="application/ld+json">'+json.dumps([article,sponsor])+'</script>'
            '<footer><a href="https://facebook.com/example">Follow us</a>'
            '<a href="mailto:office@example.test">Email</a></footer>')
        row=self.observe({self.HOME:page})
        identity=self.by_field(row,'website.verified_url')
        self.assertEqual(identity['availability'],'available')
        self.assertEqual(identity['source_pointer'],'explicit_site_operator')
        self.assertEqual(identity['identity_support']['state'],'target')
        self.assertEqual(website_identity(self.ORG,Page(page,self.HOME)),'exact')
        self.assertEqual(self.by_field(row,'website.activity')['value'][0]['title'],
                         'A published company bulletin')
        self.assertEqual(self.by_field(row,'website.social_links')['availability'],'available')

    def test_different_legal_name_without_id_is_unresolved_not_certain_other_company(self):
        page=self.operator_page({'legalName':'Parent Company AS'},
                                '<footer>Example AS, Org nr 810034882</footer>','operator')
        row=self.observe({self.HOME:page})
        identity=self.by_field(row,'website.verified_url')
        self.assertEqual(identity['availability'],'ambiguous')
        self.assertEqual(identity['identity_support']['state'],'unresolved')
        self.assertEqual(identity['identity_support']['operators'][0]['organisation_numbers'],[])
        self.assertEqual(identity['qualifiers']['own_entity_attribution'],'unresolved')
        self.assertIsNone(identity['value'])

    def test_absent_operator_is_not_a_new_group_word_veto(self):
        from agent import site_operator_identity
        page='<p>Our group supports partners.</p><footer>Org nr 810034882</footer>'
        self.assertEqual(site_operator_identity(self.ORG,Page(page,self.HOME),
                                               {'navn':'Example AS'})['state'],'absent')
        row=self.observe({self.HOME:page})
        self.assertEqual(self.by_field(row,'website.verified_url')['availability'],'available')
        self.assertEqual(self.by_field(row,'website.description')['availability'],'ambiguous')

    def test_conflicting_operators_on_current_website_remain_ambiguous(self):
        declarations={'@context':'https://schema.org','@graph':[
            {'@type':'WebSite','url':self.HOME,'publisher':[
                {'@id':'#target'},{'@id':'#other'}]},
            {'@type':'Organization','@id':'#target','identifier':{
                '@type':'PropertyValue','propertyID':'organisasjonsnummer','value':self.ORG}},
            {'@type':'Organization','@id':'#other','identifier':{
                '@type':'PropertyValue','propertyID':'organisasjonsnummer','value':'974761076'}}]}
        page='Org nr 810034882<script type="application/ld+json">'+json.dumps(declarations)+'</script>'
        row=self.observe({self.HOME:page})
        identity=self.by_field(row,'website.verified_url')
        self.assertEqual(identity['availability'],'ambiguous')
        self.assertEqual(identity['identity_support']['state'],'different')
        self.assertEqual(len(identity['identity_support']['operators']),2)


    def test_foreign_or_invalid_explicit_website_url_cannot_be_overridden_by_local_id(self):
        for explicit_url in ('https://sponsor.test/', None, '', 'javascript:invalid'):
            with self.subTest(explicit_url=explicit_url):
                sponsor={'@type':'WebSite','url':explicit_url,'@id':'#sponsor-site',
                         'publisher':{'@type':'Organization','identifier':{
                             '@type':'PropertyValue','propertyID':'NO:OrgNr','value':'974761076'}}}
                page=self.operator_page({'legalName':'Example AS','identifier':{
                    '@type':'PropertyValue','propertyID':'NO:OrgNr','value':self.ORG}},
                    '<footer>Org nr 810034882</footer>'
                    '<script type="application/ld+json">'+json.dumps(sponsor)+'</script>')
                row=self.observe({self.HOME:page})
                identity=self.by_field(row,'website.verified_url')
                self.assertEqual(identity['availability'],'available')
                self.assertEqual(identity['identity_support']['state'],'target')
                proofs=identity['identity_support']['operators']
                self.assertEqual(len(proofs),1)
                self.assertEqual(proofs[0]['organisation_numbers'],[self.ORG])
                self.assertEqual(proofs[0]['website_url'],self.HOME)
