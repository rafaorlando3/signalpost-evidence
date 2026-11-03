import json,unittest
from agent import Page
from nuu_careers import card_leads,accepted_item,route_supported

class NuuCareersTests(unittest.TestCase):
    def fixtures(self):
        host='careers.example.no';company={'id':17,'name':'Example School','sub_companies':None,'group_settings':None}
        def record(url,b):return {'u':'https://api.nuu.no'+url,'s':200,'b':b}
        domain=record('/companies/domain/'+host+'/',company)
        cards=record('/companies/17/job-folders/',[{'id':33,'company':17,'title':'We seek two teachers'},{'id':34,'company':17,'title':'Åpen søknad'}])
        def page(records,url,body=''):
            return Page('<title>We seek two teachers | Example School</title>'+body+'<script type="application/json">'+json.dumps(dict(enumerate(records)))+'</script><script src="main-ABC.js"></script>',url)
        index=page([domain,cards],'https://'+host,'<h1>We seek two teachers</h1>')
        job={'id':33,'company':{'id':17,'name':'Example School'},'title':'We seek two teachers','is_published':True,'internal':False,'external':True,'expiration_date':'2026-11-20','translations':{'no':{'title':'We seek two teachers','description':'<p>Example School seeks two teachers for its new educational programme with a complete public job description.</p>'}}}
        detail=page([domain,record('/jobs/33/',job)],'https://'+host+'/stilling/33')
        parent=Page('<a href="https://'+host+'">Ledige stillinger</a>','https://example.no/careers/')
        script={'url':'https://'+host+'/main-ABC.js','status':'available','text':'routes=[{path:"stilling/:jobId",component:Example}]'}
        rsp={'url':detail.url,'status':'available','retrieved_at':'2026-11-03T12:00:00Z'};data={'organisasjonsnummer':'810034882','navn':'EXAMPLE SCHOOL AS'}
        return data,parent,index,detail,script,rsp,company,job,page,domain,record
    def test_card_id_and_observed_route_are_only_leads(self):
        d,p,i,*_=self.fixtures();leads=card_leads(i);self.assertEqual([c['id'] for c in leads[0]['cards']],[33]);self.assertTrue(route_supported('x={path:"stilling/:jobId"}'));self.assertFalse(route_supported('stilling/33'))
    def test_current_single_company_ad_keeps_publication_unknown(self):
        d,p,i,page,s,r,*_=self.fixtures();out=accepted_item(page,r,d,p,i,s)
        self.assertIsNotNone(out);self.assertIsNone(out['date']);self.assertEqual(out['valid_through'],'2026-11-20');self.assertEqual(out['employer_as_published'],'Example School')
    def test_exact_legal_stem_required(self):
        d,p,i,page,s,r,*_=self.fixtures();d['navn']='EXAMPLE SCHOOL BERGEN AS';self.assertIsNone(accepted_item(page,r,d,p,i,s))
    def test_group_or_mismatched_company_is_rejected(self):
        d,p,i,page,s,r,c,job,make,domain,record=self.fixtures();c['sub_companies']=[{'id':18}]
        bad=make([record('/companies/domain/careers.example.no/',c),record('/jobs/33/',job)],page.url)
        self.assertIsNone(accepted_item(bad,r,d,p,i,s))
    def test_expired_internal_unpublished_and_spontaneous_are_rejected(self):
        for changes in [{'expiration_date':'2026-10-01'},{'is_published':False},{'internal':True},{'external':False},{'title':'Åpen søknad'}]:
            with self.subTest(changes=changes):
                d,p,i,page,s,r,c,job,make,domain,record=self.fixtures();job.update(changes);bad=make([domain,record('/jobs/33/',job)],page.url)
                self.assertIsNone(accepted_item(bad,r,d,p,i,s))
    def test_source_auditor_reconstructs_the_nuu_item_and_detects_tampering(self):
        import copy,tempfile
        from pathlib import Path
        from agent import digest
        from audit import audit
        d,p,i,page,s,r,*_=self.fixtures();item=accepted_item(page,r,d,p,i,s)
        with tempfile.TemporaryDirectory() as tmp:
            responses=[{'url':'https://data.brreg.no/enhetsregisteret/api/enheter/'+d['organisasjonsnummer'],'json':d,'text':json.dumps(d)},
                *[{'url':pg.url,'text':pg.raw_html} for pg in [p,i,page]],s]
            evidence=[]
            for n,rsp in enumerate(responses):
                rsp={**rsp,'status':'available','status_code':200,'retrieved_at':'2026-11-03T12:00:00Z','content_sha256':digest(rsp['text'].encode())}
                name=str(n)+'.json';Path(tmp,name).write_text(json.dumps(rsp));evidence.append({'id':str(n),'snapshot_file':name,'content_sha256':rsp['content_sha256']})
            row={'organisation_number':d['organisasjonsnummer'],'claims':[{'field':'website.hiring','availability':'available','value':[item],'evidence_ids':[e['id'] for e in evidence]}],'evidence':evidence}
            result=audit([row],tmp);self.assertTrue(result['passed']);self.assertEqual(result['counts']['dedicated_nuu_postings_checked'],1)
            broken=copy.deepcopy(row);broken['claims'][0]['value'][0]['valid_through']='2027-01-01'
            self.assertFalse(audit([broken],tmp)['passed'])

    def test_unlinked_foreign_portal_and_missing_route_are_rejected(self):
        d,p,i,page,s,r,*_=self.fixtures();self.assertIsNone(accepted_item(page,r,d,Page('<p>Jobs</p>',p.url),i,s));self.assertIsNone(accepted_item(page,r,d,p,i,{**s,'text':'unsupported route'}))
        self.assertIsNone(accepted_item(page,r,d,Page('<a href="https://careers.example.no/">Jobs</a>','https://other.no/'),i,s))

if __name__=='__main__':unittest.main()
