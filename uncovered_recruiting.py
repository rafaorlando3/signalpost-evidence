"""Late recruiting budget prioritises previously uncovered legal employers.

Searches/registered business prefixes only nominate URLs. Existing primary
board parsing still requires a current dated ad, exact published corporate
number or a registered child and matching employer. No target URLs/IDs stored.
"""
import re

def shared_registered_query(data,units):
    from agent import valid_org
    from attribution import legal_stem
    target=data.get('organisasjonsnummer');prefixes=[]
    for unit in units:
        if unit.get('overordnetEnhet')!=target or not valid_org(str(unit.get('organisasjonsnummer',''))):continue
        name=unit.get('navn')
        if not isinstance(name,str):continue
        match=re.match(r'^(.{5,160}?)\s+AVD(?:ELING)?\.?\s+\S',name,re.I)
        if match:prefixes.append(match[1].strip())
    if len(prefixes)<2:return None
    keys={legal_stem(p) for p in prefixes}
    if len(keys)!=1 or not next(iter(keys)) or next(iter(keys))==legal_stem(data.get('navn','')):return None
    return prefixes[0]


def discover_uncovered(data,units,fetcher,previous=None):
    from agent import valid_org
    from public_recruiting import discover
    result={'records':[],'sources':[],'checks':[],'detail_attempts':0,'identity_sources':[]}
    if (not getattr(fetcher,'public_jobs',True) or not valid_org(str(data.get('organisasjonsnummer','')))
            or not isinstance(data.get('navn'),str) or not 3<=len(data['navn'])<=200):return result
    # The established phase always retains its full allowance/order. This last
    # pass may use the unspent base budget plus at most four extra HTTP calls.
    fetcher.limit=min(fetcher.limit+4,24)
    result=discover(data,units,fetcher,max_details=2,resume=previous,
                    query_override=shared_registered_query(data,units),stop_after_first=True,matching_labels_only=True)
    result['identity_sources']=[]
    return result
