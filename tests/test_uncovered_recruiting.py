import unittest,tempfile,json
from pathlib import Path
from unittest.mock import patch
import test_public_recruiting as fixtures
import test_pipeline as pipeline
from urllib.parse import urlencode
from agent import Page
from public_recruiting import discover
from uncovered_recruiting import discover_uncovered,shared_registered_query
from test_public_recruiting import DATA,AD,ORG,html,rsp

class UncoveredRecruiting(unittest.TestCase):
    def test_old_negative_details_are_not_repeated_and_next_matching_ad_can_cover_employer(self):
        nav=fixtures.NAVPrimary().source(sourceUrl=None);index='https://arbeidsplassen.nav.no/stillinger?'+urlencode({'q':DATA['navn']})
        wrong='https://arbeidsplassen.nav.no/stillinger/stilling/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        source=rsp(index,'<article><p>Arbeidsgiver</p><p>'+DATA['navn']+'</p><a href="'+wrong+'">Old</a></article><article><p>Arbeidsgiver</p><p>'+DATA['navn']+'</p><a href="'+nav['url']+'">Current</a></article>')
        previous={'sources':[source,{**rsp(wrong,'Unavailable'),'status':'blocked','status_code':403}],'detail_attempts':2}
        class F:
            requests=20;limit=20;public_jobs=True
            def __init__(self):self.urls=[]
            def get(self,u,**kw):
                self.urls.append(u);self.requests+=1
                if u==nav['url']:return nav
                raise AssertionError('Repeated index or old detail: '+u)
        f=F();out=discover_uncovered(DATA,[],f,previous)
        self.assertEqual(len(out['records']),1);self.assertEqual(f.urls,[nav['url']]);self.assertEqual(f.limit,24)
        self.assertEqual(out['detail_attempts'],1);self.assertEqual(out['prior_detail_attempts'],2)
    def test_late_discovery_uses_no_more_than_the_shared_twenty_four_request_cap(self):
        class F:
            requests=20;limit=20;public_jobs=True
            def get(self,u,**kw):self.requests+=1;return rsp(u,'No results')
        f=F();out=discover_uncovered(DATA,[],f);self.assertLessEqual(f.requests,24);self.assertEqual(f.limit,24);self.assertFalse(out['records'])
    def test_explicit_closed_finn_source_vetoes_nav_syndication_in_resumed_phase(self):
        nav=fixtures.NAVPrimary().source();index='https://arbeidsplassen.nav.no/stillinger?'+urlencode({'q':DATA['navn']})
        source=rsp(index,'<article><p>Arbeidsgiver</p><p>'+DATA['navn']+'</p><a href="'+nav['url']+'">Current</a></article>')
        previous={'sources':[source,rsp(AD,html(state='Besatt'))],'detail_attempts':1}
        class F:
            requests=20;limit=20;public_jobs=True
            def get(self,u,**kw):self.requests+=1;return nav if u==nav['url'] else rsp(u,'No results')
        self.assertFalse(discover_uncovered(DATA,[],F(),previous)['records'])
    def test_foreign_published_employer_and_expired_posting_are_still_withheld(self):
        for changes in [{'employer':{'orgnr':'913884213','name':DATA['navn']}},{'application':{'applicationDueDate':'2026-10-30'}},{'status':'INACTIVE'}]:
            nav=fixtures.NAVPrimary().source(**changes);index='https://arbeidsplassen.nav.no/stillinger?'+urlencode({'q':DATA['navn']})
            class F:
                requests=20;limit=20;public_jobs=True
                def get(self,u,**kw):self.requests+=1;return nav if u==nav['url'] else rsp(u,'<article><p>Arbeidsgiver</p><p>'+DATA['navn']+'</p><a href="'+nav['url']+'">Engineer</a></article>')
            self.assertFalse(discover_uncovered(DATA,[],F())['records'])
    def test_unlabelled_broad_hits_do_not_spend_late_details_on_other_employers(self):
        nav=fixtures.NAVPrimary().source(sourceUrl=None);index='https://arbeidsplassen.nav.no/stillinger?'+urlencode({'q':DATA['navn']})
        source=rsp(index,'<a href="'+nav['url']+'">Engineer</a>')
        previous={'sources':[source],'checks':[{'url':index,'matching_employer_labels':0}],'detail_attempts':0}
        class F:
            requests=20;limit=20;public_jobs=True
            def get(self,u,**kw):
                self.requests+=1
                if u==nav['url']:raise AssertionError('unlabelled detail is not a late employer lead')
                return rsp(u,'No results')
        out=discover_uncovered(DATA,[],F(),previous);self.assertFalse(out['records']);self.assertEqual(out['detail_attempts'],0)
    def test_two_remaining_late_calls_can_query_and_fetch_when_nav_robots_already_checked(self):
        nav=fixtures.NAVPrimary().source(sourceUrl=None)
        from attribution import legal_stem
        search_url='https://arbeidsplassen.nav.no/stillinger?'+urlencode({'q':legal_stem(DATA['navn'])})
        legal_nav='https://arbeidsplassen.nav.no/stillinger?'+urlencode({'q':DATA['navn']})
        legal_finn='https://www.finn.no/job/search?'+urlencode({'q':DATA['navn']})
        prior={'sources':[rsp(u,'No matching employer') for u in [legal_nav,legal_finn]],
               'checks':[{'url':u,'matching_employer_labels':0} for u in [legal_nav,legal_finn]]}
        class F:
            requests=22;limit=24;robots={'https://arbeidsplassen.nav.no':object()}
            def __init__(self):self.urls=[]
            def get(self,u,**kw):
                self.urls.append(u);self.requests+=1
                if u==search_url:return rsp(u,'<article><p>Arbeidsgiver</p><p>'+DATA['navn']+'</p><a href="'+nav['url']+'">Engineer</a></article>')
                if u==nav['url']:return nav
                raise AssertionError('unexpected call: '+u)
        f=F();out=discover(DATA,[],f,resume=prior,max_details=2,stop_after_first=True,matching_labels_only=True)
        self.assertEqual(f.urls,[search_url,nav['url']]);self.assertEqual(f.requests,24);self.assertEqual(len(out['records']),1)
        f=F();f.robots={};out=discover(DATA,[],f,resume=prior,max_details=2,stop_after_first=True,matching_labels_only=True)
        self.assertFalse(out['records']);self.assertFalse(f.urls)
    def test_disabled_board_and_unverified_registry_never_grant_a_late_allowance(self):
        class F:
            requests=20;limit=20;public_jobs=False
            def get(self,*a,**k):raise AssertionError('disabled')
        f=F();self.assertFalse(discover_uncovered(DATA,[],f)['records']);self.assertEqual(f.limit,20)
        f.public_jobs=True;self.assertFalse(discover_uncovered({},[],f)['records']);self.assertEqual(f.limit,20)
    def test_shared_registered_business_prefix_is_only_a_query_and_preserves_legal_differentiators(self):
        data={'organisasjonsnummer':ORG,'navn':'New Parent AS'}
        units=[{'organisasjonsnummer':n,'overordnetEnhet':ORG,'navn':'Historic Engineering AS AVD '+city} for n,city in [('974761076','OSLO'),('974287005','BERGEN')]]
        self.assertEqual(shared_registered_query(data,units),'Historic Engineering AS')
        self.assertIsNone(shared_registered_query(data,units[:1]));self.assertIsNone(shared_registered_query(data,[{**u,'overordnetEnhet':'913884213'} for u in units]))
        units[1]['navn']='Historic Engineering Bergen AS AVD BERGEN';self.assertIsNone(shared_registered_query(data,units))
