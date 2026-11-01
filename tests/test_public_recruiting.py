import json,copy,tempfile,unittest
from pathlib import Path
from urllib.parse import urlencode
from unittest.mock import patch
from agent import Page,Fetcher,research,digest,encode
from public_recruiting import parse_postings,job_key,discover
from audit import audit
import test_pipeline as pipeline_fixtures
from test_pipeline import save,BASE,ORG

DATA={'organisasjonsnummer':ORG,'navn':'Example Plant AS','antallAnsatte':20}
AD='https://www.finn.no/job/ad/123456789'
DATE='2026-11-01T00:00:00Z'
def html(number=ORG,name='Example Plant AS',title='Mechanical engineer',posted='2026-10-28',deadline='2026-11-22',state='',homepage='https://own-brand.test/'):
 obj={'@type':'JobPosting','title':title,'url':AD,'datePosted':posted,'validThrough':deadline,'hiringOrganization':{'@type':'Organization','name':name,'url':homepage}}
 return '<h1>'+title+'</h1><p>'+state+'</p><script type="application/ld+json">'+json.dumps(obj)+'</script><h2>Annonseinformasjon</h2><div>Org.nr. : '+number+'</div><p>Rapporter annonse</p>'
def rsp(url=AD,text=None):return {'url':url,'requested_url':url,'text':text or html(),'status':'available','status_code':200,'retrieved_at':DATE,'content_sha256':digest((text or html()).encode())}
def parse(body=None,response=None,data=None,units=None):
 r=response or rsp(text=body);return parse_postings(Page(r['text'],r['url']),r,data or DATA,units or [])

class PublicRecruiting(unittest.TestCase):
 def test_primary_ad_number_name_date_and_homepage_are_separate_evidence(self):
  r=parse()[0];self.assertEqual(r['item']['date'],'2026-10-28');self.assertEqual(r['item']['employer_binding']['published_organisation_number'],ORG);self.assertEqual(r['homepage'],'https://own-brand.test/')
 def test_wrong_employer_unscoped_number_comment_and_conflicting_numbers_withheld(self):
  for body in [html(number='974761076'),html(name='Example Parent AS'),html().replace('Annonseinformasjon','Related companies'),html().replace('<div>Org.nr. : '+ORG+'</div>','<!--Org.nr. : '+ORG+'-->'),html().replace('Rapporter annonse','Org.nr. 974761076 Rapporter annonse')]:self.assertFalse(parse(body))
 def test_closed_expired_future_and_undated_ads_withheld(self):
  for body in [html(state='Fristen er utløpt'),html(state='Besatt'),html(deadline='2026-10-30'),html(posted='2026-11-02'),html(posted=None),html(deadline='19.10'),html(title='Åpen søknad')]:self.assertFalse(parse(body))
 def test_unavailable_body_and_foreign_ad_url_do_not_publish(self):
  self.assertFalse(parse(response={**rsp(),'status':'blocked','status_code':429}))
  self.assertFalse(parse(html().replace('"url": "'+AD+'"','"url": "https://www.finn.no/job/ad/987654321"')))
 def test_malformed_external_url_is_not_a_posting_or_dedup_crash(self):
  self.assertEqual(job_key({'url':'https://[invalid'}),'https://[invalid')
  response={**rsp(),'url':'https://[invalid'}
  self.assertFalse(parse_postings(Page('<h1>Mechanical engineer</h1>',AD),response,DATA,[]))
 def test_registered_child_requires_current_parent_relationship(self):
  child='974761076';units=[{'organisasjonsnummer':child,'overordnetEnhet':ORG,'navn':'Example Plant AS AVD TOWN'}]
  result=parse(html(number=child),units=units)[0]['item'];self.assertEqual(result['employer_binding']['method'],'published_registered_child_number')
  self.assertFalse(parse(html(number=child),units=[{**units[0],'overordnetEnhet':'892074232'}]))
 def test_syndication_deduplicates_by_explicit_source_not_similar_title(self):
  self.assertEqual(job_key({'url':AD}),job_key({'url':'https://arbeidsplassen.nav.no/stillinger/stilling/x','source_posting_url':'http://www.finn.no/123456789'}))
  self.assertNotEqual(job_key({'url':AD}),job_key({'url':'https://www.finn.no/job/ad/987654321'}))
 def test_search_result_is_a_url_lead_not_an_employer_assertion(self):
  class F:
   requests=0;limit=5
   def __init__(self):self.urls=[]
   def get(self,url,**kwargs):
    self.urls.append(url);self.requests+=1
    return rsp(url, '<article><a href="'+AD+'">Mechanical engineer</a><strong>Example Plant AS</strong></article>' if '/search?' in url else html())
  f=F();result=discover(DATA,[],f);self.assertEqual(len(result['records']),1);self.assertEqual(len(f.urls),2);self.assertEqual(f.urls[0],'https://www.finn.no/job/search?'+urlencode({'q':DATA['navn']}));self.assertEqual(f.urls[1],AD)
 def test_missing_search_results_and_wrong_numbers_never_become_jobs(self):
  class F:
   requests=0;limit=8
   def get(self,url,**kwargs):
    self.requests+=1
    return rsp(url,'<a href="'+AD+'">Example Plant AS</a>' if '/search?' in url else html(number='974761076'))
  self.assertFalse(discover(DATA,[],F())['records'])

