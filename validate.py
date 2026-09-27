"""Validate run artifacts, separating structural validity from competitive score."""
import argparse
import json
from pathlib import Path
from agent import STATES, compare

def validate(rows, expected):
    errors=[]
    ids=[r.get('organisation_number') for r in rows]
    if ids!=expected:errors.append('Output count/order does not match input')
    for row in rows:
        org=row['organisation_number'];evidence={e['id']:e for e in row.get('evidence',[])}
        for c in row.get('claims',[]):
            if c['availability'] not in STATES:errors.append(f'{org}: invalid state')
            if c['availability']=='available' and (c['value'] is None or not c['evidence_ids']):errors.append(f'{org}: unsupported available claim')
            if c['availability']!='available' and c['value'] is not None:errors.append(f'{org}: unknown must not contain a value')
            for eid in c['evidence_ids']:
                if eid not in evidence:errors.append(f'{org}: missing evidence {eid}')
        for e in evidence.values():
            if not all(e.get(k) for k in ('source_url','retrieved_at','content_sha256')):errors.append(f'{org}: incomplete evidence')
        if row['operations']['requests']>20:errors.append(f'{org}: request budget exceeded')
        if compare(row,row):errors.append(f'{org}: non-idempotent self comparison')
    return {'structurally_valid':not errors,'errors':errors,'companies':len(rows),'official_score':None,
        'note':'Does not establish factual accuracy, source completeness or competition qualification.'}

def main():
    p=argparse.ArgumentParser();p.add_argument('input');p.add_argument('results');args=p.parse_args()
    expected=[str(json.loads(l)['organisation_number']) for l in Path(args.input).read_text().splitlines() if l.strip()]
    rows=[json.loads(l) for l in Path(args.results).read_text().splitlines() if l.strip()]
    result=validate(rows,expected);Path(args.results).with_suffix('.validation.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2));raise SystemExit(0 if result['structurally_valid'] else 1)

if __name__=='__main__':main()
