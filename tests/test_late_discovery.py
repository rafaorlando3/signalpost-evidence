import unittest
from agent import Page
from registry_discovery import unresolved_name_host_aliases
from inline_recruiting import visit_observed_role_pages,candidates
import test_inline_recruiting as fixtures


class LateDiscovery(unittest.TestCase):
    def test_aliases_are_bounded_full_name_https_candidates(self):
        attempts=[{'url':'https://wholelegalbrand.no/','origin':'name_domain_heuristic',
                   'fetch_state':'blocked','fetch_error':'robots unreachable; complete disallow'},
                  {'url':'https://whole-legal-brand.no/','origin':'name_domain_heuristic','fetch_state':'blocked'},
                  {'url':'https://wholelegalbrand.com/','origin':'late_name_com_heuristic','fetch_state':'blocked'}]
        self.assertEqual(unresolved_name_host_aliases(attempts),
                         ['https://www.wholelegalbrand.no/','https://www.whole-legal-brand.no/'])

    def test_aliases_do_not_retry_success_prohibition_challenge_or_seen_host(self):
        base={'url':'https://wholelegalbrand.no/','origin':'name_domain_heuristic','fetch_state':'blocked'}
        for extra in [{'fetch_state':'available'}, {'fetch_error':'robots disallow'},
                      {'protection':{'javascript_challenge':True}},
                      {'robots':[{'policy_state':'rules'}],'fetch_error':'robots policy denied URL'},
                      {'origin':'anonymous_search'}, {'url':'http://wholelegalbrand.no/'}]:
            with self.subTest(extra=extra):self.assertEqual(unresolved_name_host_aliases([{**base,**extra}]),[])
        self.assertEqual(unresolved_name_host_aliases([base,{'url':'https://www.wholelegalbrand.no/'}]),[])

    def bundle(self,extra=''):
        helper=fixtures.InlineRecruiting();pages=helper.bundle()
        pg,rsp=pages[0];raw=pg.raw_html.replace('</main>',extra+'</main>')
        pages[0]=helper.page(raw)
        return helper,pages

    def fetcher(self,helper,text,**changes):
        class F:
            requests=20;limit=24
            def __init__(self):self.urls=[]
            def get(self,u,**kw):
                self.urls.append(u);self.requests+=1
                return helper.page(text,u)[1]
        f=F()
        for k,v in changes.items():setattr(f,k,v)
        return f

    def test_observed_team_link_can_supply_distinct_literal_role_without_date_guess(self):
        h,pages=self.bundle('<a href="/team-acme">Team Acme</a>')
        content='<main><h1>Team</h1><h2>Current openings</h2>'+h.job('Senior Developer')+'</main><footer><a href="/personvern">Personvern</a></footer>'
        f=self.fetcher(h,content);extra,checks=visit_observed_role_pages(pages,h.data,f,Page)
        self.assertEqual(f.urls,['https://www.acme.no/team-acme'])
        records=candidates(pages+extra,h.data)
        self.assertEqual([r['item']['title'] for r in records],['Account Executive','Senior Developer'])
        self.assertTrue(all(r['item']['date'] is None for r in records))
        self.assertEqual(f.requests,21)

    def test_team_source_is_not_a_vacancy_without_its_own_invitation(self):
        h,pages=self.bundle('<a href="/team-acme">Team Acme</a>')
        raw='<main><h1>Team</h1><h2>Current openings</h2>'+h.job('Senior Developer').replace('Send en søknad med CV til jobs@rekruttering.example.','Ta kontakt.')+'</main><footer><a href="/personvern">Personvern</a></footer>'
        extra,_=visit_observed_role_pages(pages,h.data,self.fetcher(h,raw),Page)
        self.assertEqual(len(candidates(pages+extra,h.data)),1)

    def test_external_login_bio_or_unobserved_url_is_never_fetched(self):
        h,pages=self.bundle('<a href="https://group.example/team">Team</a><a href="/team-acme?token=secret">Team</a><a href="/people/one">Person</a>')
        f=self.fetcher(h,'');self.assertEqual(visit_observed_role_pages(pages,h.data,f,Page),([],[]));self.assertFalse(f.urls)

    def test_spare_request_budget_and_existing_legal_owner_are_required(self):
        h,pages=self.bundle('<a href="/team-acme">Team</a>')
        for ps,f in [(pages,self.fetcher(h,'',requests=24)),(pages[:1],self.fetcher(h,''))]:
            self.assertEqual(visit_observed_role_pages(ps,h.data,f,Page),([],[]));self.assertFalse(f.urls)

    def test_wrong_owner_and_redirect_to_external_host_are_withheld(self):
        h,pages=self.bundle('<a href="/team-acme">Team</a>')
        f=self.fetcher(h,'<main>Org.nr 913 884 213</main>')
        extra,checks=visit_observed_role_pages(pages,h.data,f,Page);self.assertFalse(extra);self.assertFalse(checks[0]['compatible_own_page'])
        f=self.fetcher(h,'')
        def redirected(u,**kw):f.requests+=1;return h.page(h.job(),'https://external.example/team')[1]
        f.get=redirected;self.assertFalse(visit_observed_role_pages(pages,h.data,f,Page)[0])

    def test_last_own_career_get_is_included_in_final_envelope_budget(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from agent import Fetcher,research,crawl_company,digest,encode
        from validate import validate
        import test_pipeline as base
        own='https://example.test/'
        with tempfile.TemporaryDirectory() as directory:
            base.Pipeline().fixture(directory)
            base.save(directory,base.BASE,{'organisasjonsnummer':base.ORG,
                      'navn':'Example Engineering AS','hjemmeside':own})
            for url,text in [(own+'robots.txt','User-agent: *\nAllow: /'),
                             (own,'<title>Example Engineering</title><footer>Example Engineering AS Org.nr '+base.ORG+'</footer><a href="mailto:office@example.test">Email</a>')]:
                Path(directory,digest(url.encode())+'.json').write_text(encode({
                    'url':url,'status':'available','status_code':200,'text':text,
                    'retrieved_at':'2026-11-04T12:00:00Z','content_sha256':digest(text.encode())}))
            def base_budget(*args,**kwargs):
                result=crawl_company(*args,**kwargs)
                if result[0]:args[3].requests=20
                return result
            def late(data,units,fetcher,previous):
                fetcher.limit=24;fetcher.requests=23
                return {'records':[],'checks':[],'detail_attempts':0,'identity_sources':[]}
            def own_visit(pages,data,fetcher,page_type):
                fetcher.requests+=1
                return [],[{'url':own+'careers/closed','status':'not_available'}]
            with patch('agent.crawl_company',side_effect=base_budget), \
                    patch('uncovered_recruiting.discover_uncovered',side_effect=late), \
                    patch('inline_recruiting.visit_observed_role_pages',side_effect=own_visit):
                row=research({'organisation_number':base.ORG},Fetcher(directory,replay=True))
            self.assertEqual(row['operations']['requests'],24)
            self.assertEqual(row['portal_expansion']['late_requests'],4)
            self.assertTrue(validate([row],[base.ORG])['structurally_valid'])
            self.assertTrue(any(c['field']=='website.verified_url' and c['availability']=='available'
                                for c in row['claims']))
