"""Optional URL discovery. Search snippets are never evidence for company facts."""
import hashlib
import http.client
import json
import os
from pathlib import Path
import threading
import time
from urllib.parse import urlsplit, urlunsplit
import re

DIRECTORIES = {'proff.no','purehelp.no','1881.no','gulesider.no','brreg.no','vexter.no',
               '1850.no','bizzy.org','wikipedia.org','facebook.com','linkedin.com','instagram.com',
               '180.no','io.no','vainu.com','listings.no','proffi.no','foretaksinfo.no',
               'firmalisten.no','yra.no','b2bprospect.no','finn.no','haandverkere.no','nol.no'}

def identity_candidates(results, org, name):
    """Rank discovery only; snippets never become evidence or survive retention."""
    domains={}
    terms=set(re.findall(r'\w+',name.casefold()))-{'as','asa','sti','stiftelsen','holding','eiendom','invest','drift','borettslag','boligsameie'}
    for position,r in enumerate(results):
        if not isinstance(r,dict):continue
        url=r.get('url')
        if not isinstance(url,str):continue
        try:
            p=urlsplit(url);host=(p.hostname or '').casefold()
            if p.scheme not in {'http','https'} or not host or p.username or p.password or p.port not in (None,80,443):continue
        except ValueError:continue
        if any(host==d or host.endswith('.'+d) for d in DIRECTORIES):continue
        # Search-result titles/snippets affect ordering only, never attribution.
        text=str(r.get('title',''))+' '+str(r.get('content',''))
        score=(10 if org in re.sub(r'\D','',text) else 0)+len(terms & set(re.findall(r'\w+',text.casefold())))
        if not score:continue
        root=urlunsplit((p.scheme,p.netloc,'/','',''))
        key=host.removeprefix('www.')
        item=domains.setdefault(key,{'url':root,'hints':[],'score':score,'position':position})
        item['score']=max(item['score'],score)
        # Only shallow, explicitly legal/contact paths; never vendor case studies
        # or directory entries quoting someone else's organisation number.
        parts=[x for x in p.path.casefold().split('/') if x]
        if (1<=len(parts)<=3 and re.search(r'kontakt|contact|personvern|privacy|legal|terms|vilk|beting|impressum',p.path,re.I)
            and not re.search(r'customer|kunde|case|portfolio|partner|sponsor|company|companies|bedrift',p.path,re.I)):
            hint=urlunsplit((p.scheme,p.netloc,p.path,p.query,''))
            if hint not in item['hints']:item['hints'].append(hint)
    return [{'url':i['url'],'hints':i['hints'][:2]} for i in sorted(domains.values(),key=lambda i:(-i['score'],i['position']))[:3]]


def candidate_urls(results):
    excluded = {'facebook.com', 'linkedin.com', 'instagram.com', 'proff.no',
                'brreg.no', 'purehelp.no', '1881.no', 'gulesider.no', 'wikipedia.org',
                'vexter.no', '1850.no', 'bizzy.org', 'virksomhet.brreg.no'}
    seen = set()
    for result in results:
        url = result.get('url') if isinstance(result, dict) else None
        if not isinstance(url, str): continue
        try:
            p = urlsplit(url); host = (p.hostname or '').lower()
            if p.scheme not in ('https', 'http') or not host or p.username or p.password: continue
            if p.port not in (None, 80, 443): continue
        except ValueError: continue
        if any(host == d or host.endswith('.' + d) for d in excluded): continue
        if host in seen: continue
        seen.add(host)
        # A vendor's customer page or business directory may quote the exact org
        # number. Establish ownership at the domain root and its own legal pages.
        yield urlunsplit((p.scheme, p.netloc, '/', '', ''))


