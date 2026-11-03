import copy,json,tempfile,unittest
from pathlib import Path
from agent import Page,digest
from vilect_careers import accepted_item,position_key,labelled_fields
from public_recruiting import job_key
class VilectCareersTests(unittest.TestCase):
    def fixtures(self):
        data={'organisasjonsnummer':'810034882','navn':'EXAMPLE CARE AS'}
        parent=Page('<title>Example Care</title><p>Org.nr 810034882</p><a href="https://app.vilect.com/brands/18/jobs/">Ledige stillinger</a>','https://example.no/careers/')
        index=Page('<h1>Ledige stillinger – Example Care</h1><a href="https://example.no/">Our homepage</a><a href="/positions/33">Assistant</a>','https://app.vilect.com/brands/18/jobs/')
        fields=''.join('<p><span class="has-text-weight-bold">'+k+'</span><br><span class="has-word-wrap">'+v+'</span></p>' for k,v in [('Stillingstittel','Assistant'),('Arbeidsgiver','Example Care'),('Arbeidssted','Oslo'),('Søknadsfrist:','Snarest')])
        body='<h1>We seek an assistant</h1>'+fields+'<a href="#apply-form">Søk på denne stillingen</a>'
        meta={'og:url':'https://recruiting.done.ai/positions/33','og:type':'article','article:section':'Ledige stillinger','article:published_time':'2026-10-12T10:00:00Z','article:expiration_time':'2026-11-20'}
        raw=''.join('<meta property="'+k+'" content="'+v+'">' for k,v in meta.items())+body
        detail=Page(raw,'https://app.vilect.com/positions/33');rsp={'url':detail.url,'status':'available','retrieved_at':'2026-11-03T12:00:00Z'}
        return data,parent,index,detail,rsp
    def test_literal_job_fields_date_and_expiration_are_distinct(self):
        d,p,i,j,r=self.fixtures();out=accepted_item(j,r,d,p,i,p)
        self.assertIsNotNone(out);self.assertEqual(out['employer_as_published'],'Example Care');self.assertEqual(out['date'],'2026-10-12T10:00:00Z');self.assertIsNone(out['valid_through']);self.assertEqual(out['deadline_text'],'Snarest');self.assertEqual(out['listing_expires_at'],'2026-11-20')
    def test_expired_modified_only_future_closed_and_spontaneous_not_counted(self):
        for change in ['expired','modified','future','closed','spontaneous','partial-deadline']:
            with self.subTest(change=change):
                d,p,i,j,r=self.fixtures();raw=j.raw_html
                if change=='expired':raw=raw.replace('2026-11-20','2026-10-01')
                if change=='modified':raw=raw.replace('article:published_time','article:modified_time')
                if change=='future':raw=raw.replace('2026-10-12T10:00:00Z','2026-12-12T10:00:00Z')
                if change=='closed':raw=raw.replace('Snarest','Annonsen er utløpt')
                if change=='spontaneous':raw=raw.replace('Assistant','Åpen søknad')
                if change=='partial-deadline':raw=raw.replace('Snarest','19.10')
                self.assertIsNone(accepted_item(Page(raw,j.url),r,d,p,i,p))
    def test_unlinked_foreign_employer_number_and_missing_apply_are_rejected(self):
        for change in ['unlinked','foreign-employer','foreign-number','no-apply','different-canonical','no-backlink','group']:
            with self.subTest(change=change):
                d,p,i,j,r=self.fixtures();identity=p
                if change=='unlinked':p=Page('Jobs',p.url)
                if change=='foreign-employer':d['navn']='EXAMPLE CARE BERGEN AS'
                if change=='foreign-number':identity=Page('Org.nr 913 884 213',p.url)
                if change=='no-apply':j=Page(j.raw_html.replace('Søk på denne stillingen','Contact us'),j.url)
                if change=='different-canonical':j.meta['og:url']='https://recruiting.done.ai/positions/34'
                if change=='no-backlink':i=Page(i.raw_html.replace('https://example.no/','https://other.no/'),i.url)
                if change=='group':p=Page(p.raw_html+'<p>The group employs 900 people in several countries.</p>',p.url)
                self.assertIsNone(accepted_item(j,r,d,p,i,identity))
    def test_duplicate_fields_are_not_an_employer_statement(self):
        d,p,i,j,r=self.fixtures();bad=Page(j.raw_html+'<p><span class="has-text-weight-bold">Arbeidsgiver</span><span class="has-word-wrap">Other AS</span></p>',j.url)
        self.assertFalse(labelled_fields(bad));self.assertIsNone(accepted_item(bad,r,d,p,i,p))
    def test_aliases_and_nav_explicit_primary_url_deduplicate(self):
        self.assertEqual(job_key({'url':'https://app.vilect.com/positions/33?utm_source=x'}),job_key({'url':'https://recruiting.done.ai/positions/33'}))
        self.assertEqual(job_key({'url':'https://arbeidsplassen.nav.no/stillinger/stilling/example','source_posting_url':'https://app.vilect.com/positions/33'}),'vilect:33')
        self.assertIsNone(position_key('https://app.vilect.com/positions/33/apply'))
        self.assertIsNone(position_key('https://app.vilect.com:invalid/positions/33'))
    def test_legal_identity_audit_keeps_exact_entry_with_slash_alias(self):
        from audit import audit
        from legal_name_identity import legal_name_identity
        data={'organisasjonsnummer':'810034882','navn':'EXAMPLE CARE AS'}
        raw='<title>Example Care</title><p>Example Care AS is a Norwegian provider of care services.</p>'
        entry=Page(raw,'https://example.no');alias=Page(raw,'https://example.no/')
        proof=legal_name_identity(data,[(entry,{}),(alias,{})],lambda p:True)
        with tempfile.TemporaryDirectory() as directory:
            evidence=[]
            sources=[{'url':'https://data.brreg.no/enhetsregisteret/api/enheter/'+data['organisasjonsnummer'],'json':data,'text':json.dumps(data)},*[{'url':pg.url,'text':pg.raw_html} for pg in [alias,entry]]]
            for n,source in enumerate(sources):
                source={**source,'status':'available','content_sha256':digest(source['text'].encode())};name=str(n)+'.json';Path(directory,name).write_text(json.dumps(source));evidence.append({'id':str(n),'snapshot_file':name,'content_sha256':source['content_sha256']})
            row={'organisation_number':data['organisasjonsnummer'],'claims':[{'field':'website.verified_url','value':entry.url,'availability':'available','source_pointer':'linked_first_party_legal_name','identity_support':proof,'evidence_ids':[e['id'] for e in evidence]}],'evidence':evidence}
            self.assertTrue(audit([row],directory)['passed'])
    def test_audit_reconstructs_full_company_source_chain_and_detects_tampering(self):
        from audit import audit
        d,p,i,j,r=self.fixtures();item=accepted_item(j,r,d,p,i,p)
        with tempfile.TemporaryDirectory() as directory:
            sources=[{'url':'https://data.brreg.no/enhetsregisteret/api/enheter/'+d['organisasjonsnummer'],'json':d,'text':json.dumps(d)},*[{'url':pg.url,'text':pg.raw_html} for pg in [p,i,j]]];evidence=[]
            for n,s in enumerate(sources):
                s={**s,'status':'available','status_code':200,'retrieved_at':r['retrieved_at'],'content_sha256':digest(s['text'].encode())};name=str(n)+'.json';Path(directory,name).write_text(json.dumps(s));evidence.append({'id':str(n),'snapshot_file':name,'content_sha256':s['content_sha256']})
            row={'organisation_number':d['organisasjonsnummer'],'claims':[{'field':'website.hiring','availability':'available','value':[item],'evidence_ids':[e['id'] for e in evidence]}],'evidence':evidence}
            result=audit([row],directory);self.assertTrue(result['passed']);self.assertEqual(result['counts']['vilect_company_postings_checked'],1)
            row['claims'][0]['value'][0]['date']='2026-01-01';self.assertFalse(audit([row],directory)['passed'])
if __name__=='__main__':unittest.main()
