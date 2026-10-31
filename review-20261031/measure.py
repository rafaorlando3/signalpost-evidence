"""Recompute this local comparison without inventing official precision/recall."""
import collections
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from output_contract import contract_errors
from validate import validate

root=Path(__file__).resolve().parent
read=lambda name:[json.loads(line) for line in (root/name).read_text().splitlines()]
expected=(root/'orgs100.txt').read_text().splitlines()
baseline=read('baseline-paired.jsonl');candidate=read('candidate-reviewed.jsonl')
fields=['website.verified_url','website.social_links','website.activity','website.contact_channels','website.hiring']
def stats(rows):
 return {field:{'companies':sum(any(c['field']==field and c['availability']=='available' and bool(c['value']) for c in row['claims']) for row in rows),
                'items':sum((len(c['value']) if isinstance(c['value'],list) else 1) for row in rows for c in row['claims'] if c['field']==field and c['availability']=='available' and bool(c['value']))}
         for field in fields}
manifest=json.loads((root/'cache-manifest.json').read_text())['files'];cache=root.parent/'cache/shared'
current={str(p.relative_to(cache)):hashlib.sha256(p.read_bytes()).hexdigest() for p in cache.rglob('*.json')}
current_sources={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.parent.glob('*.py')}
frozen=json.loads((root/'source-freeze.json').read_text())
metrics={'scope':'local paired test on 100 new firms, stratified 50 with/50 without a declared site; not a representative precision/recall estimate or official score',
 'baseline_commit':'c2e81e14f8e7ee7423083710a8244b28970d9adb','baseline':stats(baseline),'candidate':stats(candidate),
 'terminal_envelopes':len(candidate),'input_order_preserved':[r['organisation_number'] for r in candidate]==expected,
 'candidate_legacy_validation':validate(candidate,expected),'minimal_contract_errors':sum(len(contract_errors(row)) for row in candidate),
 'cache_unchanged':manifest==current,'cache_files':len(current),'source_freeze_matches':current_sources==frozen['candidate_sources'],
 'requests_paired':sum(row['operations']['requests'] for row in candidate),'third_party_cost_usd':0,
 'official_score':None,'network_capture_note':'Both replay arms use identical captured URL responses; baseline captures take priority, candidate fills missing URLs. Preliminary live candidate claims are not the final scored arm.'}
(root/'METRICS.json').write_text(json.dumps(metrics,indent=2));print(json.dumps(metrics,indent=2))
