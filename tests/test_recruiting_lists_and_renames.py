import json, tempfile, unittest
from unittest.mock import patch
from agent import Page, Fetcher
from hiring_discovery import delegated_hiring_pages, recruiting_index_links, recruiting_feed_details
from registry_discovery import renamed_email_domain_candidates


class RecruitingListsAndRenames(unittest.TestCase):
    def test_historical_email_suffix_changes_only_with_registry_name_history(self):
        data={'navn':'EXAMPLE SERVICES NORTH AS','epostadresse':'office@es-south.no',
              'historiskeNavn':[{'navn':'EXAMPLE SERVICES SOUTH AS'}]}
        self.assertEqual(renamed_email_domain_candidates(data),['https://es-north.no/','https://www.es-north.no/'])
        for changed in [dict(data,historiskeNavn=[]),dict(data,hjemmeside='declared.test'),
                        dict(data,epostadresse='user@gmail.com'),dict(data,epostadresse='es-south.no'),
                        dict(data,epostadresse='office@es-notsouth.no'),
                        dict(data,navn='OTHER BUSINESS NORTH AS'),dict(data,epostadresse='office@z-south.no')]:
            self.assertEqual(renamed_email_domain_candidates(changed),[])

    def test_generic_portal_root_list_and_literal_detail_are_visited(self):
        company=Page('<a href="https://careers.example.test">Careers</a>','https://example.test/')
        bodies={'https://careers.example.test':'<h1>Example Services AS</h1><a href="/jobs">Ledige stillinger</a><a href="/tag/jobs">Editorial jobs</a><a href="/login">Login</a>',
                'https://careers.example.test/jobs':'<h1>Vacancies</h1><a href="/jobs/12-engineer">Engineer</a>',
                'https://careers.example.test/jobs/12-engineer':'<h1>Engineer</h1><script type="application/ld+json">'+json.dumps({'@type':'JobPosting','title':'Engineer','datePosted':'2026-10-01','hiringOrganization':{'name':'Example Services AS'}})+'</script>'}
        visited=[]
        with tempfile.TemporaryDirectory() as directory:
            f=Fetcher(directory,replay=True)
            def get(url,**kw):
                f.requests+=1;visited.append(url)
                return {'url':url,'requested_url':url,'status':'available','status_code':200,'text':bodies[url]}
            with patch.object(f,'get',side_effect=get):
                out=delegated_hiring_pages([(company,{'url':company.url,'identity_verified':True})],f,Page,data={'navn':'Example Services AS'})
        self.assertEqual(visited,list(bodies))
        self.assertEqual(out[-1][0].ld[0]['hiringOrganization']['name'],'Example Services AS')
        self.assertTrue(all(not rsp['identity_verified'] for _,rsp in out))

    def test_empty_list_feed_observed_without_invented_vacancy(self):
        pg=Page('<a href="/jobs">Jobs</a><link rel="alternate" type="application/rss+xml" href="/jobs.rss"><a href="https://foreign.test/jobs">Jobs</a>','https://careers.other.test/')
        self.assertEqual(recruiting_index_links(pg),['https://careers.other.test/jobs','https://careers.other.test/jobs.rss'])
        feed=Page('<rss><channel><title>Example Services AS</title></channel></rss>','https://careers.other.test/jobs.rss')
        self.assertEqual(recruiting_feed_details(feed),[])
        feed=Page('<rss><channel><item><link>https://careers.other.test/jobs/1</link></item><item><link>https://foreign.test/jobs/2</link></item><item><link>https://user:pass@careers.other.test/jobs/3</link></item></channel></rss>',feed.url)
        self.assertEqual(recruiting_feed_details(feed),['https://careers.other.test/jobs/1'])
        self.assertEqual(feed.ld,[])

    def test_unverified_career_link_is_never_owner_proof(self):
        pg=Page('<a href="https://careers.example.test/jobs">Careers</a>','https://example.test/')
        with tempfile.TemporaryDirectory() as directory:
            f=Fetcher(directory,replay=True)
            with patch.object(f,'get',side_effect=AssertionError('unverified parent')):
                self.assertEqual(delegated_hiring_pages([(pg,{'url':pg.url,'identity_verified':False})],f,Page),[])
