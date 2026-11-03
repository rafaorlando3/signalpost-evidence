import tempfile,unittest
from search import identity_candidates,TavilySearch
from agent import Fetcher
class ScopedSearchTests(unittest.TestCase):
    def test_entity_leaf_survives_root_reduction_and_directories_do_not_crowd_it(self):
        r=identity_candidates([{'url':'https://www.largestcompanies.com/one','title':'Lakeside FUS Barnehage AS'},
            {'url':'https://fus.test/lakeside','title':'Lakeside FUS barnehage'},
            {'url':'https://fus.test/lakeside/staff','title':'Lakeside FUS barnehage'}],'810034882','LAKESIDE FUS BARNEHAGE AS')
        self.assertEqual(r[0]['url'],'https://fus.test/');self.assertEqual(r[0]['scoped_pages'],['https://fus.test/lakeside'])
    def test_client_references_documents_and_directory_paths_are_not_entity_leaves(self):
        for path in ['/customers/lakeside','/referenser/lakeside','/company/lakeside','/news/lakeside','/lakeside.pdf']:
            r=identity_candidates([{'url':'https://vendor.test'+path,'title':'Lakeside FUS Barnehage AS'}],'810034882','LAKESIDE FUS BARNEHAGE AS')
            self.assertNotIn('scoped_pages',r[0])
    def test_matching_domain_is_prioritized_over_a_supplier_reference(self):
        r=identity_candidates([{'url':'https://supplier.test/referenser/arvid-nilsson','title':'Arvid Nilsson'},
            {'url':'https://arvidnilsson.test/','title':'Arvid Nilsson'}],'810034882','ARVID NILSSON NORGE AS')
        self.assertEqual(r[0]['url'],'https://arvidnilsson.test/')
    def test_unknown_directory_profile_is_not_a_company_page(self):
        r=identity_candidates([{'url':'https://unknown-directory.test/tlf/lakeside-as/810034882','title':'Lakeside AS','content':'Org.nr 810034882'}],'810034882','LAKESIDE AS')
        self.assertNotIn('scoped_pages',r[0])
    def test_scoped_lead_is_lazy_and_replays_without_an_api_call(self):
        with tempfile.TemporaryDirectory() as d:
            s=TavilySearch(d,key='fixture',strategy='name_focus',transport=lambda *_:{'results':[{'url':'https://fus.test/lakeside','title':'Lakeside FUS barnehage'}],'usage':{'credits':1}})
            actual=list(s.iter_candidates('810034882','LAKESIDE FUS BARNEHAGE AS',Fetcher(d)))
            self.assertEqual([x[0] for x in actual],['https://fus.test/','https://fus.test/lakeside'])
            replay=TavilySearch(d,key='',strategy='name_focus',transport=lambda *_:self.fail('network'))
            self.assertEqual(actual,list(replay.iter_candidates('810034882','LAKESIDE FUS BARNEHAGE AS',Fetcher(d,replay=True))))

class ScopedSearchPipelineTests(unittest.TestCase):
    def test_shared_host_leaf_keeps_own_identity_and_drops_global_contact_pages(self):
        from unittest.mock import patch
        from test_agent import R5Precision
        from agent import research
        helper=R5Precision();base='https://fus.test/';leaf=base+'lakeside'
        class Search:
            def iter_candidates(self,*_):
                yield base,1,[]
                yield leaf,0,[]
        pages={base:'<h1>Parent Group</h1>Org.nr 987654321',leaf:'<h1>Lakeside FUS Barnehage AS</h1><footer>Org.nr '+helper.ORG+'</footer><a href="/global/contact">Contact</a>',base+'global/contact':'<h1>Group contact</h1><a href="mailto:global@fus.test">global@fus.test</a>'}
        original=research
        with patch('test_agent.research',side_effect=lambda incoming,f:original(incoming,f,search=Search())):
            row=helper.observe(pages,{'navn':'Lakeside FUS Barnehage AS','hjemmeside':None})
        site=next(c for c in row['claims'] if c['field']=='website.verified_url')
        self.assertEqual(site['value'],leaf);self.assertIn('specific company page',site['qualifiers']['site_scope'])
        contacts=next(c for c in row['claims'] if c['field']=='website.contact_channels')
        self.assertNotIn('global@fus.test',str(contacts['value']))

class NamedNumberLabels(unittest.TestCase):
    def test_legal_name_between_label_and_number_identifies_the_owner(self):
        from agent import Page,website_identity
        p=Page('<footer>Organisasjonsnummer Example AS: 810 034 882</footer>','https://example.test/')
        self.assertEqual(website_identity('810034882',p),'exact')
    def test_another_number_cannot_be_replaced_by_a_subsidiary_name_and_address(self):
        from agent import Page,website_identity,corroborated_site
        data={'organisasjonsnummer':'810034882','navn':'EXAMPLE BERGEN AS','hjemmeside':'example.test','forretningsadresse':{'adresse':['Main road 3'],'postnummer':'1234'}}
        p=Page('<title>Example</title><main>Example Bergen AS Main road 3, 1234 Bergen</main><footer>Organisasjonsnummer Other AS: 913 884 213</footer>','https://example.test/')
        self.assertEqual(website_identity('810034882',p,data),'conflict');self.assertFalse(corroborated_site(data,p))

class EmailDomainAliasTests(unittest.TestCase):
    def test_late_www_email_domain_is_a_lead_requiring_legal_identity(self):
        from test_agent import R5Precision
        helper=R5Precision()
        row=helper.observe({'https://www.example.no':'<title>Example</title><main><p>Example AS er en bedrift som leverer byggtjenester i Norge.</p></main>'},{'hjemmeside':None,'epostadresse':'post@example.no'})
        c=next(c for c in row['claims'] if c['field']=='website.verified_url')
        self.assertEqual(c['value'],'https://www.example.no')
        wrong=helper.observe({'https://www.example.no':'<title>Different Company</title>Org.nr 913 884 213'},{'hjemmeside':None,'epostadresse':'post@example.no'})
        c=next(c for c in wrong['claims'] if c['field']=='website.verified_url')
        self.assertNotEqual(c['availability'],'available')

if __name__=='__main__':unittest.main()
