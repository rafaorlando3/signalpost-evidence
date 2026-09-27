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

    def test_fresh_mode_uses_supplied_snapshot_without_network(self):
        with tempfile.TemporaryDirectory() as source,tempfile.TemporaryDirectory() as cache,patch('socket.getaddrinfo',side_effect=AssertionError('network forbidden')):
            snapshot=FrozenRegistry(self.bundle(source))
            row=research({'organisation_number':ORG},Fetcher(cache,fresh=True,registry_snapshot=snapshot))
            self.assertEqual(row['operations']['requests'],0)
            self.assertEqual(next(c['value'] for c in row['claims'] if c['field']=='legal_name'),'Fixture AS')
            self.assertTrue(all(e['retrieved_at']=='2026-09-26T00:00:00+00:00' for e in row['evidence']))

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
