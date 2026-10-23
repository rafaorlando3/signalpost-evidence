"""Validate run artifacts, separating structural validity from competitive score."""
import argparse
import json
from pathlib import Path
from agent import STATES, compare

def validate(rows, expected):
    errors=[]
    ids=[r.get('organisation_number') if isinstance(r,dict) else None for r in rows]
    if ids!=expected:errors.append('Output count/order does not match input')
    for index,row in enumerate(rows):
        if not isinstance(row,dict):
            errors.append(f'Row {index}: terminal envelope must be an object')
            continue
        org=row.get('organisation_number',f'row {index}')
        sections={'claims':list,'evidence':list,'changes':list,'errors':list,
                  'source_snapshots':list,'refresh':dict,'run':dict,'operations':dict}
        malformed=False
        for section,kind in sections.items():
            if not isinstance(row.get(section),kind):
                errors.append(f'{org}: missing or invalid {section}')
                malformed=True
        if malformed:continue
        if not isinstance(row.get('organisation_number'),str):
            errors.append(f'{org}: missing or invalid organisation_number')
            continue
        if row['run'].get('terminal_status') not in ('completed','failed'):
            errors.append(f'{org}: invalid terminal_status')
        if (any(not isinstance(e,dict) or not isinstance(e.get('id'),str) for e in row['evidence'])
                or any(not isinstance(c,dict) or not isinstance(c.get('field'),str)
                       or not isinstance(c.get('evidence_ids'),list)
                       or any(not isinstance(eid,str) for eid in c.get('evidence_ids',[]))
                       or 'availability' not in c or 'value' not in c for c in row['claims'])):
            errors.append(f'{org}: invalid evidence or claim shape')
            continue
        org=row['organisation_number'];evidence={e['id']:e for e in row.get('evidence',[])}
        if len(evidence)!=len(row['evidence']):errors.append(f'{org}: duplicate evidence IDs')
        for c in row.get('claims',[]):
            if c['availability'] not in STATES:errors.append(f'{org}: invalid state')
            if c['availability']=='available' and (c['value'] is None or not c['evidence_ids']):errors.append(f'{org}: unsupported available claim')
            if c['availability']!='available' and c['value'] is not None:errors.append(f'{org}: unknown must not contain a value')
            for eid in c['evidence_ids']:
                if eid not in evidence:errors.append(f'{org}: missing evidence {eid}')
        for e in evidence.values():
            if not all(e.get(k) for k in ('source_url','retrieved_at','content_sha256')):errors.append(f'{org}: incomplete evidence')
        requests=row['operations'].get('requests')
        if type(requests) is not int or requests<0:errors.append(f'{org}: invalid request count')
        elif requests>20:errors.append(f'{org}: request budget exceeded')
        try:
            if compare(row,row):errors.append(f'{org}: non-idempotent self comparison')
        except (TypeError,ValueError,KeyError,AttributeError):
            errors.append(f'{org}: invalid comparison/history shape')
    return {'structurally_valid':not errors,'errors':errors,'companies':len(rows),'official_score':None,
        'note':'Does not establish factual accuracy, source completeness or competition qualification.'}

def main():
    p=argparse.ArgumentParser();p.add_argument('input');p.add_argument('results');args=p.parse_args()
    expected=[str(json.loads(l)['organisation_number']) for l in Path(args.input).read_text().splitlines() if l.strip()]
    rows=[json.loads(l) for l in Path(args.results).read_text().splitlines() if l.strip()]
    result=validate(rows,expected);Path(args.results).with_suffix('.validation.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2));raise SystemExit(0 if result['structurally_valid'] else 1)

if __name__=='__main__':main()
