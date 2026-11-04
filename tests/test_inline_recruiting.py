import copy
import unittest
from agent import Page
from inline_recruiting import candidates, role_key


class InlineRecruiting(unittest.TestCase):
    data = {'organisasjonsnummer':'911605287', 'navn':'ACME NORGE AS'}

    def page(self, text, url='https://www.acme.no/karriere', **extra):
        return Page(text, url), {'url':url, 'text':text, 'retrieved_at':'2026-11-04T09:00:00Z',
                                 'status':'available', 'status_code':200, 'identity_verified':True, **extra}

    def job(self, title='Account Executive', body=None):
        body = body or ('Vi i Acme Norge søker en ny kollega. Hva du får: et fagmiljø og opplæring. '
            'Dine viktigste oppgaver er å kontakte kunder og følge opp møter og kontrakter. '
            'Vi ønsker erfaring med salg og gode kommunikasjonsevner. '
            'Send en søknad med CV til jobs@rekruttering.example. Vi vurderer søknader fortløpende.')
        return '<h5>'+title+'</h5><p>'+body+'</p>'

    def bundle(self, content=None):
        raw = ('<main><h1>Karriere</h1><h2>Utlyste stillinger nå</h2>'+(content or self.job())+
               '</main><footer><a href="/personvern">Personvern</a></footer>')
        return [self.page(raw), self.page('<main>Behandlingsansvarlig er ACME NORGE AS '
                '(Org. nr. 911 605 287).</main>', 'https://www.acme.no/personvern')]

    def test_own_current_invitation_retains_unknown_dates_and_legal_source(self):
        result = candidates(self.bundle(), self.data)
        self.assertEqual(len(result), 1)
        item = result[0]['item']
        self.assertEqual(item['title'], 'Account Executive')
        self.assertIsNone(item['date'])
        self.assertIsNone(item['valid_through'])
        self.assertEqual(item['employer_binding']['company_identity_source'], 'https://www.acme.no/personvern')
        self.assertNotIn('application_contact', item)

    def test_two_roles_on_one_page_are_distinct(self):
        result = candidates(self.bundle(self.job()+self.job('Senior Developer')), self.data)
        self.assertEqual([r['item']['title'] for r in result], ['Account Executive','Senior Developer'])
        self.assertEqual(len({role_key(r['item']) for r in result}), 2)

    def test_spontaneous_section_does_not_contaminate_prior_specific_role(self):
        result = candidates(self.bundle(self.job()+'<h2>Åpne søknader</h2><p>Send en åpen søknad.</p>'), self.data)
        self.assertEqual(len(result), 1)

    def test_wrong_or_weak_legal_page_never_establishes_owner(self):
        for text in ['ACME NORGE AS Org. nr. 912345678', 'Acme Norge, org. nr. 911605287',
                     'Other Group AS Org. nr. 911605287']:
            with self.subTest(text=text):
                pages=self.bundle();pages[1]=self.page('<main>'+text+'</main>', 'https://www.acme.no/personvern')
                self.assertEqual(candidates(pages, self.data), [])

    def test_registry_domain_or_unlinked_legal_page_is_insufficient(self):
        pages=self.bundle();pages[0]=self.page(pages[0][0].raw_html.replace('href="/personvern"','href="/kontakt"'))
        self.assertEqual(candidates(pages, self.data), [])

    def test_foreign_job_page_number_vetoes_privacy_owner(self):
        pages=self.bundle();pages[0]=self.page(pages[0][0].raw_html+'<p>Org. nr. 912 048 535</p>')
        self.assertEqual(candidates(pages, self.data), [])

    def test_client_spontaneous_closed_or_past_role_is_not_published(self):
        for bad in ['Vi søker for vår kunde.', 'Dette er en åpen søknad.', 'Stillingen er besatt.',
                    'Søknadsfrist: 01.11.2026', 'Søknadsfrist: 19.10']:
            with self.subTest(bad=bad):
                self.assertEqual(candidates(self.bundle(self.job().replace('</p>',bad+'</p>')), self.data), [])

    def test_literal_unexpired_role_deadline_is_separate_from_publication(self):
        result=candidates(self.bundle(self.job().replace('</p>','Søknadsfrist: 20.11.2026</p>')), self.data)
        self.assertEqual(result[0]['item']['valid_through'], '2026-11-20')
        self.assertIsNone(result[0]['item']['date'])

    def test_generic_role_hours_and_product_headings_are_not_vacancies(self):
        for title in ['LEDIG STILLING - HELTID/DELTID', 'Åpen søknad', 'Våre produkter', 'Kvalifikasjoner']:
            with self.subTest(title=title):
                self.assertEqual(candidates(self.bundle(self.job(title)), self.data), [])

    def test_global_invitation_cannot_fill_a_role_without_an_invitation(self):
        pages=self.bundle(self.job().replace('Send en søknad med CV til jobs@rekruttering.example.', 'Ta gjerne kontakt.'))
        pages[0]=self.page(pages[0][0].raw_html+'<footer>Send søknad med CV til oss.</footer>')
        self.assertEqual(candidates(pages, self.data), [])

    def test_no_company_named_in_the_role_no_acceptance(self):
        self.assertEqual(candidates(self.bundle(self.job().replace('Acme Norge', 'Annet Selskap')), self.data), [])

    def test_own_legal_chain_does_not_promote_an_external_portal(self):
        pages=self.bundle();pages[0][1]['delegated_from_verified_careers']=True
        self.assertEqual(candidates(pages, self.data), [])

    def test_unverified_job_or_legal_source_fails_closed(self):
        for i in [0,1]:
            pages=self.bundle();pages[i][1]['identity_verified']=False
            self.assertEqual(candidates(pages, self.data), [])

    def test_unavailable_or_non_success_sources_are_not_factual_evidence(self):
        for i in [0,1]:
            for field,value in [('status','blocked'),('status_code',403)]:
                pages=self.bundle();pages[i][1][field]=value
                self.assertEqual(candidates(pages,self.data),[])

    def test_sidebar_and_agency_roles_are_excluded(self):
        for wrapper in ['aside','footer','nav','form']:
            with self.subTest(wrapper=wrapper):
                self.assertEqual(candidates(self.bundle('<'+wrapper+'>'+self.job()+'</'+wrapper+'>'), self.data), [])
        self.assertEqual(candidates(self.bundle('<section class="customer">'+self.job()+'</section>'), self.data), [])

    def test_legacy_and_plural_title_aliases_are_one_role(self):
        pages=self.bundle();alias=self.page(pages[0][0].raw_html.replace('Account Executive','Account Executives'),
                                          'https://www.acme.no/team-acme')
        result=candidates(pages+[alias], self.data)
        self.assertEqual(len(result), 1)

    def test_unscoped_bio_without_current_openings_cue_is_not_a_role(self):
        pages=self.bundle();pages[0]=self.page(pages[0][0].raw_html.replace('Utlyste stillinger nå', 'Våre ansatte'))
        self.assertEqual(candidates(pages, self.data), [])

    def test_no_network_or_source_mutation(self):
        pages=self.bundle();before=copy.deepcopy([r for _,r in pages]);candidates(pages, self.data)
        self.assertEqual([r for _,r in pages], before)
