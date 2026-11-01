"""Anonymous Mwmbl API discovery; URL leads only, zero billing credentials.

Official service: https://developer.mwmbl.org/ (anonymous 1,000/month/IP,
1 request/second). A shared run cap and circuit breaker never switch IPs,
versions, hosts or credentials after a quota/access failure.
"""
import re
import threading
import time
from urllib.parse import urlencode,urlsplit

class AnonymousSearch:
    def __init__(self,limit=1000):
        if not isinstance(limit,int) or isinstance(limit,bool) or not 1<=limit<=1000:raise ValueError('anonymous search limit must be1..1000')
        self.limit=limit;self.attempts=0;self.last=0;self.lock=threading.Lock();self.disabled=None

    def discover(self,data,fetcher):
        from agent import digest
        from search import identity_candidates
        name=data.get('navn');org=data.get('organisasjonsnummer')
        record={'provider':'mwmbl_anonymous','state':'not_checked','request_attempts':0,'paid_cost_usd':0,'candidates':[],
                'attribution':'https://mwmbl.org/','endpoint_documentation':'https://developer.mwmbl.org/',
                'scope':'URL discovery only; snippets are not company evidence'}
        fetcher.public_search_discovery=record
        if not isinstance(name,str) or not isinstance(org,str):record['state']='invalid_identity_input';return []
        query=re.sub(r'\s+(?:AS|ASA|NUF|ANS|DA|SA)\s*$','',name,flags=re.I).strip()[:200]
        if len(query)<3:record['state']='query_too_short';return []
        url='https://api.mwmbl.org/api/v2/search/?'+urlencode({'q':query});record['query_url']=url
        cached=(fetcher.directory/(digest(url.encode())+'.json')).exists() and (fetcher.replay or not fetcher.fresh)
        if fetcher.replay and not cached:record['state']='missing_replay_fixture';return []
        if not cached:
            with self.lock:
                if self.disabled:record['state']=self.disabled;return []
                pause=max(0,self.last+1.1-time.monotonic())
                if self.attempts>=self.limit or fetcher.requests>=fetcher.limit-2 or fetcher.end-time.monotonic()<=pause+.2:
                    record['state']='budget_exhausted';return []
                if pause:time.sleep(pause)
                self.attempts+=1;self.last=time.monotonic();record['request_attempts']=1
        response=fetcher.get(url)
        record.update(source_status=response['status'],http_status=response.get('status_code'),retrieved_at=response.get('retrieved_at'),content_sha256=response.get('content_sha256'))
        if response.get('status_code') in (401,403,429):
            with self.lock:self.disabled='provider_access_or_quota_blocked'
            record['state']=self.disabled;return []
        if response['status']!='available':record['state']='source_unavailable';return []
        payload=response.get('json')
        if (urlsplit(response['url']).hostname!='api.mwmbl.org' or not isinstance(payload,dict)
                or payload.get('query')!=query or not isinstance(payload.get('results'),list)):
            record['state']='invalid_response';return []
        candidates=identity_candidates(payload['results'][:100],org,name)[:2]
        record.update(state='cached' if cached else 'completed',candidates=candidates,
                      results_seen=min(len(payload['results']),100),monthly_usage=payload.get('monthly_usage'),monthly_limit=payload.get('monthly_limit'))
        return candidates