class LateEmployerPipeline(unittest.TestCase):
    def test_full_base_budget_can_recover_an_employer_without_erasing_website_or_contact(self):
        from agent import Fetcher,research,crawl_company,digest,encode
        from audit import audit
        own='https://exampleplant.no/'
        with tempfile.TemporaryDirectory() as directory:
            pipeline.Pipeline().fixture(directory);pipeline.save(directory,pipeline.BASE,{**DATA,'hjemmeside':own})
            nav=fixtures.NAVPrimary().source(sourceUrl=None)
            sources=[rsp(own+'robots.txt','User-agent: *\nAllow: /'),rsp(own,'<title>Example Plant</title><p>Manufacturing industrial products for Norwegian customers.</p><footer>Example Plant AS Org.nr '+ORG+'</footer><a href="mailto:office@exampleplant.no">Email</a>'),rsp('https://arbeidsplassen.nav.no/robots.txt','User-agent: *\nAllow: /'),rsp('https://arbeidsplassen.nav.no/stillinger?'+urlencode({'q':DATA['navn']}),'<article><p>Arbeidsgiver</p><p>'+DATA['navn']+'</p><a href="'+nav['url']+'">Engineer</a></article>'),nav]
            for source in sources:Path(directory,digest(source['url'].encode())+'.json').write_text(encode(source))
            def full_base(*args,**kwargs):
                result=crawl_company(*args,**kwargs)
                if result[0]:args[3].requests=20
                return result
            with patch('agent.crawl_company',side_effect=full_base):row=research({'organisation_number':ORG},Fetcher(directory,replay=True))
            claims={c['field']:c for c in row['claims']};self.assertEqual(claims['website.verified_url']['value'],own)
            self.assertEqual(claims['website.hiring']['availability'],'available');self.assertTrue(any(x['value']=='office@exampleplant.no' for x in claims['website.contact_channels']['value']))
            self.assertLessEqual(row['operations']['requests'],24);self.assertEqual(row['late_employer_discovery']['verified_ads'],1)
            self.assertTrue(audit([row],directory)['passed'])
if __name__=='__main__':unittest.main()
