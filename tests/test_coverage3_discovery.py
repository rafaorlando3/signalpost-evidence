import tempfile,unittest
from unittest.mock import patch
from agent import Page,Fetcher,crawl_company
from hiring_discovery import delegated_hiring_pages,closed_hiring_page

class Coverage3Discovery(unittest.TestCase):
 def test_asset_contact_labels_and_sitemap_paths_cannot_consume_page_budget(self):
  html='<title>Example Works</title><footer>Org.nr. 810 034 882</footer><a href="/contact">Contact</a>'
  for path in ['/about/privacy.jpg.webp','/contact/icon.svg','/careers/role.mp4','/contact-form-confirmation']:
   html+='<a href="'+path+'">Contact</a>'
  response={'url':'https://example.test/','status':'available','text':html}
  requested=[]
  def get(url,**kw):
   requested.append(url)
   return {'url':url,'status':'available','text':'<p>Org.nr. 810 034 882</p>' if url.endswith('/contact') else '<urlset><url><loc>https://example.test/jobs/opening.png.webp</loc></url></urlset>','status_code':200}
  with tempfile.TemporaryDirectory() as d:
   f=Fetcher(d,replay=True)
   with patch.object(f,'get',side_effect=get):
    verified,pages=crawl_company('810034882',{'navn':'Example Works AS'},response,f)
  self.assertTrue(verified);self.assertIn('https://example.test/contact',requested)
  self.assertFalse(any(x in u for u in requested for x in ['.webp','.svg','.mp4','confirmation']))
 def test_linked_named_ad_is_discovered_without_an_external_job_seed(self):
  page=Page('<h1>Careers</h1><p>Open applications welcome.</p><a href="https://www.finn.no/job/ad/123456789">Mechanical engineer</a>','https://example.test/careers')
  rsp={'url':page.url,'identity_verified':True};requested=[]
  def get(url,**kw):
   requested.append(url)
   return {'url':url,'text':'<title>Mechanical engineer</title>','status':'available'}
  with tempfile.TemporaryDirectory() as d:
   f=Fetcher(d,replay=True)
   with patch.object(f,'get',side_effect=get):out=delegated_hiring_pages([(page,rsp)],f,Page)
  self.assertEqual(requested,['https://www.finn.no/job/ad/123456789'])
  self.assertFalse(out[0][1]['identity_verified'])
  self.assertEqual(out[0][1]['delegated_from_url'],page.url)
 def test_named_ad_search_customer_and_unverified_links_do_not_delegate(self):
  for path,url,third,verified in [('/careers','https://www.finn.no/job/search?query=engineer',False,True),('/customers','https://www.finn.no/job/ad/123',False,True),('/careers','https://www.finn.no/job/ad/123',True,True),('/careers','https://www.finn.no/job/ad/123',False,False)]:
   pg=Page('<a href="'+url+'">Mechanical engineer</a>','https://example.test'+path);pg.links[0]['third_party_context']=third
   with tempfile.TemporaryDirectory() as d:
    f=Fetcher(d,replay=True)
    with patch.object(f,'get',side_effect=AssertionError('not a public career lead')):
     self.assertEqual(delegated_hiring_pages([(pg,{'url':pg.url,'identity_verified':verified})],f,Page),[])
 def test_closed_ad_is_not_open_because_schema_remains_on_page(self):
  self.assertTrue(closed_hiring_page(Page('<h1>Engineer</h1><div>Besatt</div>','https://board.test/job/ad/123')))
  self.assertTrue(closed_hiring_page(Page('<h1>Engineer</h1><p>Fristen er utløpt</p>','https://board.test/job/ad/123')))
  self.assertFalse(closed_hiring_page(Page('<h1>Engineer</h1><p>Applications welcome.</p>','https://board.test/job/ad/123')))
 def test_expired_reciprocal_board_ad_vetoes_only_the_same_named_employer_and_role(self):
  import json
  from hiring_discovery import literal_hiring_candidates
  data={'navn':'Example Engineering AS','organisasjonsnummer':'810034882'}
  u='https://example.test/engineer';ad='https://www.finn.no/job/ad/123456789'
  body='<h1>Mechanical engineer</h1><p>Example Engineering AS: Vi søker ingeniør. Kvalifikasjoner: degree. Søknadsfrist: Snarest. Søknader vurderes fortløpende. Søknad sendes til: office@example.test</p><a href="mailto:office@example.test">office@example.test</a><a href="'+ad+'">finn.no</a><footer>Org.nr. 810 034 882</footer>'
  page=Page(body,u);rsp={'url':u,'identity_verified':True,'retrieved_at':'2026-11-01T00:00:00Z'}
  self.assertTrue(literal_hiring_candidates(page,rsp,data,[]))
  for employer,title,closed,expected in [('Example Engineering AS','Mechanical engineer',True,False),('Different AS','Mechanical engineer',True,True),('Example Engineering AS','Sales manager',True,True),('Example Engineering AS','Mechanical engineer',False,True)]:
   ld={'@type':'JobPosting','title':title,'hiringOrganization':{'name':employer},'datePosted':'2026-10-01'}
   board=Page('<div>'+('Fristen er utløpt' if closed else 'Applications welcome')+'</div><script type="application/ld+json">'+json.dumps(ld)+'</script>',ad)
   sources=[(board,{'url':ad,'requested_url':ad,'delegated_from_url':u,'delegated_from_verified_careers':True})]
   self.assertEqual(bool(literal_hiring_candidates(page,rsp,data,sources)),expected)
