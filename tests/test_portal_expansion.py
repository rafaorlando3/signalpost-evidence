import copy,json,tempfile,unittest
from pathlib import Path
from agent import Page,digest
from portal_expansion import extra_postings,schema_item,detail_links

class PortalExpansionTests(unittest.TestCase):
    def fixture(self):
        data={'organisasjonsnummer':'810034882','navn':'EXAMPLE CARE AS'}
        parent=Page('<h1>Example Care AS</h1><p>Org.nr 810034882</p><a href="https://careers.example.test/jobs">Ledige stillinger</a>','https://example.test/')
        index=Page('<h1>Careers</h1>'+''.join('<a href="/jobs/'+str(n)+'-engineer">Engineer '+str(n)+'</a>' for n in range(1,9)),'https://careers.example.test/jobs')
        def rsp(pg):return {'url':pg.url,'status':'available','retrieved_at':'2026-11-03T12:00:00Z','text':pg.raw_html}
        ir={**rsp(index),'delegated_from_verified_careers':True,'delegated_from_url':parent.url}
        def detail(n,**updates):
            node={'@type':'JobPosting','title':'Engineer '+str(n),'datePosted':'2026-10-20','validThrough':'2026-11-30','hiringOrganization':{'name':data['navn']},'url':index.url+'/'+str(n)+'-engineer'};node.update(updates)
            return Page('<h1>Engineer '+str(n)+'</h1><script type="application/ld+json">'+json.dumps(node)+'</script>',node['url'])
        return data,parent,index,rsp,ir,detail
    def test_late_extension_preserves_first_two_and_visits_only_four_new_observed_details(self):
        d,p,i,r,ir,detail=self.fixture();known=[(p,r(p)),(i,ir),*[(detail(n),r(detail(n))) for n in [1,2]]]
        class F:
            requests=10;limit=20
            def __init__(self):self.urls=[]
            def get(self,u,**kw):self.requests+=1;self.urls.append(u);return r(detail(int(u.split('/')[-1].split('-')[0])))
        f=F();out,diagnostics=extra_postings([(p,r(p))],known,f,Page,d)
        self.assertEqual([x['item']['title'] for x in out],['Engineer '+str(n) for n in [3,4,5,6]])
        self.assertEqual(f.requests,14);self.assertEqual(diagnostics['unvisited_observed_details'],2)
        self.assertFalse(any('/1-engineer' in u or '/2-engineer' in u for u in f.urls))
    def test_existing_trailing_slash_alias_is_not_visited_again(self):
        d,p,i,r,ir,detail=self.fixture();pg=detail(1);alias=Page(pg.raw_html,pg.url+'/')
        class F:
            requests=19;limit=20
            def __init__(self):self.urls=[]
            def get(self,u,**kw):self.urls.append(u);self.requests+=1;return r(detail(2))
        f=F();out,diag=extra_postings([(p,r(p))],[(p,r(p)),(i,ir),(alias,r(alias))],f,Page,d)
        self.assertEqual(f.urls,[detail(2).url])
    def test_remaining_global_budget_wins_over_requested_extra_detail_count(self):
        d,p,i,r,ir,detail=self.fixture()
        class F:
            requests=19;limit=20
            def get(self,u,**kw):self.requests+=1;return r(detail(1))
        f=F();out,diagnostics=extra_postings([(p,r(p))],[(p,r(p)),(i,ir)],f,Page,d,max_details=99)
        self.assertEqual(f.requests,20);self.assertEqual(diagnostics['detail_attempts'],1)
        f.requests=20;out,diagnostics=extra_postings([(p,r(p))],[(p,r(p)),(i,ir)],f,Page,d);self.assertEqual(diagnostics['detail_attempts'],0)
    def test_allowance_is_granted_only_after_a_verified_observed_index(self):
        d,p,i,r,ir,detail=self.fixture()
        class F:
            requests=20;limit=20
            def get(self,u,**kw):self.requests+=1;return r(detail(int(u.split('/')[-1].split('-')[0])))
        f=F();out,diag=extra_postings([(p,r(p))],[(p,r(p)),(i,ir)],f,Page,d,request_allowance=99)
        self.assertEqual(f.requests,24);self.assertEqual(len(out),4);self.assertEqual(diag['additional_request_allowance'],4)
        f=F();out,diag=extra_postings([(p,r(p))],[],f,Page,d,request_allowance=4);self.assertEqual(f.limit,20);self.assertEqual(f.requests,20)
    def test_foreign_employer_identifier_modified_only_expired_and_spontaneous_rejected(self):
        for update in [{'hiringOrganization':{'name':'Example Care Bergen AS'}},{'hiringOrganization':{'name':'EXAMPLE CARE AS','identifier':'913884213'}},{'hiringOrganization':{'name':'EXAMPLE CARE AS','identifier':913884213}},{'datePosted':None,'dateModified':'2026-10-20'},{'validThrough':'2026-10-30'},{'datePosted':'2026-12-01'},{'title':'Open application'},{'title':'General application'},{'title':'Unsolicited application'}]:
            d,p,i,r,ir,detail=self.fixture();pg=detail(1,**update)
            if 'title' in update:pg=Page(pg.raw_html.replace('<h1>Engineer 1</h1>','<h1>'+update['title']+'</h1>'),pg.url)
            self.assertIsNone(schema_item(pg,r(pg),d,p,i,p,ir))
    def test_unnominated_index_foreign_links_actions_and_closed_detail_with_schema_rejected(self):
        d,p,i,r,ir,detail=self.fixture();pg=detail(1)
        self.assertIsNone(schema_item(pg,r(pg),d,Page('Other company',p.url),i,p,ir))
        i.links.extend([{'url':'https://other.test/jobs/99','text':'Engineer'},{'url':'https://careers.example.test/jobs/1-engineer/apply','text':'Apply'},{'url':'https://careers.example.test/jobs/9','text':'Open application'}])
        self.assertEqual(len(detail_links(i)),8)
        pg=Page(pg.raw_html+'<p>Fristen er utløpt</p>',pg.url);self.assertIsNone(schema_item(pg,r(pg),d,p,i,p,ir))
    def test_application_engineer_is_a_role_not_an_application_action(self):
        d,p,i,r,ir,detail=self.fixture()
        i.links.append({'url':i.url+'/9-application-engineer','text':'Application Engineer'})
        self.assertIn(i.url+'/9-application-engineer',detail_links(i))
        i.links.append({'url':i.url+'/apply','text':'Apply'})
        self.assertNotIn(i.url+'/apply',detail_links(i))
    def test_source_auditor_checks_the_same_chain_and_rejects_tampering(self):
        from audit import audit
        d,p,i,r,ir,detail=self.fixture();pg=detail(1);item=schema_item(pg,r(pg),d,p,i,p,ir);self.assertIsNotNone(item)
        with tempfile.TemporaryDirectory() as directory:
            records=[{'url':'https://data.brreg.no/enhetsregisteret/api/enheter/'+d['organisasjonsnummer'],'json':d,'text':json.dumps(d)},r(p),ir,r(pg)];evidence=[]
            for n,record in enumerate(records):
                record={**record,'status':'available','content_sha256':digest(record['text'].encode())};name=str(n)+'.json';Path(directory,name).write_text(json.dumps(record));evidence.append({'id':str(n),'snapshot_file':name,'content_sha256':record['content_sha256']})
            row={'organisation_number':d['organisasjonsnummer'],'claims':[{'field':'website.hiring','value':[item],'availability':'available','evidence_ids':[e['id'] for e in evidence]}],'evidence':evidence}
            result=audit([row],directory);self.assertTrue(result['passed']);self.assertEqual(result['counts']['linked_schema_portal_postings_checked'],1)
            item['date']='2026-09-01';self.assertFalse(audit([row],directory)['passed'])
    def test_vilect_increase_requires_verified_single_company_index(self):
        from vilect_careers import verified_index
        from test_vilect_careers import VilectCareersTests
        d,p,i,j,r=VilectCareersTests().fixtures();self.assertTrue(verified_index(d,p,i,p))
        d['navn']='Example Care Bergen AS';self.assertFalse(verified_index(d,p,i,p))
        p=Page(p.raw_html+'<p>The group employs 900 people in several countries.</p>',p.url);self.assertFalse(verified_index(d,p,i,p))