class NAVPrimary(unittest.TestCase):
 UUID='11111111-2222-3333-4444-555555555555'
 def source(self,**changes):
  obj={'id':self.UUID,'status':'ACTIVE','title':'Mechanical engineer','published':'2026-10-30T08:00:00Z','updated':'2026-10-31T09:00:00Z','expires':'2026-11-22T00:00:00Z','employer':{'orgnr':ORG,'name':DATA['navn'],'homepage':'https://own-brand.test/'},'application':{'applicationDueDate':'2026-11-22'},'sourceUrl':AD};obj.update(changes)
  script='self.__next_f.push('+json.dumps([1,'12:'+json.dumps(obj)])+');'
  body='<h1>Mechanical engineer</h1><script>'+script+'</script>'
  return rsp('https://arbeidsplassen.nav.no/stillinger/stilling/'+self.UUID,body)
 def test_current_page_uuid_and_published_field_not_updated(self):
  r=parse(response=self.source())[0]['item'];self.assertEqual(r['date'],'2026-10-30T08:00:00Z');self.assertEqual(r['source_posting_url'],AD)
 def test_similar_ads_inactive_other_entity_and_future_publication_rejected(self):
  for r in [self.source(id='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'),self.source(status='INACTIVE'),self.source(employer={'orgnr':'974761076','name':DATA['navn']}),self.source(published='2026-11-03T00:00:00Z')]:self.assertFalse(parse(response=r))
 def test_malformed_application_object_is_withheld(self):
  self.assertFalse(parse(response=self.source(application='not an object')))

class PublicDiscoveryPipeline(unittest.TestCase):
 def test_existing_website_leads_keep_priority_over_public_search_budget(self):
  with tempfile.TemporaryDirectory() as d,patch('socket.getaddrinfo',side_effect=AssertionError('network forbidden')):
   pipeline_fixtures.Pipeline().fixture(d);save(d,BASE,DATA)
   own='https://exampleplant.no/'
   for url,text in [(own+'robots.txt','User-agent: *\nAllow: /'),(own,'<title>Example Plant</title><p>Manufacturing and repair services for industrial customers.</p><footer>Example Plant AS Org.nr. '+ORG+'</footer>')]:
    (Path(d)/(digest(url.encode())+'.json')).write_text(encode(rsp(url,text)))
   f=Fetcher(d,replay=True);original=f.get;visited=[]
   def observed(url,**kwargs):visited.append(url);return original(url,**kwargs)
   f.get=observed
   row=research({'organisation_number':ORG},f);claims={c['field']:c for c in row['claims']}
   self.assertEqual(claims['website.verified_url']['value'],own)
   query=next(i for i,u in enumerate(visited) if u.startswith('https://www.finn.no/job/search?'))
   self.assertLess(visited.index(own),query)
 def test_no_hint_homepage_and_job_discovered_audited_and_tamper_rejected(self):
  with tempfile.TemporaryDirectory() as d,patch('socket.getaddrinfo',side_effect=AssertionError('network forbidden')):
   pipeline_fixtures.Pipeline().fixture(d);save(d,BASE,DATA)
   query='https://www.finn.no/job/search?'+urlencode({'q':DATA['navn']})
   sources=[('https://www.finn.no/robots.txt','User-agent: *\nAllow: /'),(query,'<a href="'+AD+'">Mechanical engineer</a>'),(AD,html()),('https://own-brand.test/robots.txt','User-agent: *\nAllow: /'),('https://own-brand.test/','<title>Example Plant</title><p>Manufacturing and repair services for industrial customers.</p><footer>Example Plant AS Org.nr. '+ORG+'</footer><a href="mailto:office@own-brand.test">Email</a>')]
   for url,text in sources:
    record=rsp(url,text);(Path(d)/(digest(url.encode())+'.json')).write_text(encode(record))
   row=research({'organisation_number':ORG},Fetcher(d,replay=True));c={x['field']:x for x in row['claims']}
   self.assertEqual(c['website.verified_url']['value'],'https://own-brand.test/')
   self.assertEqual(c['website.hiring']['value'][0]['url'],AD)
   self.assertTrue(audit([row],d)['passed'])
   changed=copy.deepcopy(row);next(x for x in changed['claims'] if x['field']=='website.hiring')['value'][0]['employer_binding']['published_organisation_number']='974761076'
   self.assertFalse(audit([changed],d)['passed'])

