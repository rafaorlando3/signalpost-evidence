"""Audit published scalar values against retained sources; never estimate an official score."""
import argparse
import collections
import json
from pathlib import Path
from agent import digest, encode, compare, Page, website_identity

def resolve(data, pointer):
    for key in pointer.lstrip('/').split('/'):
        key=key.replace('~1','/').replace('~0','~')
        data=data[int(key)] if isinstance(data,list) else data[key]
    return data

def audit(rows, cache):
    counts=collections.Counter(); errors=[]; external=[]
    for row in rows:
        sources={}
        for e in row['evidence']:
            p=Path(cache)/e.get('snapshot_file',e.get('cache_file','MISSING'))
            if not p.is_file(): errors.append([row['organisation_number'],'missing snapshot',e['id']]);continue
            rsp=json.loads(p.read_text());sources[e['id']]=rsp
            if rsp['content_sha256']!=e['content_sha256']:
                errors.append([row['organisation_number'],'snapshot changed',e['id']])
            if e.get('retained_text_sha256') and digest(rsp['text'].encode())!=e['retained_text_sha256']:
                errors.append([row['organisation_number'],'retained text hash mismatch',e['id']])
            counts['source_references_checked']+=1
        for c in row['claims']:
            if c['availability']!='available': continue
            pointer=c.get('source_pointer') or ''
            # Only literal JSON Pointers: transformed collections need separate checks.
            if pointer.startswith('/') and ';' not in pointer:
                rsp=sources.get(c['evidence_ids'][0],{})
                try:
                    if resolve(rsp['json'],pointer)!=c['value']:raise ValueError('value mismatch')
                    counts['direct_claims_matched_to_source']+=1
                except (KeyError,TypeError,IndexError,ValueError) as exc:
                    errors.append([row['organisation_number'],c['field'],str(exc)])
            if c['field']=='website.verified_url':
                web=[s for eid,s in sources.items() if eid in c['evidence_ids'] and 'json' not in s]
                if pointer=='explicit_org_number' and not any(website_identity(row['organisation_number'],Page(s.get('text',''),s['url']))=='exact' for s in web):
                    errors.append([row['organisation_number'],'identity number not supported by retained page'])
                support=c.get('identity_support')
                if support:
                    spans=support.get('literal_spans',[])
                    if not spans or not any(all(Page(s.get('text',''),s['url']).text[x['start']:x['end']]==x['text'] for x in spans) for s in web):
                        errors.append([row['organisation_number'],'identity spans not literal source text'])
                    else:counts['literal_identity_spans_checked']+=len(spans)
                external.append({'organisation_number':row['organisation_number'],'url':c['value'],
                    'method':pointer,'evidence_ids':c['evidence_ids']})
            if c['field']=='website.contact_channels':
                from contacts import contact_links
                retained=[i for eid,s in sources.items() if eid in c['evidence_ids'] and 'text' in s
                          for i in contact_links(Page(s['text'],s['url']))]
                for item in c['value']:
                    if item not in retained:errors.append([row['organisation_number'],'contact link not supported by retained page'])
                    else:counts['literal_contact_links_checked']+=1
        if compare(row,row): errors.append([row['organisation_number'],'false self change'])
    return {'passed':not errors,'counts':dict(counts),'errors':errors,'external_identity_review':external,
        'official_score':None,'precision':None,'recall':None,
        'limitations':'Checks source consistency, not independent ground truth, source completeness, site ownership or official qualification.'}

def main():
    p=argparse.ArgumentParser();p.add_argument('results');p.add_argument('--cache',default='cache');args=p.parse_args()
    rows=[json.loads(l) for l in Path(args.results).read_text().splitlines() if l.strip()]
    result=audit(rows,args.cache)
    Path(args.results).with_suffix('.audit.json').write_text(json.dumps(result,indent=2))
    print(json.dumps({k:v for k,v in result.items() if k!='external_identity_review'},indent=2))
    raise SystemExit(0 if result['passed'] else 1)

if __name__=='__main__':main()
