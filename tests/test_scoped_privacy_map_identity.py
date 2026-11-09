import copy,json,tempfile,unittest
from pathlib import Path
from agent import Page,digest
from audit import audit
from legal_name_identity import legal_name_identity
from contact_map_identity import contact_map_identity,contact_map_records

class ScopedPrivacyMapIdentity(unittest.TestCase):
    def data(self):return {'navn':'EXAMPLE WORKS AS','organisasjonsnummer':'810034882','hjemmeside':'www.example.test','forretningsadresse':{'adresse':['Road 12'],'postnummer':'1234'}}
    def privacy(self,body=None):
        root=Page('<title>Example Works</title><a href="/personvernerklaering/">Personvern</a>','https://example.test/')
        text=body or '<p>Denne personvernerklæringen forteller om hvordan Example Works AS samler inn og bruker personopplysninger.</p><p>Vi behandler opplysninger på www.example.test.</p>'
        privacy=Page('<main>'+text+'</main>','https://example.test/personvernerklaering/')
        return [(root,{'url':root.url}),(privacy,{'url':privacy.url})]
    def test_exact_privacy_self_collector_and_literal_host_bind_site(self):
        proof=legal_name_identity(self.data(),self.privacy(),lambda p:True)
        self.assertTrue(proof);self.assertEqual(proof['source_url'],'https://example.test/personvernerklaering/')
        self.assertIn('Example Works AS',proof['self_identification']);self.assertEqual(len(proof['links']),1)
    def test_vendor_different_collector_foreign_host_and_conflict_never_bind(self):
        for body in ['<p>Example Works AS er leverandør av markedsføringstjenester på www.example.test.</p>',
                     '<p>Denne personvernerklæringen forteller om hvordan Parent Group AS samler inn og bruker personopplysninger.</p><p>Example Works AS er leverandør på www.example.test.</p>',
                     '<p>Denne personvernerklæringen forteller om hvordan Example Works AS samler inn og bruker personopplysninger på www.foreign.test.</p>']:
            self.assertIsNone(legal_name_identity(self.data(),self.privacy(body),lambda p:True))
        self.assertIsNone(legal_name_identity(self.data(),self.privacy(),lambda p:False))
    def maps(self,markers=None,host='example.test',brand='Example Works AS',target=True):
        root=Page('<title>'+brand+'</title><a href="/contact">Contact</a>','https://'+host+'/')
        records=markers or [{'title':'Other Subsidiary AS','html':'Other Subsidiary AS<br>Wrong road 99<br>9876 City'}, {'title':'EXAMPLE WORKS AS','html':'<strong>Example Works AS</strong><br>Road 12<br>N-1234 City'}]
        config=json.dumps({'options':{},'markers':records})
        body=('<div id="map42"></div>' if target else '')+"<script>eds1_11(function($){$('#map42').data('mapObject',new edMap_1($('#map42')[0], "+config+"));});</script>"
        contact=Page(body,'https://'+host+'/contact')
        return [(root,{'url':root.url}),(contact,{'url':contact.url})]
    def test_contact_map_selects_one_exact_legal_record_not_other_offices(self):
        proof=contact_map_identity(self.data(),self.maps(),lambda p:True)
        self.assertTrue(proof);self.assertEqual(proof['marker']['json_pointer'],'/markers/1')
        self.assertEqual(proof['registered_street'],'Road 12');self.assertNotIn('Other Subsidiary',proof['marker']['text'])
    def test_map_requires_declared_host_full_brand_marker_address_and_dom(self):
        for pages in [self.maps(host='foreign.test'),self.maps(brand='Parent Group'),self.maps(target=False),
                      self.maps([{'title':'EXAMPLE WORKS AS','html':'Example Works AS Road 12 9999 City'}]),
                      self.maps([{'title':'EXAMPLE WORKS AS','html':'Example Works AS Wrong road 12 1234 City'}]),
                      self.maps([{'title':'Other Subsidiary AS','html':'Example Works AS Road 12 1234 City'}])]:
            self.assertIsNone(contact_map_identity(self.data(),pages,lambda p:True))
        self.assertIsNone(contact_map_identity(self.data(),self.maps(),lambda p:False))
    def test_same_values_in_unrelated_script_are_not_map_proof(self):
        page=Page('<div id="map42"></div><script>var unrelated='+json.dumps({'options':{},'markers':[{'title':'EXAMPLE WORKS AS','html':'Example Works AS Road 12 1234 City'}]})+';</script>','https://example.test/contact')
        self.assertEqual(contact_map_records(page),[])
    def test_record_name_and_address_cannot_be_joined_across_markers(self):
        pages=self.maps([{'title':'EXAMPLE WORKS AS','html':'Example Works AS Wrong road 22 9999 City'}, {'title':'Other AS','html':'Other AS Road 12 1234 City'}])
        self.assertIsNone(contact_map_identity(self.data(),pages,lambda p:True))

    def test_explicit_conflicting_number_inside_marker_overrides_name_and_address(self):
        pages=self.maps([{'title':'EXAMPLE WORKS AS','html':'Example Works AS<br>Road 12<br>1234 City<br>Org.nr. 974 761 076'}])
        self.assertIsNone(contact_map_identity(self.data(),pages,lambda p:True))

    def test_literal_host_boundary_allows_sentence_stop_but_rejects_foreign_suffix_and_email(self):
        good=self.privacy()
        self.assertIsNotNone(legal_name_identity(self.data(),good,lambda p:True))
        for mention in ['www.example.test.foreign.test','office@example.test']:
            body='<p>Denne personvernerklæringen forteller om hvordan Example Works AS samler inn og bruker personopplysninger.</p><p>'+mention+'</p>'
            self.assertIsNone(legal_name_identity(self.data(),self.privacy(body),lambda p:True))

    def _write_snapshot(self,folder,eid,url,text=None,payload=None):
        raw=json.dumps(payload,ensure_ascii=False) if payload is not None else (text or '')
        sha=digest(raw.encode())
        snap={'id':eid,'url':url,'content_sha256':sha}
        if payload is not None:snap['json']=payload
        else:snap['text']=raw
        name=f'{eid}.json'
        (Path(folder)/name).write_text(json.dumps(snap,ensure_ascii=False))
        ev={'id':eid,'url':url,'snapshot_file':name,'content_sha256':sha}
        if payload is None:ev['retained_text_sha256']=sha
        return ev

    def _audit_map_fixture(self,folder,root_extra='',contact_extra='',evidence_ids=None):
        reg=self.data()
        pages=self.maps()
        root_html=pages[0][0].raw_html+root_extra
        contact_html=pages[1][0].raw_html+contact_extra
        bundles=[(Page(root_html,pages[0][0].url),{'url':pages[0][0].url}),(Page(contact_html,pages[1][0].url),{'url':pages[1][0].url})]
        proof=contact_map_identity(reg,bundles,lambda p:True)
        ev_reg=self._write_snapshot(folder,'src_01_brreg','https://data.brreg.no/enhetsregisteret/api/enheter/810034882',payload=reg)
        ev_root=self._write_snapshot(folder,'src_03_root',pages[0][0].url,text=root_html)
        ev_contact=self._write_snapshot(folder,'src_04_contact',pages[1][0].url,text=contact_html)
        eids=evidence_ids if evidence_ids is not None else ['src_04_contact','src_01_brreg','src_03_root']
        row={
            'organisation_number':reg['organisasjonsnummer'],
            'evidence':[ev_reg,ev_root,ev_contact],
            'claims':[{
                'field':'website.verified_url',
                'availability':'available',
                'value':proof['entry_url'],
                'source_pointer':'registered_domain_exact_legal_contact_map',
                'evidence_ids':list(eids),
                'identity_support':copy.deepcopy(proof),
            }],
        }
        return row,proof

    def test_audit_reconstructs_contact_map_identity_from_retained_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            row,_=self._audit_map_fixture(tmp)
            res=audit([row],tmp)
            self.assertTrue(res['passed'],res['errors'])
            self.assertEqual(res['counts'].get('contact_map_identity_proofs_checked'),1)

    def test_audit_rejects_tampered_marker_address_pointer_and_wrong_marker_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            base,_=self._audit_map_fixture(tmp)
            mutations=[
                lambda r:r['claims'][0]['identity_support']['marker'].__setitem__('literal_html','<strong>Example Works AS</strong><br>Road 99<br>N-1234 City'),
                lambda r:r['claims'][0]['identity_support']['marker'].__setitem__('text','Example Works AS Road 99 N-1234 City'),
                lambda r:r['claims'][0]['identity_support']['marker'].__setitem__('json_pointer','/markers/0'),
                lambda r:r['claims'][0]['identity_support']['marker'].__setitem__('map_container_id','map99'),
                lambda r:r['claims'][0]['identity_support']['marker'].__setitem__('script_index',9),
                lambda r:r['claims'][0]['identity_support']['marker'].__setitem__('title','Other Subsidiary AS'),
                lambda r:r['claims'][0]['identity_support'].__setitem__('registered_street','Wrong road 99'),
                lambda r:r['claims'][0]['identity_support'].__setitem__('registered_postcode','9876'),
                lambda r:r['claims'][0]['identity_support']['literal_spans'][0].__setitem__('end',5),
                lambda r:r['claims'][0]['identity_support'].__setitem__('links',[]),
                lambda r:r['claims'][0].__setitem__('value','https://foreign.test/'),
            ]
            for mutate in mutations:
                candidate=copy.deepcopy(base)
                mutate(candidate)
                res=audit([candidate],tmp)
                self.assertFalse(res['passed'])
                self.assertIn([base['organisation_number'],'contact-map legal identity proof not reproduced from retained first-party pages and registry'],res['errors'])

    def test_audit_rejects_missing_contact_page_root_page_or_registry_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            for eids in [['src_01_brreg','src_03_root'],['src_04_contact','src_01_brreg'],['src_04_contact','src_03_root']]:
                row,_=self._audit_map_fixture(tmp,evidence_ids=eids)
                res=audit([row],tmp)
                self.assertFalse(res['passed'])
            row_no_support,_=self._audit_map_fixture(tmp)
            row_no_support['claims'][0]['identity_support']=None
            self.assertFalse(audit([row_no_support],tmp)['passed'])

    def test_audit_rejects_foreign_operator_or_conflicting_org_on_retained_pages(self):
        foreign_footer='<footer><p>© 2026 Foreign Operator AS, Org.nr. 974 761 076</p></footer>'
        with tempfile.TemporaryDirectory() as tmp:
            row_root,_=self._audit_map_fixture(tmp,root_extra=foreign_footer)
            self.assertFalse(audit([row_root],tmp)['passed'])
            row_contact,_=self._audit_map_fixture(tmp,contact_extra=foreign_footer)
            self.assertFalse(audit([row_contact],tmp)['passed'])

    def test_audit_preserves_generic_literal_spans_and_legal_name_branches(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg=self.data()
            priv_pages=self.privacy()
            priv_proof=legal_name_identity(reg,priv_pages,lambda p:True)
            ev_reg=self._write_snapshot(tmp,'src_reg','https://data.brreg.no/enhetsregisteret/api/enheter/810034882',payload=reg)
            ev_root=self._write_snapshot(tmp,'src_root',priv_pages[0][0].url,text=priv_pages[0][0].raw_html)
            ev_priv=self._write_snapshot(tmp,'src_priv',priv_pages[1][0].url,text=priv_pages[1][0].raw_html)
            row={
                'organisation_number':reg['organisasjonsnummer'],
                'evidence':[ev_reg,ev_root,ev_priv],
                'claims':[
                    {
                        'field':'website.verified_url',
                        'availability':'available',
                        'value':priv_proof['entry_url'],
                        'source_pointer':'linked_first_party_legal_name',
                        'evidence_ids':['src_priv','src_reg','src_root'],
                        'identity_support':priv_proof,
                    },
                    {
                        'field':'website.verified_url',
                        'availability':'available',
                        'value':priv_pages[0][0].url,
                        'source_pointer':'registered_domain_exact_legal_name',
                        'evidence_ids':['src_root'],
                        'identity_support':{'literal_spans':[{'start':0,'end':13,'text':'Example Works'}]},
                    },
                ],
            }
            res=audit([row],tmp)
            self.assertTrue(res['passed'],res['errors'])
            self.assertEqual(res['counts'].get('first_party_legal_name_proofs_checked'),1)
            self.assertEqual(res['counts'].get('literal_identity_spans_checked'),1)
            bad=copy.deepcopy(row)
            bad['claims'][1]['identity_support']['literal_spans'][0]['text']='Tampered Text'
            res_bad=audit([bad],tmp)
            self.assertFalse(res_bad['passed'])
            self.assertIn([reg['organisasjonsnummer'],'identity spans not literal source text'],res_bad['errors'])