class LegalSuffixFallback(unittest.TestCase):
 def test_last_resort_suffix_domain_still_needs_first_party_legal_identity(self):
  from registry_discovery import legal_form_domain_candidates
  data={**DATA,'navn':'Example AS'}
  self.assertEqual(legal_form_domain_candidates(data),['https://exampleas.no/'])
  self.assertFalse(legal_form_domain_candidates({**data,'navn':'Example Parent AS'}))
  self.assertFalse(legal_form_domain_candidates({**data,'navn':'Holding AS'}))
  for number,expected in [(ORG,'available'),('974761076',None)]:
   with tempfile.TemporaryDirectory() as d,patch('socket.getaddrinfo',side_effect=AssertionError('network forbidden')):
    pipeline_fixtures.Pipeline().fixture(d);save(d,BASE,data);own='https://exampleas.no/'
    for url,text in [(own+'robots.txt','User-agent: *\nAllow: /'),(own,'<title>Example</title><p>Manufacturing and repair services for industrial customers.</p><footer>Example AS Org.nr. '+number+'</footer>')]:
     (Path(d)/(digest(url.encode())+'.json')).write_text(encode(rsp(url,text)))
    c={x['field']:x for x in research({'organisation_number':ORG},Fetcher(d,replay=True))['claims']}
    if expected:self.assertEqual(c['website.verified_url']['value'],own)
    else:self.assertNotEqual(c['website.verified_url']['availability'],'available')

class SearchCardRanking(unittest.TestCase):
 def test_correct_employer_below_unrelated_results_gets_the_detail_budget(self):
  wrong='https://www.finn.no/job/ad/111111111'
  class F:
   requests=0;limit=8
   def __init__(self):self.urls=[]
   def get(self,url,**kwargs):
    self.urls.append(url);self.requests+=1
    body='<article><a href="'+wrong+'">Engineer</a><strong>Other AS</strong></article><article><a href="'+AD+'">Engineer</a><strong>Example Plant AS</strong></article>' if '/search?' in url else html()
    return rsp(url,body)
  f=F();r=discover(DATA,[],f);self.assertEqual(len(r['records']),1);self.assertNotIn(wrong,f.urls);self.assertEqual(r['detail_attempts'],1)
 def test_nav_matching_employer_precedes_unrelated_finn_details(self):
  source=NAVPrimary().source();nav_url=source['url'];wrong='https://www.finn.no/job/ad/111111111'
  class F:
   requests=0;limit=10
   def __init__(self):self.urls=[]
   def get(self,url,**kwargs):
    self.urls.append(url);self.requests+=1
    if '/job/search?' in url:return rsp(url,'<article><a href="'+wrong+'">Engineer</a><strong>Other AS</strong></article>')
    if '/stillinger?' in url:return rsp(url,'<article><a href="'+nav_url+'">Mechanical engineer</a><p>Arbeidsgiver</p><p>Example Plant AS</p><p>Sted</p><p>Oslo</p></article>')
    return source
  f=F();r=discover(DATA,[],f);self.assertEqual(len(r['records']),1);self.assertEqual(r['records'][0]['item']['url'],nav_url);self.assertNotIn(wrong,f.urls)
 def test_search_label_cannot_replace_the_posting_corporate_number(self):
  class F:
   requests=0;limit=8
   def get(self,url,**kwargs):
    self.requests+=1
    return rsp(url,'<article><a href="'+AD+'">Engineer</a><strong>Example Plant AS</strong></article>' if '/search?' in url else html(number='974761076'))
  self.assertFalse(discover(DATA,[],F())['records'])
