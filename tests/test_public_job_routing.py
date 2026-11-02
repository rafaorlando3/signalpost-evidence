import unittest
from urllib.parse import urlencode
from agent import Page
from public_recruiting import discover, registered_trade_query
import test_public_recruiting as fixtures
from test_public_recruiting import DATA, AD, ORG, html, rsp


class FairBoardRouting(unittest.TestCase):
    def test_stale_first_board_does_not_starve_active_nav_or_resurrect_closed_syndication(self):
        second='https://www.finn.no/job/ad/222222222'
        for source,accepted in [(None,True),(AD,False)]:
            nav=fixtures.NAVPrimary().source(sourceUrl=source)
            class F:
                requests=0;limit=20
                def get(self,url,**kwargs):
                    self.requests+=1
                    if 'finn.no/job/search?' in url:
                        return rsp(url,''.join('<article><strong>Example Plant AS</strong><a href="'+u+'">Engineer</a></article>' for u in [AD,second]))
                    if 'arbeidsplassen.nav.no/stillinger?' in url:
                        return rsp(url,'<article><p>Arbeidsgiver</p><p>Example Plant AS</p><a href="'+nav['url']+'">Engineer</a></article>')
                    if url==nav['url']:return nav
                    return rsp(url,html(state='Besatt').replace(AD,url))
            result=discover(DATA,[],F())
            self.assertEqual(bool(result['records']),accepted)
            self.assertLessEqual(result['detail_attempts'],2)
            self.assertEqual([x['provider'] for x in result['checks']],['finn','nav'])

    def test_two_previously_valid_finn_details_are_preserved(self):
        second='https://www.finn.no/job/ad/222222222'
        class F:
            requests=0;limit=20
            def get(self,url,**kwargs):
                self.requests+=1
                if '/search?' in url:
                    return rsp(url,''.join('<article><strong>Example Plant AS</strong><a href="'+u+'">Engineer</a></article>' for u in [AD,second]))
                return rsp(url,html().replace(AD,url))
        result=discover(DATA,[],F())
        self.assertEqual(len(result['records']),2)
        self.assertEqual(result['detail_attempts'],2)

    def test_registered_trade_is_a_search_lead_but_corporate_binding_remains_required(self):
        unit={'organisasjonsnummer':'974761076','overordnetEnhet':ORG,'navn':'Local Café'}
        self.assertEqual(registered_trade_query(DATA,[unit]),'Local Café')
        self.assertIsNone(registered_trade_query(DATA,[unit,{**unit,'navn':'Another Café'}]))
        self.assertIsNone(registered_trade_query(DATA,[{**unit,'overordnetEnhet':'974761076'}]))
        for number,accepted in [('974761076',True),('988943037',False)]:
            nav=fixtures.NAVPrimary().source(employer={'orgnr':number,'name':'Local Café'},sourceUrl=None)
            class F:
                requests=0;limit=20
                def get(self,url,**kwargs):
                    self.requests+=1
                    if url==nav['url']:return nav
                    if urlencode({'q':'Local Café'}) in url:
                        return rsp(url,'<article><p>Arbeidsgiver</p><p>Local Café</p><a href="'+nav['url']+'">Engineer</a></article>')
                    return rsp(url,'No results')
            result=discover(DATA,[unit],F())
            self.assertEqual(bool(result['records']),accepted)
            self.assertEqual(len(result['checks']),3)
            self.assertEqual(result['checks'][-1]['query_basis'],'unique current registered child trade name; URL discovery only')
