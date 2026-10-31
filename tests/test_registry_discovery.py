import unittest
from unittest.mock import patch
import tempfile
from agent import Page,corroborated_site,Fetcher,research,OFFICIAL
from registry_discovery import registry_candidates

ORG='810034882'
DATA={'organisasjonsnummer':ORG,'navn':'Example Business AS','hjemmeside':'https://old.test',
      'forretningsadresse':{'adresse':['Street 42'],'postnummer':'1234'},
      'postadresse':{'adresse':['Postboks 25'],'postnummer':'5678'}}


class RegistryDiscovery(unittest.TestCase):
    def test_alternatives_survive_obsolete_primary_and_are_deduplicated(self):
        data={**DATA,'epostadresse':'contact@new.test'}
        units=[{'overordnetEnhet':ORG,'hjemmeside':'https://workplace.test'},
               {'overordnetEnhet':'wrong','hjemmeside':'https://unrelated.test'}]
        self.assertEqual([x['origin'] for x in registry_candidates(ORG,data,units)],
                         ['entity_website','unique_workplace_website','email_domain'])
        data['epostadresse']='contact@old.test'
        self.assertEqual(len(registry_candidates(ORG,data,units)),2)

    def test_free_email_invalid_urls_and_conflicting_workplace_urls_not_used(self):
        data={**DATA,'hjemmeside':'https://secret:pass@old.test','epostadresse':'a@icloud.com'}
        units=[{'overordnetEnhet':ORG,'hjemmeside':'https://one.test'},
               {'overordnetEnhet':ORG,'hjemmeside':'https://two.test'}]
        self.assertEqual(registry_candidates(ORG,data,units),[])

    def test_postal_address_requires_declared_domain_name_and_exact_postcode(self):
        good=Page('Example Business, Postboks 25, 5678 Oslo','https://old.test')
        self.assertTrue(corroborated_site(DATA,good))
        self.assertFalse(corroborated_site(DATA,Page(good.text,'https://other.test')))
        self.assertFalse(corroborated_site(DATA,Page('Example Business Postboks 25 9999','https://old.test')))
        self.assertFalse(corroborated_site(DATA,Page('Different Business Postboks 25 5678','https://old.test')))
        self.assertFalse(corroborated_site({**DATA,'hjemmeside':None},good))

    def test_only_observed_registry_redirect_can_extend_domain_anchor(self):
        p=Page('Example Business, Street 42 1234','https://new.test')
        self.assertFalse(corroborated_site(DATA,p))
        self.assertTrue(corroborated_site(DATA,p,'new.test'))
        self.assertFalse(corroborated_site(DATA,p,'unrelated.test'))
        conflict=Page(p.text+' Org no 987654321','https://new.test')
        self.assertFalse(corroborated_site(DATA,conflict,'new.test'))

    def test_pipeline_falls_back_from_wrong_group_to_exact_email_domain(self):
        def get(url,**kwargs):
            r={'url':url,'requested_url':url,'status':'available','status_code':200,
               'retrieved_at':'2026-09-26T00:00:00Z','content_sha256':'fixture','text':''}
            if url==OFFICIAL+'/enhetsregisteret/api/enheter/'+ORG:r['json']={**DATA,'epostadresse':'contact@new.test'}
            elif 'regnskap/' in url:r['json']=[]
            elif '/roller' in url:r['json']={'rollegrupper':[]}
            elif 'underenheter?' in url:r['json']={'page':{'totalPages':0}}
            elif url.startswith('https://old.test'):r['text']='Org no 987654321'
            elif url.startswith('https://new.test'):r['text']='Org no '+ORG
            return r
        with tempfile.TemporaryDirectory() as d:
            f=Fetcher(d,replay=True)
            with patch.object(f,'get',side_effect=get): result=research({'organisation_number':ORG},f)
        c=next(c for c in result['claims'] if c['field']=='website.verified_url')
        self.assertEqual(c['value'],'https://new.test')
        self.assertEqual(c['source_pointer'],'explicit_org_number')

if __name__=='__main__':unittest.main()

class HeuristicLeads(unittest.TestCase):
    def test_dotted_initials_are_grouped_without_expanding_domain_guess_budget(self):
        from registry_discovery import name_domain_candidates
        self.assertEqual(name_domain_candidates({'navn':'A.B. Example AS'}),
                         ['https://abexample.no/','https://ab-example.no/'])
        self.assertEqual(name_domain_candidates({'navn':'A Example AS'}),
                         ['https://aexample.no/','https://a-example.no/'])
    def test_domains_are_generic_bounded_and_never_identity_proof(self):
        from registry_discovery import name_domain_candidates
        self.assertEqual(name_domain_candidates({'navn':'ÆØÅ Industri AS'}),['https://aeoaindustri.no/','https://aeoa-industri.no/'])
        self.assertEqual(name_domain_candidates({'navn':'Somebody Invest AS'}),[])
        self.assertEqual(name_domain_candidates({'navn':'ABC AS'}),[])
        self.assertEqual(name_domain_candidates({'navn':'Example AS'}),['https://example.no/','https://example.com/'])

    def test_unknown_domain_requires_own_legal_footer_brand_and_exact_address(self):
        from agent import legal_footer_identity
        data={'navn':'Example Business AS','organisasjonsnummer':ORG,'forretningsadresse':{'adresse':['Road 12'],'postnummer':'1234'}}
        good='<title>Example Business</title><footer>Example Business AS Road 12, 1234 Oslo</footer>'
        self.assertTrue(legal_footer_identity(data,Page(good,'https://new.test/')))
        self.assertFalse(legal_footer_identity(data,Page(good,'https://new.test/customers/example')))
        self.assertFalse(legal_footer_identity(data,Page(good.replace('Example Business</title>','Other Group</title>'),'https://new.test/')))
        self.assertFalse(legal_footer_identity(data,Page(good.replace('1234','9999'),'https://new.test/')))
        self.assertFalse(legal_footer_identity(data,Page(good.replace('<footer>','<div>').replace('</footer>','</div>'),'https://new.test/')))
