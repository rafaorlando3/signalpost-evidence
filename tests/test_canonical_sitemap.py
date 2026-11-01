import unittest
from site_discovery import xml_candidates
class CanonicalSitemap(unittest.TestCase):
 def test_alias_is_only_a_lead_on_the_verified_host(self):
  xml='<urlset><url><loc>https://example.no/engineer</loc></url><url><loc>https://other.no/engineer</loc></url><url><loc>https://name:secret@example.no/engineer</loc></url></urlset>'
  self.assertEqual(xml_candidates(xml,'https://www.example.no/sitemap.xml','www.example.no')[0],[])
  self.assertEqual(xml_candidates(xml,'https://www.example.no/sitemap.xml','www.example.no',canonical_alias=True)[0],['https://www.example.no/engineer'])
 def test_alias_never_accepts_subdomain_or_unusual_port(self):
  xml='<urlset><url><loc>https://jobs.example.no/a</loc></url><url><loc>https://example.no:444/a</loc></url></urlset>'
  self.assertEqual(xml_candidates(xml,'https://www.example.no/sitemap.xml','www.example.no',canonical_alias=True)[0],[])

class SitemapDiscoveryPipeline(unittest.TestCase):
 def test_valid_xml_in_404_is_only_a_lead_and_role_needs_own_200_source(self):
  import tempfile,json
  from pathlib import Path
  from unittest.mock import patch
  from agent import Fetcher,research,encode,digest
  from test_pipeline import Pipeline,save,BASE,ORG
  home='https://www.example.no/'
  with tempfile.TemporaryDirectory() as folder,patch('socket.getaddrinfo',side_effect=AssertionError('network forbidden')):
   Pipeline().fixture(folder);save(folder,BASE,{'organisasjonsnummer':ORG,'navn':'Example Engineering AS','hjemmeside':home})
   pages={home:(200,'<title>Example Engineering</title><a href="/careers">Careers</a><footer>Org.nr. 810 034 882</footer>'),home+'robots.txt':(200,'User-agent: *\nDisallow:'),home+'careers':(200,'<h1>Careers</h1>Our company careers'),home+'sitemap.xml':(404,'<urlset><url><loc>https://example.no/engineer</loc><lastmod>2026-10-30</lastmod></url></urlset>'),home+'engineer':(200,'<h1>Engineer</h1><p>Example Engineering: Vi søker en ingeniør. Søknader vurderes fortløpende.</p><a href="https://ats.test/sok-stilling/567">Søk på stillingen</a><footer>Org.nr. 810 034 882</footer>')}
   for u,(status,text) in pages.items():
    r={'url':u,'requested_url':u,'text':text,'status':'available' if status==200 else 'not_available','status_code':status,'retrieved_at':'2026-11-01T00:00:00Z','content_sha256':digest(text.encode())};(Path(folder)/(digest(u.encode())+'.json')).write_text(encode(r))
   row=research({'organisation_number':ORG},Fetcher(folder,replay=True));c=next(c for c in row['claims'] if c['field']=='website.hiring')
   self.assertEqual(c['value'][0]['url'],home+'engineer');self.assertIsNone(c['value'][0]['date']);self.assertIsNone(c['value'][0]['valid_through'])
   from audit import audit
   self.assertTrue(audit([row],folder)['passed'])
   c['value'][0]['title']='Invented vacancy';self.assertFalse(audit([row],folder)['passed'])
   r=json.loads((Path(folder)/(digest((home+'engineer').encode())+'.json')).read_text());r.update(status='not_available',status_code=404);(Path(folder)/(digest((home+'engineer').encode())+'.json')).write_text(encode(r))
   row=research({'organisation_number':ORG},Fetcher(folder,replay=True));self.assertIsNone(next(c for c in row['claims'] if c['field']=='website.hiring')['value'])
