import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from agent import Fetcher,research,digest
from frozen_registry import FrozenRegistry
import test_pipeline as fixtures
ORG=fixtures.ORG
BASE=fixtures.BASE

class FrozenSnapshots(unittest.TestCase):
    def bundle(self,d):
        fixtures.Pipeline().fixture(d)
        records=[json.loads(p.read_text()) for p in Path(d).glob('*.json')]
        path=Path(d)/'registry.jsonl';path.write_text(''.join(json.dumps(r)+'\n' for r in records))
        return path

    def test_fresh_mode_uses_supplied_snapshot_without_live_registry(self):
        # The frozen snapshot governs registry I/O; optional external discovery
        # may still attempt public sites. Deny those safely in this fixture.
        with tempfile.TemporaryDirectory() as source,tempfile.TemporaryDirectory() as cache,patch('agent.safe_url',side_effect=ValueError('external fixture unavailable')) as outgoing:
            snapshot=FrozenRegistry(self.bundle(source))
            row=research({'organisation_number':ORG},Fetcher(cache,fresh=True,registry_snapshot=snapshot))
            self.assertEqual(row['operations']['requests'],0)
            self.assertEqual(next(c['value'] for c in row['claims'] if c['field']=='legal_name'),'Fixture AS')
            self.assertTrue(all(e['retrieved_at']=='2026-09-26T00:00:00+00:00' for e in row['evidence']))
            self.assertTrue(all(not c.args[0].startswith('https://data.brreg.no/') for c in outgoing.call_args_list))

    def test_missing_snapshot_never_falls_back_to_live_registry(self):
        with tempfile.TemporaryDirectory() as d,patch('socket.getaddrinfo',side_effect=AssertionError('network forbidden')):
            snapshot=FrozenRegistry(self.bundle(d));snapshot.responses.pop(BASE)
            result=Fetcher(d,fresh=True,registry_snapshot=snapshot).get(BASE)
            self.assertEqual(result['status'],'failed');self.assertIn('fallback disabled',result['error'])

    def test_corrupt_or_external_sources_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path=self.bundle(d);lines=path.read_text().splitlines();record=json.loads(lines[0])
            for change in ({'text':'{}'},{'url':'https://example.test/'},{'retrieved_at':'2026-09-26'}):
                path.write_text(json.dumps({**record,**change})+'\n')
                with self.assertRaises(ValueError):FrozenRegistry(path)

if __name__=='__main__':unittest.main()

class UnicodeRegistryJSONL(unittest.TestCase):
    def test_literal_unicode_separator_is_data_not_an_interchange_delimiter(self):
        import hashlib
        from frozen_registry import FrozenRegistry
        with tempfile.TemporaryDirectory() as folder:
            url='https://data.brreg.no/enhetsregisteret/api/enheter/810034882'
            data={'organisasjonsnummer':'810034882','navn':'Before\u2028After'}
            data['navn']=data['navn'].replace('\\u2028','\u2028')
            text=json.dumps(data,ensure_ascii=False)
            record={'requested_url':url,'url':url,'retrieved_at':'2026-11-01T00:00:00Z','status':'available','status_code':200,'content_sha256':hashlib.sha256(text.encode()).hexdigest(),'text':text,'json':data}
            path=Path(folder)/'registry.jsonl';path.write_text(json.dumps(record,ensure_ascii=False)+'\n')
            self.assertEqual(FrozenRegistry(path).lookup(url)['json'],data)
