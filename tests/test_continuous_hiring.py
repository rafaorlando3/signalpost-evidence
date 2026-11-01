import unittest
from agent import Page
from hiring_discovery import continuous_first_party_vacancy
class ContinuousHiring(unittest.TestCase):
 data={'navn':'Example Engineering AS','organisasjonsnummer':'810034882'}
 url='https://example.no/engineer'
 body='<main><h1>Er du vår nye ingeniør?</h1><p>Example Engineering søker kolleger. Vi søker en ingeniør til vårt team. Søknader vurderes fortløpende.</p><a href="https://ats.test/sok-stilling/567">Søk på stillingen</a></main><footer>Example Engineering AS Org.nr. 810 034 882</footer>'
 def result(self,body=None,**kw):
  return continuous_first_party_vacancy(Page(body or self.body,self.url),{'url':self.url,'identity_verified':True,'retrieved_at':'2026-11-01T00:00:00Z',**kw},self.data)
 def test_literal_rolling_notice_preserves_unknown_dates(self):
  c=self.result()[0];self.assertIsNone(c['datePosted']);self.assertIsNone(c['validThrough']);self.assertEqual(c['_application_url'],'https://ats.test/sok-stilling/567')
 def test_closed_spontaneous_expired_partial_date_and_other_employer_rejected(self):
  for change in ['Stillingen er besatt','Åpen søknad','Søknadsfrist: 30.10.2026','Søknadsfrist: 19.10','On behalf of our client']:
   self.assertFalse(self.result(self.body.replace('</main>','<p>'+change+'</p></main>')))
  self.assertFalse(self.result(self.body.replace('Example Engineering søker','Other Agency søker')))
  self.assertFalse(self.result(identity_verified=False))
 def test_unverified_identity_inert_comment_and_submit_link_cannot_supply_proof(self):
  for body in [self.body.replace('810 034 882','974 761 076'),self.body.replace('Søknader vurderes fortløpende.','<!--Søknader vurderes fortløpende.-->'),self.body.replace('/sok-stilling/567','/submit'),self.body.replace('Søk på stillingen','Privacy policy')]:self.assertFalse(self.result(body))
 def test_literal_role_title_and_job_sections_support_undated_specific_invitation(self):
  body='<title>Stilling ledig elektriker – Example Engineering</title>'+self.body.replace('Søknader vurderes fortløpende.','Hvem er du? Ønskede kvalifikasjoner: Fagbrev elektriker. Vi tilbyr: fast jobb.').replace('/sok-stilling/567','/tenant/sok-stilling/567').replace('Søk på stillingen','Send inn søknad her.')
  c=self.result(body)[0];self.assertEqual(c['title'],'Stilling ledig elektriker');self.assertIsNone(c['datePosted'])
  self.assertFalse(self.result(body.replace('<title>Stilling ledig elektriker – Example Engineering</title>','')))