class TavilySearch:
    """One basic request per company, globally capped. No signup or paid fallback."""
    def __init__(self, directory, limit=100, key=None, transport=None, strategy='legacy'):
        if not 1 <= limit <= 1000: raise ValueError('search credit cap must be 1..1000')
        self.directory = Path(directory) / 'search'
        self.directory.mkdir(parents=True, exist_ok=True)
        self.limit = limit; self.attempts = 0
        self.lock = threading.Lock(); self.last = 0
        self.key = key if key is not None else os.environ.get('TAVILY_API_KEY')
        self.transport = transport or self._post
        if strategy not in ('legacy','name_focus','adaptive'):raise ValueError('unknown search strategy')
        self.strategy=strategy

    def payload(self,name,org=None,mode=None):
        mode=mode or self.strategy
        query = '"' + name[:200] + '" Norge hjemmeside -site:proff.no -site:vexter.no -site:purehelp.no -site:1881.no -site:1850.no'
        payload=dict(query=query, search_depth='basic', topic='general', max_results=5,
                     include_answer=False, include_raw_content=False, include_images=False,
                     auto_parameters=False, include_usage=True)
        if mode=='name_focus':
            payload.update(query='"'+name[:200]+'"',max_results=10,country='norway',
                           exclude_domains=['proff.no','purehelp.no','1881.no','gulesider.no','brreg.no',
                                            'vexter.no','1850.no','bizzy.org','wikipedia.org',
                                            'facebook.com','linkedin.com','instagram.com'])
        if mode=='identity':
            payload.update(query='"'+name[:200]+'" '+org+' Norge',max_results=10,
                           country='norway',exclude_domains=sorted(DIRECTORIES))
        return payload

    def _post(self, payload, timeout):
        conn = http.client.HTTPSConnection('api.tavily.com', timeout=timeout)
        try:
            conn.request('POST', '/search', json.dumps(payload), headers={
                'Content-Type': 'application/json', 'Authorization': 'Bearer ' + self.key})
            response = conn.getresponse()
            # Never forward authorization through redirects; never log response errors.
            if response.status != 200: raise ValueError('search HTTP ' + str(response.status))
            raw = response.read(1_000_001)
            if len(raw) > 1_000_000: raise ValueError('search response too large')
            return json.loads(raw)
        finally: conn.close()

    def discover(self, org, name, fetcher, mode=None):
        mode=mode or self.strategy
        payload=self.payload(name,org,mode)
        cache_key=payload['query'] if mode=='legacy' else json.dumps(payload,sort_keys=True)
        path = self.directory / (hashlib.sha256(cache_key.encode()).hexdigest() + '.json')
        record = {'provider': 'tavily', 'state': 'unavailable', 'request_attempts': 0,
                  'credits_reported': 0, 'paid_cost_usd': 0, 'urls': [],'strategy':mode}
        fetcher.discovery = record
        if path.exists() and (fetcher.replay or not fetcher.fresh):
            cached = json.loads(path.read_text())
            record.update(state='cached', urls=list(candidate_urls([{'url': u} for u in cached['urls']])), retrieved_at=cached['retrieved_at'])
            if mode=='identity':record['candidates']=cached.get('candidates',[])
            fetcher.hits += 1
            return record['urls']
        if fetcher.replay:
            record['state'] = 'missing_replay_fixture'; return []
        if not self.key:
            record['state'] = 'key_not_configured'; return []
        # Serialize reservations and starts, enforcing the run-wide credit/request cap.
        with self.lock:
            remaining = fetcher.end - time.monotonic()
            pause = max(0, self.last + 1.05 - time.monotonic())
            if self.attempts >= self.limit or fetcher.requests >= fetcher.limit or remaining <= pause + .1:
                record['state'] = 'budget_exhausted'; return []
            if pause: time.sleep(pause)
            self.last = time.monotonic(); self.attempts += 1; fetcher.requests += 1
        record.update(request_attempts=1, credits_reported=None, paid_cost_usd=None)
        try:
            response = self.transport(payload, max(.1, min(8, fetcher.end - time.monotonic())))
            candidates=identity_candidates(response.get('results',[]),org,name) if mode=='identity' else []
            urls = [c['url'] for c in candidates] if mode=='identity' else list(candidate_urls(response.get('results', [])))[:2]
            record.update(state='completed', urls=urls,
                          credits_reported=response.get('usage', {}).get('credits'))
            if mode=='identity':record['candidates']=candidates
            # Cache only candidate URLs, never snippets, answers, API credentials or full output.
            from datetime import datetime, timezone
            record['retrieved_at'] = datetime.now(timezone.utc).isoformat()
            temp = path.with_suffix('.' + str(threading.get_ident()) + '.tmp')
            temp.write_text(json.dumps({'urls': urls, 'retrieved_at': record['retrieved_at'],
                                       **({'candidates':candidates} if mode=='identity' else {})}))
            temp.replace(path)
            return urls
        except (OSError, ValueError, TypeError, AttributeError, http.client.HTTPException) as exc:
            record.update(state='failed', error=type(exc).__name__)
            return []

    def iter_candidates(self,org,name,fetcher):
        """Second query is lazy: a confirmed first-stage site avoids its charge."""
        stages=[];seen=set()
        modes=('legacy','identity') if self.strategy=='adaptive' else (self.strategy,)
        for mode in modes:
            urls=self.discover(org,name,fetcher,mode)
            stage=dict(fetcher.discovery);stages.append(stage)
            if self.strategy=='adaptive':
                fetcher.discovery={'provider':'tavily','strategy':'adaptive','state':stage['state'],
                    'stages':stages,'urls':list(dict.fromkeys(u for s in stages for u in s['urls'])),
                    'request_attempts':sum(s['request_attempts'] for s in stages),
                    'credits_reported':None if any(s['credits_reported'] is None for s in stages) else sum(s['credits_reported'] for s in stages),
                    'paid_cost_usd':None if any(s['paid_cost_usd'] is None for s in stages) else 0}
            hints={c['url']:c['hints'] for c in stage.get('candidates',[])}
            for index,url in enumerate(urls):
                key=(urlsplit(url).hostname or '').removeprefix('www.')
                if key in seen and not hints.get(url):continue
                seen.add(key)
                yield url,len(urls)-index-1+(mode!=modes[-1]),hints.get(url,[])
