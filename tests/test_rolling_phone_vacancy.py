import unittest
from agent import Page
from hiring_discovery import continuous_first_party_vacancy


class RollingPhoneVacancyTests(unittest.TestCase):
    data={'organisasjonsnummer':'810034882','navn':'EXAMPLE ELEKTRO AS'}
    raw='''<main><h1>Elektriker</h1><p>Vi i Example Elektro søker nå en dyktig elektriker.</p>
    <p>Example Elektro AS er en lokal elektrobedrift.</p><h2>Kvalifikasjoner</h2>
    <p>Med fagbrev og førerkort.</p><h2>Vi tilbyr:</h2><p>Varierte oppgaver.</p>
    <p>Har du spørsmål og ønsker å vite mer rundt stillingen? Ta kontakt med daglig leder.
    Tlf: <a href="tel:91746741">91746741</a></p><p>Søknadsfrist: Løpende</p></main>
    <footer>Org.nr 810034882 <a href="tel:62480140">62480140</a></footer>'''

    def result(self,raw=None,url='https://example.test/om-oss/ledige-stillinger/elektriker',**rsp):
        pg=Page(self.raw if raw is None else raw,url)
        return continuous_first_party_vacancy(pg,{'url':url,'identity_verified':True,
            'retrieved_at':'2026-11-04T12:00:00Z',**rsp},self.data)

    def test_literal_rolling_deadline_and_job_contact_survive_without_an_invented_email_or_date(self):
        item=self.result()[0]
        self.assertIsNone(item['datePosted']);self.assertIsNone(item['validThrough'])
        self.assertEqual(item['_deadline_text'],'Løpende')
        self.assertEqual(item['_application_contact'],'tel:91746741')
        self.assertEqual(item['_application_url'],'https://example.test/om-oss/ledige-stillinger/elektriker')

    def test_negative_controls(self):
        variants=[self.raw+'<p>Stillingen er besatt</p>',self.raw.replace('</main>','<p>Åpen søknad</p></main>'),
            self.raw.replace('810034882','913884213'),
            self.raw.replace('Example Elektro AS','Example Elektro Bergen AS'),
            self.raw.replace('Søknadsfrist: Løpende','Søknadsfrist: 19.10'),
            self.raw.replace('Søknadsfrist: Løpende','Søknadsfrist: 19.10.2026'),
            self.raw.replace('Søknadsfrist: Løpende','Søknadsfrist: Løpende til 19.10.2026'),
            self.raw.replace('Søknadsfrist: Løpende',''),
            self.raw.replace('Vi i Example Elektro søker','Example Elektro søker'),
            self.raw.replace('Har du spørsmål og ønsker å vite mer rundt stillingen? Ta kontakt med daglig leder.','Kontakt oss for et pristilbud.'),
            self.raw.replace('tel:91746741','tel:92223333'),
            self.raw.replace('<a href="tel:91746741">91746741</a>','91746741'),
            self.raw.replace('Elektriker</h1>','Rørlegger</h1>'),
            self.raw.replace('Vi tilbyr:','Våre tjenester:'),
            self.raw.replace('Vi i Example Elektro søker nå','På vegne av vår kunde søker vi nå')]
        for raw in variants:
            with self.subTest(raw=raw):self.assertEqual(self.result(raw),[])
        self.assertEqual(self.result(url='https://example.test/news/elektriker'),[])
        self.assertEqual(self.result(delegated_from_verified_careers=True),[])
        self.assertEqual(self.result(identity_verified=False),[])


if __name__=='__main__':unittest.main()
