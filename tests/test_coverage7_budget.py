"""A public careers portal must remain reachable under a real request cap."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent import Fetcher, digest, research
from search import DIRECTORIES, TavilySearch, identity_candidates


class ExternalCareerBudget(unittest.TestCase):
    def test_redirect_alias_does_not_repeat_identical_inspection_but_changed_body_is_rechecked(self):
        from test_pipeline import Pipeline, ORG
        from agent import encode
        aliases=['https://alias-one.test/','https://alias-two.test/']
        canonical='https://canonical.test/'
        for changed in [False,True]:
            with self.subTest(changed=changed),tempfile.TemporaryDirectory() as directory:
                Pipeline().fixture(directory)
                body='<title>Unknown business</title><a href="/contact">Contact</a>'
                pages=[(aliases[0],canonical,body),
                       (aliases[1],canonical,body+(' Org.nr. '+ORG if changed else '')),
                       (canonical+'contact',canonical+'contact','<h1>Contact</h1>')]
                pages += [(u+'robots.txt',u+'robots.txt','User-agent: *\nAllow: /') for u in aliases+[canonical]]
                for requested,url,text in pages:
                    rsp={'url':url,'requested_url':requested,'status':'available','status_code':200,
                         'retrieved_at':'2026-11-01T00:00:00Z','text':text,'content_sha256':digest(text.encode())}
                    (Path(directory)/(digest(requested.encode())+'.json')).write_text(encode(rsp))
                fetcher=Fetcher(directory,replay=True,public_jobs=False)
                with patch('registry_discovery.name_domain_candidates',return_value=aliases),patch('registry_discovery.legal_form_domain_candidates',return_value=[]),patch.object(fetcher,'get',wraps=fetcher.get) as get,patch('socket.getaddrinfo',side_effect=AssertionError('no network')):
                    row=research({'organisation_number':ORG},fetcher)
                site=next(c for c in row['claims'] if c['field']=='website.verified_url')
                self.assertEqual(site['availability']=='available',changed)
                if not changed:
                    self.assertTrue(row['website_attempts'][1]['reused_inspection'])
                    self.assertEqual(sum(c.args[0]==canonical+'contact' for c in get.call_args_list),1)

    def test_previous_site_is_only_a_revalidated_lead_and_old_contacts_are_not_copied(self):
        from test_pipeline import Pipeline, save, BASE, ORG
        from agent import encode
        own='https://old-public-site.test/'
        for previous_org, declared_org, accepted in [(ORG,ORG,True),('974761076',ORG,False),(ORG,'974761076',False)]:
            with self.subTest(previous_org=previous_org,declared_org=declared_org),tempfile.TemporaryDirectory() as directory:
                Pipeline().fixture(directory)
                prior={'organisation_number':previous_org,'claims':[
                    {'field':'website.verified_url','value':own,'availability':'available'},
                    {'field':'website.contact_channels','value':[{'type':'email','value':'stale@old-public-site.test','source_url':own}], 'availability':'available'}]}
                for url,text in [(own+'robots.txt','User-agent: *\nAllow: /'),
                                 (own,'<title>Fixture AS</title><footer>Org.nr. '+declared_org+'</footer>')]:
                    rsp={'url':url,'requested_url':url,'status':'available','status_code':200,
                         'retrieved_at':'2026-11-01T00:00:00Z','text':text,'content_sha256':digest(text.encode())}
                    (Path(directory)/(digest(url.encode())+'.json')).write_text(encode(rsp))
                with patch('socket.getaddrinfo',side_effect=AssertionError('no network')):
                    row=research({'organisation_number':ORG},Fetcher(directory,replay=True,public_jobs=False),prior)
                claims={c['field']:c for c in row['claims']}
                self.assertEqual(claims['website.verified_url']['availability']=='available',accepted)
                self.assertNotEqual(claims['website.contact_channels']['availability'],'available')

    def test_busy_site_still_reaches_named_external_job_without_weakening_employer(self):
        org = '810034882'
        own = 'https://example.test/'
        portal = 'https://careers.example.test/'
        base = 'https://data.brreg.no/enhetsregisteret/api/enheter/' + org
        for employer, accepted in [('Example AS', True), ('Other Company AS', False)]:
            with self.subTest(employer=employer), tempfile.TemporaryDirectory() as directory:
                fetcher = Fetcher(directory, replay=True, public_jobs=False)
                visited = []
                job = {'@type': 'JobPosting', 'title': 'Mechanical engineer',
                       'datePosted': '2026-10-20', 'validThrough': '2026-11-20',
                       'hiringOrganization': {'name': employer}}
                links = ''.join('<a href="/about/p'+str(i)+'">About our work</a>' for i in range(30))
                pages = {own: '<footer>Example AS Org.nr. '+org+' <a href="mailto:office@example.test">Email</a></footer>'
                              '<a href="'+portal+'#jobs">Ledige stillinger</a>'+links,
                         portal: '<h1>Careers</h1><a href="/jobs/123-engineer">Mechanical engineer</a>',
                         portal+'jobs/123-engineer': '<h1>Mechanical engineer</h1><script type="application/ld+json">'+json.dumps(job)+'</script>'}

                def get(url, **kwargs):
                    if fetcher.requests >= fetcher.limit:
                        return {'url': url, 'status': 'failed', 'error': 'budget_exhausted'}
                    fetcher.requests += 1
                    visited.append(url)
                    rsp = {'url': url, 'requested_url': url, 'status': 'available',
                           'status_code': 200, 'retrieved_at': '2026-11-01T00:00:00Z'}
                    if url == base:
                        rsp['json'] = {'organisasjonsnummer': org, 'navn': 'Example AS', 'hjemmeside': own}
                    elif url.endswith('/roller'): rsp['json'] = {'rollegrupper': []}
                    elif '/regnskapsregisteret/' in url: rsp['json'] = []
                    elif '/underenheter?' in url: rsp['json'] = {'page': {'totalPages': 0}}
                    rsp['text'] = pages.get(url, json.dumps(rsp.get('json', {})))
                    rsp['content_sha256'] = digest(rsp['text'].encode())
                    return rsp

                with patch.object(fetcher, 'get', side_effect=get), patch('socket.getaddrinfo', side_effect=AssertionError('no network')):
                    row = research({'organisation_number': org}, fetcher)
                claims = {c['field']: c for c in row['claims']}
                self.assertLessEqual(fetcher.requests, 20)
                self.assertIn(portal+'jobs/123-engineer', visited)
                self.assertEqual(claims['website.hiring']['availability'] == 'available', accepted)
                self.assertEqual(claims['website.contact_channels']['value'][0]['value'], 'office@example.test')

    def test_registry_anchor_keeps_priority_over_previous_url(self):
        from test_pipeline import Pipeline, save, BASE, ORG
        from agent import encode
        with tempfile.TemporaryDirectory() as directory:
            Pipeline().fixture(directory)
            current='https://current-site.test/'
            save(directory,BASE,{'organisasjonsnummer':ORG,'navn':'Fixture AS','hjemmeside':current})
            for url,text in [(current+'robots.txt','User-agent: *\nAllow: /'),
                             (current,'<title>Fixture AS</title><footer>Org.nr. '+ORG+'</footer>')]:
                rsp={'url':url,'requested_url':url,'status':'available','status_code':200,
                     'retrieved_at':'2026-11-01T00:00:00Z','text':text,'content_sha256':digest(text.encode())}
                (Path(directory)/(digest(url.encode())+'.json')).write_text(encode(rsp))
            prior={'organisation_number':ORG,'claims':[{'field':'website.verified_url','value':'https://previous-site.test/','availability':'available','evidence_ids':[]}]}
            with patch('socket.getaddrinfo',side_effect=AssertionError('no network')):
                row=research({'organisation_number':ORG},Fetcher(directory,replay=True,public_jobs=False),prior)
            self.assertEqual(next(c for c in row['claims'] if c['field']=='website.verified_url')['value'],current)

    def test_search_filters_directory_crowding_before_a_primary_candidate(self):
        results = [{'url': 'https://opplysning.byndle.no/company/example', 'content': 'Example AS'},
                   {'url': 'https://www.visitnorway.com/listings/example/123', 'content': 'Example AS'},
                   {'url': 'https://www.tavily.com/', 'content': 'Example AS'},
                   {'url': 'https://ours.test/kontakt', 'content': 'Example AS'}]
        self.assertEqual(identity_candidates(results, '810034882', 'Example AS'),
                         [{'url': 'https://ours.test/', 'hints': ['https://ours.test/kontakt']}])
        with tempfile.TemporaryDirectory() as directory:
            payload = TavilySearch(directory).payload('Example AS', mode='filtered_name')
        from search import ADDITIONAL_DIRECTORIES
        self.assertEqual(set(payload['exclude_domains']), DIRECTORIES-ADDITIONAL_DIRECTORIES)
