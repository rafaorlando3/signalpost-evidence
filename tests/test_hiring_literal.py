import unittest
from agent import Page, link_family
from hiring_discovery import application_links, delegated_hiring_pages, literal_hiring_candidates


class LiteralHiring(unittest.TestCase):
    own='https://example.test/karriere/engineer/'
    ats='https://ats.test/ApplicationInit.aspx?cid=7&ProjectId=45'
    body='<main><p>Ledig stilling</p><h1>Engineer – Instrumentation</h1><p>Vi søker en ingeniør.</p><a href="'+ats+'">Søk på stilling</a></main>'

    def candidates(self, body=None, ats_html=None, operator='target', identity=True, date='2026-10-31', source=None):
        page=Page(body if body is not None else self.body,self.own)
        response={'url':self.own,'identity_verified':identity,'site_operator':{'state':operator}}
        ats=Page(ats_html if ats_html is not None else '<title>Talentech - Engineer – Instrumentation</title><p>Application due 15.11.2026</p>',self.ats)
        rsp={'url':self.ats,'requested_url':self.ats,'retrieved_at':date+'T12:00:00Z','delegated_from_url':source or self.own}
        return literal_hiring_candidates(page,response,{'navn':'Example AS'},[(ats,rsp)])

    def test_imprint_is_generic_identity_lead(self):
        self.assertEqual(link_family('https://example.test/imprint/'),'identity')

    def test_undated_job_keeps_publication_null_and_deadline_separate(self):
        result=self.candidates()[0]
        self.assertIsNone(result['datePosted'])
        self.assertEqual(result['validThrough'],'2026-11-15')
        self.assertEqual(result['hiringOrganization']['name'],'Example AS')
        self.assertIn('ATS employer not independently displayed',result['_employer_basis'])

    def test_expired_invalid_and_comment_only_deadline_are_excluded(self):
        for date in ['30.10.2026','31.02.2027']:
            self.assertFalse(self.candidates(ats_html='<title>Engineer – Instrumentation</title>Application due '+date))
        self.assertFalse(self.candidates(ats_html='<title>Engineer – Instrumentation</title><!--Application due 15.11.2026-->'))

    def test_same_day_deadline_not_marked_as_expired(self):
        self.assertTrue(self.candidates(date='2026-11-15'))

    def test_group_footer_or_unverified_site_cannot_establish_employer(self):
        for state in ['absent','different','unresolved']:
            self.assertFalse(self.candidates(operator=state))
        self.assertFalse(self.candidates(identity=False))

    def test_specific_role_and_matching_explicit_link_are_required(self):
        self.assertFalse(self.candidates(source='https://example.test/other-role'))
        self.assertFalse(self.candidates(ats_html='<title>Talentech - Other role</title>Application due 15.11.2026'))
        self.assertFalse(self.candidates(body=self.body.replace('Søk på stilling','Contact')))
        self.assertFalse(self.candidates(body=self.body.replace('Vi søker','Vårt team')))
        self.assertFalse(self.candidates(body=self.body.replace('Ledig stilling','Careers')))

    def test_spontaneous_and_closed_recruiting_pages_are_excluded(self):
        self.assertFalse(self.candidates(body=self.body.replace('Engineer – Instrumentation','Åpen søknad')))
        self.assertFalse(self.candidates(body=self.body+'<p>Stillingen er besatt</p>'))
        self.assertFalse(self.candidates(ats_html='<title>Engineer – Instrumentation</title><p>Position is filled</p>Application due 15.11.2026'))

    def test_application_submit_login_and_credentials_are_not_fetched(self):
        for url in ['https://ats.test/ApplicationSubmit.aspx','https://ats.test/login','https://name:secret@ats.test/ApplicationInit.aspx','javascript:submit()']:
            self.assertFalse(application_links(Page(self.body.replace(self.ats,url),self.own)))

    def test_only_get_of_explicit_public_landing_and_parent_recorded(self):
        class Fetch:
            requests=0
            limit=2
            def __init__(self):self.visited=[]
            def get(self,url,**kw):
                self.requests+=1;self.visited.append(url)
                return {'url':url,'status':'available','text':'<title>Engineer</title>','retrieved_at':'2026-10-31T12:00:00Z'}
        f=Fetch();page=Page(self.body,self.own)
        result=delegated_hiring_pages([(page,{'url':self.own})],f,Page)
        self.assertEqual(f.visited,[self.ats])
        self.assertEqual(result[0][1]['delegated_from_url'],self.own)

class LiteralLegalOwner(unittest.TestCase):
    def test_owner_role_number_and_exact_name_required(self):
        from agent import site_operator_identity
        from test_agent import R5Precision as Helper
        h=Helper();body='<main>Eieren av dette nettstedet er: Example AS Example street 1 1234 Oslo MVA ID: '+h.ORG+' MVA</main>'
        def check(body,url='https://example.test/imprint/'):
            return site_operator_identity(h.ORG,Page(body,url),{'navn':'Example AS'},'https://example.test/')['state']
        self.assertEqual(check(body),'target')
        self.assertEqual(check(body.replace('Eieren av dette nettstedet er','Customer')),'absent')
        self.assertEqual(check(body,url='https://example.test/news/customer'),'absent')
        self.assertEqual(check(body.replace('Example AS','Other AS')),'unresolved')
        self.assertEqual(check(body.replace(h.ORG,'999296432')),'different')
        self.assertEqual(check('<!--'+body+'-->'),'absent')

class HiringEnvelope(unittest.TestCase):
    def test_site_owner_proof_carries_to_earlier_named_role_and_retains_ats_evidence(self):
        from test_agent import R5Precision as Helper
        h=Helper();ats='https://ats.test/ApplicationInit.aspx?cid=7&ProjectId=45';role=h.HOME+'karriere/engineer/'
        row=h.observe({h.HOME:'<a href="/karriere/engineer/">Engineer</a><a href="/imprint/">Imprint</a>',
            h.HOME+'imprint/':'<main>Eieren av dette nettstedet er: Example AS Example street 1 MVA ID: '+h.ORG+' MVA</main>',
            role:'<main><p>Ledig stilling</p><h1>Engineer</h1><p>Vi søker en ingeniør.</p><a href="'+ats+'">Søk på stilling</a></main>',
            ats:'<title>Talentech - Engineer</title><p>Application due 15.11.2026</p>'})
        claim=h.by_field(row,'website.hiring')
        self.assertEqual(claim['availability'],'available')
        self.assertIsNone(claim['value'][0]['date'])
        self.assertEqual(claim['value'][0]['valid_through'],'2026-11-15')
        sources={e['source_url'] for e in row['evidence'] if e['id'] in claim['evidence_ids']}
        self.assertIn(ats,sources);self.assertIn(role,sources)

class RegistryPortalDiscovery(unittest.TestCase):
    def test_observed_legal_name_child_is_verified_and_malformed_link_ignored(self):
        from test_agent import R5Precision as Helper
        h=Helper();child='https://example.no/'
        row=h.observe({'https://group.test/':'<a href="https://example.no:bad/">Broken</a><a href="'+child+'">Our Example business</a>',
            child:'<a href="/imprint/">Imprint</a>',
            child+'imprint/':'<main>Eieren av dette nettstedet er: Example AS Example street 1 MVA ID: '+h.ORG+' MVA</main>'},
            registry_extra={'hjemmeside':'https://group.test/'})
        self.assertEqual(h.by_field(row,'website.verified_url')['value'],child)
        self.assertEqual(row['website_attempts'][1]['origin'],'entity_portal_link')
