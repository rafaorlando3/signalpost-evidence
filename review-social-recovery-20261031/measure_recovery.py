"""Local coverage, evidence integrity and paired comparisons; no official score."""
from pathlib import Path
import json,hashlib,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from validate import validate
from output_contract import contract_errors
from attribution import canonical_profile
root=Path(__file__).resolve().parent
read=lambda p:[json.loads(line) for line in p.read_text().splitlines()]
fields=['website.verified_url','website.social_links','website.activity','website.hiring','website.contact_channels']
def stats(rows):
 return {f:{'companies':sum(any(c['field']==f and c['availability']=='available' and bool(c['value']) for c in r['claims']) for r in rows),
            'items':sum((len(c['value']) if isinstance(c['value'],list) else 1) for r in rows for c in r['claims'] if c['field']==f and c['availability']=='available' and bool(c['value']))}
         for f in fields}
old=root.parent/'review-20261031'
original={name:stats(read(path)) for name,path in [('baseline',old/'baseline-paired.jsonl'),('strict',old/'candidate-reviewed.jsonl'),('recovery',root/'original100-final.jsonl')]}
new={name:stats(read(root/(name+'-paired.jsonl'))) for name in ['baseline','strict','recovery']}
expected=(root/'fresh100.txt').read_text().splitlines();recovery=read(root/'recovery-paired.jsonl')
manifest=json.loads((root/'SHARED-CACHE-MANIFEST.json').read_text())['files'];cache=root.parent/'cache/social-shared'
current={str(p.relative_to(cache)):hashlib.sha256(p.read_bytes()).hexdigest() for p in cache.rglob('*.json')}
freeze=json.loads((root/'SOURCE-FREEZE.json').read_text())['sources']
unchanged=all(hashlib.sha256((root.parent/p).read_bytes()).hexdigest()==h for p,h in freeze.items())
known_bad={'https://facebook.com/wix','https://linkedin.com/in/mbokenfohr','https://linkedin.com/company/sergel','https://tiktok.com/tag/lillelam'}
original_rows=read(root/'original100-final.jsonl');all_urls={item['url'] for row in original_rows for claim in row['claims'] if claim['field']=='website.social_links' for item in claim['value'] or []}
result={'scope':'Local comparison. Original 100 are development cases; separate fresh 100 were selected before runs. Both are stratified 50 registered websites / 50 without, not population estimates.',
        'commits':{'submitted_baseline':'c2e81e14f8e7ee7423083710a8244b28970d9adb','strict_previous':'2aaaef3cac092c04f58e8b2f27fbb59de696c20e'},
        'original100':original,'fresh100':new,'fresh_validation':validate(recovery,expected),
        'minimal_contract_errors':sum(len(contract_errors(row)) for row in recovery),'shared_cache_unchanged':current==manifest,
        'source_freeze_matches':unchanged,'known_bad_urls_reintroduced':sorted(known_bad & all_urls),
        'availability_states':{state:sum(claim['availability']==state for row in recovery for claim in row['claims']) for state in ['available','ambiguous','blocked','not_available','failed','not_applicable']},
        'verification_scope':'Recovered URLs are supported by exact-company declarations and source identity. No independent social-platform login/ownership or population precision assertion.',
        'duplicate_scope':'Items count URL observations; different URLs on the same platform are not asserted to be distinct accounts.',
        'official_score':None,'third_party_cost_usd':0}
(root/'METRICS.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
assert result['shared_cache_unchanged'] and unchanged and not result['known_bad_urls_reintroduced'] and result['minimal_contract_errors']==0 and result['fresh_validation']['structurally_valid']