class ExplicitUnwrappedVacancy(unittest.TestCase):
    def test_lone_named_vacancy_h1_on_role_route_with_application_invitation_is_supported(self):
        from hiring_discovery import continuous_first_party_vacancy
        data={'organisasjonsnummer':'810034882','navn':'EXAMPLE CARE AS'}
        raw='<header><h1>Ledig stilling som utvikler</h1></header><p>Example Care AS lager løsninger. Vi ser etter deg som kan utvikle gode produkter. Vi forventer god erfaring. Send søknaden til: <a href="mailto:utvikler@example.test">utvikler@example.test</a></p><footer>Org.nr 810034882</footer>'
        for path,accepted in [('/jobb/utvikler',True),('/customers/utvikler',False),('/blog/utvikler',False)]:
            pg=Page(raw,'https://example.test'+path);response={'url':pg.url,'identity_verified':True,'retrieved_at':'2026-11-03T12:00:00Z'}
            result=continuous_first_party_vacancy(pg,response,data);self.assertEqual(bool(result),accepted)
            if result:self.assertIsNone(result[0]['datePosted']);self.assertIsNone(result[0]['validThrough'])
    def test_closed_spontaneous_foreign_number_and_no_application_are_withheld(self):
        from hiring_discovery import continuous_first_party_vacancy
        data={'organisasjonsnummer':'810034882','navn':'EXAMPLE CARE AS'}
        raw='<header><h1>Ledig stilling som utvikler</h1></header><p>Example Care AS lager løsninger. Vi ser etter deg som kan utvikle gode produkter. Vi forventer god erfaring. Send søknaden til: <a href="mailto:utvikler@example.test">utvikler@example.test</a></p><footer>Org.nr 810034882</footer>'
        for body in [raw+'<p>Stillingen er besatt</p>',raw+'<p>Åpen søknad</p>',raw.replace('810034882','913884213'),raw.replace('Send søknaden til:','Kontakt:'),raw.replace('Ledig stilling som utvikler','Ledig stilling hos oss')]:
            pg=Page(body,'https://example.test/jobb/utvikler');self.assertFalse(continuous_first_party_vacancy(pg,{'url':pg.url,'identity_verified':True,'retrieved_at':'2026-11-03T12:00:00Z'},data))
if __name__=='__main__':unittest.main()
