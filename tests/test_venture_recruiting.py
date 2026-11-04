import json,unittest
from agent import Page
from public_recruiting import parse_postings,separate_venture_recruitment
from test_public_recruiting import DATA,AD,ORG,rsp


class VentureRecruiting(unittest.TestCase):
    body=('Example Plant og en partner etablerer et nytt felleseid selskap som skal drifte en terminal. '
          'Nå søker vi en HR Manager som vil få en sentral rolle i etableringen av virksomheten. '
          'Du får ansvar for å bygge en ny organisasjon fra grunnen av.')

    def page(self,body=None):
        text=body if body is not None else self.body
        obj={'@type':'JobPosting','title':'HR Manager','url':AD,
             'datePosted':'2026-10-28','validThrough':'2026-11-22',
             'description':'<p>'+text+'</p>','hiringOrganization':{'name':DATA['navn']}}
        raw='<h1>HR Manager</h1><main><p>'+text+'</p></main><script type="application/ld+json">'+json.dumps(obj)+'</script><h2>Annonseinformasjon</h2><div>Org.nr. '+ORG+'</div><p>Rapporter annonse</p>'
        return Page(raw,AD),rsp(AD,raw),obj

    def test_parent_label_does_not_resolve_new_venture_hiring_entity(self):
        page,response,obj=self.page()
        self.assertTrue(separate_venture_recruitment(page,obj['description'],DATA))
        self.assertEqual(parse_postings(page,response,DATA,[]),[])

    def test_explicit_target_employment_resolves_ambiguity(self):
        page,response,obj=self.page(self.body+' Du blir ansatt hos Example Plant AS.')
        self.assertFalse(separate_venture_recruitment(page,obj['description'],DATA))
        self.assertEqual(len(parse_postings(page,response,DATA,[])),1)

    def test_joint_project_mention_or_inert_hidden_copy_does_not_trigger_veto(self):
        for body in ['Vi i Example Plant AS søker en HR Manager. Du bistår vårt joint venture i regionen.',
                     self.body.replace('et nytt felleseid selskap','en ny avdeling i vårt eget selskap')]:
            page,response,obj=self.page(body)
            self.assertFalse(separate_venture_recruitment(page,obj['description'],DATA))
            self.assertEqual(len(parse_postings(page,response,DATA,[])),1)
        page,response,obj=self.page()
        hidden=Page('<h1>HR Manager</h1><!--'+self.body+'-->',AD)
        self.assertFalse(separate_venture_recruitment(hidden,obj['description'],DATA))

    def test_another_company_contract_or_unrelated_legal_name_is_not_target_proof(self):
        page,response,obj=self.page(self.body+' Du blir ansatt hos Example Plant Bergen AS.')
        self.assertTrue(separate_venture_recruitment(page,obj['description'],DATA))
        self.assertEqual(parse_postings(page,response,DATA,[]),[])

    def test_nav_copy_cannot_restore_the_same_unresolved_venture_job(self):
        from test_public_recruiting import NAVPrimary
        response=NAVPrimary().source(adTextHtml='<p>'+self.body+'</p>')
        response['text']+='<main><p>'+self.body+'</p></main>'
        page=Page(response['text'],response['url'])
        self.assertEqual(parse_postings(page,response,DATA,[]),[])
        response=NAVPrimary().source(adTextHtml='<p>'+self.body+' Du blir ansatt hos Example Plant AS.</p>')
        response['text']+='<main><p>'+self.body+' Du blir ansatt hos Example Plant AS.</p></main>'
        page=Page(response['text'],response['url'])
        self.assertEqual(len(parse_postings(page,response,DATA,[])),1)


if __name__=='__main__':unittest.main()
