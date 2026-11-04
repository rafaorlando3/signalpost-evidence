import tempfile
import unittest
from pathlib import Path

from agent import Fetcher, digest, encode, research
from registry_discovery import name_domain_candidates, short_legal_name_candidates
import test_pipeline as base


class ShortNameDiscovery(unittest.TestCase):
    def test_short_full_names_are_late_leads_without_changing_existing_candidates(self):
        self.assertEqual(name_domain_candidates({'navn':'XYLO AS'}), [])
        self.assertEqual(short_legal_name_candidates({'navn':'XYLO AS'}),
                         ['https://xylo.no/','https://xylo.com/'])
        self.assertEqual(short_legal_name_candidates({'navn':'ÆRA ASA'}),
                         ['https://aera.no/','https://aera.com/'])
        for name in ['XYLO BERGEN AS','XYLO HOLDING AS','Longbrand AS','XY AS',
                     '123 AS','XYLO','XYLO NUF','XYLO A/S']:
            self.assertEqual(short_legal_name_candidates({'navn':name}), [])

    def row(self, raw, robots='User-agent: *\nAllow: /'):
        directory=tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root=Path(directory.name)
        base.Pipeline().fixture(root)
        base.save(root,base.BASE,{'organisasjonsnummer':base.ORG,'navn':'XYLO AS'})
        for url,text in [('https://xylo.no/robots.txt',robots),('https://xylo.no/',raw)]:
            (root/(digest(url.encode())+'.json')).write_text(encode({
                'url':url,'status':'available','status_code':200,'text':text,
                'retrieved_at':'2026-11-04T12:00:00Z','content_sha256':digest(text.encode())}))
        row=research({'organisation_number':base.ORG},Fetcher(root,replay=True,public_jobs=False))
        return row

    def test_unknown_short_name_site_still_requires_independent_exact_legal_proof(self):
        row=self.row('<title>Xylo</title><footer>Xylo AS Org.nr '+base.ORG+'</footer>')
        claim=next(c for c in row['claims'] if c['field']=='website.verified_url')
        self.assertEqual(claim['value'],'https://xylo.no/')
        self.assertEqual(claim['source_pointer'],'explicit_org_number')
        self.assertEqual(next(a for a in row['website_attempts'] if a['url']=='https://xylo.no/')['origin'],
                         'late_short_legal_name_heuristic')

    def test_collision_foreign_company_and_robots_policy_are_not_waived(self):
        for html,robots in [('<title>Xylo</title><p>Welcome to Xylo</p>','User-agent: *\nAllow: /'),
                            ('<footer>Xylo AS Org.nr 913884213</footer>','User-agent: *\nAllow: /'),
                            ('<footer>Xylo AS Org.nr '+base.ORG+'</footer>','User-agent: *\nDisallow: /')]:
            row=self.row(html,robots)
            claim=next(c for c in row['claims'] if c['field']=='website.verified_url')
            self.assertNotEqual(claim['availability'],'available')


if __name__=='__main__': unittest.main()
