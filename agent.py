"""Evidence-first company research. Python standard library; optional, explicitly configured search."""
from __future__ import annotations
import argparse
import collections
import concurrent.futures
import datetime as dt
import gzip
import hashlib
import html
from html.parser import HTMLParser
import http.client
import ipaddress
import json
from pathlib import Path
import re
import socket
import ssl
import threading
import time
import uuid
from urllib.parse import urljoin, urlsplit, urlunsplit, quote
from urllib.robotparser import RobotFileParser

VERSION = '0.7.0'
UA = 'SignalpostEvidence/0.7 (company research; respects robots.txt)'
OFFICIAL = 'https://data.brreg.no'
STATES = {'available', 'not_available', 'blocked', 'not_applicable', 'ambiguous', 'failed'}

def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))

def digest(value):
    return hashlib.sha256(value).hexdigest()

def valid_org(value):
    if not re.fullmatch(r'[0-9]{9}', str(value)):
        return False
    check = (11 - sum(int(n)*w for n,w in zip(value[:8], [3,2,7,6,5,4,3,2])) % 11) % 11
    return check != 10 and check == int(value[-1])

def safe_url(url):
    p = urlsplit(url)
    if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password:
        raise ValueError('Only public HTTP(S) URLs without credentials are supported')
    if p.port not in (None, 80, 443):
        raise ValueError('Port not permitted')
    host = p.hostname.encode('idna').decode()
    port = p.port or (443 if p.scheme == 'https' else 80)
    addresses = {a[4][0] for a in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)}
    if not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses):
        raise ValueError('Non-public destination blocked')
    return p, host, port, sorted(addresses)[0]

class Fetcher:
    locks = collections.defaultdict(threading.Lock)
    host_last = {}

    def __init__(self, directory, *, replay=False, fresh=False, limit=20, deadline=90, registry_snapshot=None):
        self.directory = Path(directory); self.directory.mkdir(parents=True, exist_ok=True)
        self.replay, self.fresh = replay, fresh
        self.limit = limit; self.end = time.monotonic()+deadline
        self.requests = 0; self.hits = 0; self.robots = {}; self.records = []
        self.registry_snapshot=registry_snapshot

    def get(self, url, *, site=False, raw=False):
        if self.registry_snapshot is not None:
            from frozen_registry import registry_url
            if registry_url(url):
                result=self.registry_snapshot.lookup(url)
                if result is None:return self.failure(url,'failed','missing supplied registry snapshot; live fallback disabled')
                if '/roller' in url:
                    result['json']=redact(result['json']);result['text']=encode(result['json'])
                    result['retention']='redacted supplied registry JSON; original content hash preserved'
                self.retain(result);self.records.append(result);self.hits+=1
                return result
        if site:
            origin = urlunsplit((*urlsplit(url)[:2], '', '', ''))
            if origin not in self.robots:
                response = self.get(origin+'/robots.txt', raw=True)
                parser = RobotFileParser()
                if response['status_code'] in (404, 410):
                    parser.parse([])
                elif response['status_code'] == 200:
                    parser.parse(response.get('text', '').splitlines())
                else:
                    parser.parse(['User-agent: *', 'Disallow: /'])
                self.robots[origin] = parser
            if not self.robots[origin].can_fetch(UA, url):
                return self.failure(url, 'blocked', 'robots denied or unavailable')
        path = self.directory/(digest(url.encode())+'.json')
        if path.exists() and (self.replay or not self.fresh):
            result = json.loads(path.read_text()); self.hits += 1
            self.retain(result)
            self.records.append(result); return result
        if self.replay:
            return self.failure(url, 'failed', 'missing replay fixture')
        current = url
        result = None; retried=False
        for _ in range(4):
            if self.requests >= self.limit or time.monotonic() >= self.end:
                return self.failure(current, 'failed', 'request/time budget exhausted')
            connection=None
            try:
                p, host, port, address = safe_url(current)
                with self.locks[host]:
                    pause = max(0, self.host_last.get(host, 0)+0.25-time.monotonic())
                    if pause: time.sleep(pause)
                    self.host_last[host] = time.monotonic()
                self.requests += 1
                timeout = max(0.1, min(8, self.end-time.monotonic()))
                connection = (http.client.HTTPSConnection(host, port, timeout=timeout, context=ssl.create_default_context())
                    if p.scheme == 'https' else http.client.HTTPConnection(host, port, timeout=timeout))
                # Pin the validated address while retaining original TLS hostname verification.
                connection._create_connection = lambda *_args, **_kw: socket.create_connection((address, port), timeout)
                connection.request('GET', (p.path or '/')+('?' + p.query if p.query else ''),
                    headers={'User-Agent': UA, 'Accept': 'application/json,text/html,text/plain', 'Accept-Encoding': 'identity'})
                response = connection.getresponse(); status = response.status
                if status in (500,502,503,504) and host=='data.brreg.no' and not retried:
                    connection.close(); retried=True; continue
                if status in (301, 302, 303, 307, 308):
                    location = response.getheader('Location'); connection.close()
                    if not location: return self.failure(current, 'failed', 'redirect missing location')
                    target = urljoin(current, location)
                    if site and urlsplit(target).netloc != urlsplit(current).netloc:
                        redirected={**self.get(target,site=True,raw=raw),'requested_url':url}
                        self.retain(redirected)
                        temporary=path.with_suffix('.'+uuid.uuid4().hex+'.tmp')
                        temporary.write_text(encode(redirected));temporary.replace(path)
                        return redirected
                    current = target; continue
                data = response.read(2_000_001); connection.close()
                if len(data) > 2_000_000: return self.failure(current, 'blocked', 'response size limit')
                charset = response.headers.get_content_charset() or 'utf-8'
                text = data.decode(charset, errors='replace')
                state = 'available' if status == 200 else 'not_available' if status in (404,410) else 'blocked' if status in (401,403,429) else 'failed'
                result = {'url':current, 'requested_url':url, 'status':state, 'status_code':status,
                    'retrieved_at':now(), 'content_sha256':digest(data), 'text':text}
                if not raw:
                    try: result['json'] = json.loads(text)
                    except ValueError: pass
                # Registry responses include birth dates: strip them from retained bodies.
                if '/roller' in current and 'json' in result:
                    result['json'] = redact(result['json']); result['text'] = encode(result['json'])
                    result['retention'] = 'redacted JSON; content_sha256 describes original response'
                self.retain(result)
                temporary=path.with_suffix('.'+uuid.uuid4().hex+'.tmp')
                temporary.write_text(encode(result)); temporary.replace(path)
                self.records.append(result); return result
            except (OSError, ValueError, http.client.HTTPException) as error:
                if connection is not None: connection.close()
                result = self.failure(current, 'failed', type(error).__name__)
                if isinstance(error,(OSError,http.client.HTTPException)) and urlsplit(current).hostname=='data.brreg.no' and not retried:
                    retried=True;continue
                break
        return result or self.failure(current, 'failed', 'redirect limit')

    def retain(self,result):
        if not result.get('content_sha256'): return
        archive=self.directory/'snapshots'; archive.mkdir(exist_ok=True)
        name=digest((result.get('requested_url',result['url'])+result['retrieved_at']+result['content_sha256']).encode())+'.json'
        result['snapshot_file']='snapshots/'+name
        archived=archive/name
        if not archived.exists(): archived.write_text(encode(result))

    def failure(self, url, status, error):
        result = {'url':url, 'status':status, 'status_code':0, 'error':error, 'retrieved_at':now()}
        self.records.append(result); return result

def redact(value):
    if isinstance(value, dict):
        return {k:redact(v) for k,v in value.items() if k not in ('fodselsdato','fodselsnummer','dNummer')}
    if isinstance(value, list): return [redact(v) for v in value]
    return value

class Page(HTMLParser):
    def __init__(self, text, url):
        super().__init__(convert_charrefs=True)
        self.url=url; self.parts=[]; self.links=[]; self.ld=[]; self.skip=0; self.script=None
        self.title=''; self.in_title=False; self.description=''; self.anchor=None;self.meta={}
        self.headings=[];self.heading=None;self.times=[];self.feeds=[];self.link_context=[]
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        a=dict(attrs)
        context=' '.join((a.get(k) or '') for k in ('class','id','aria-label','title','data-sentry-component','data-sentry-source-file'))
        third_party=(self.link_context[-1][1] if self.link_context else False) or bool(re.search(r'sponsor|partner|customer|testimonial|shar(?:e|ing)|author',context,re.I))
        if tag not in {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}:
            self.link_context.append((tag,third_party))
        if tag=='img' and self.anchor and re.search(r'sponsor|partner|customer',(a.get('alt') or ''),re.I):
            self.anchor['third_party_context']=True
        if tag in ('script','style','noscript'):
            self.skip += 1
            if tag=='script' and a.get('type')=='application/ld+json': self.script=[]
        if tag=='title': self.in_title=True
        if tag=='h1':self.heading=''
        if tag=='time' and a.get('datetime'):
            semantic=((a.get('itemprop') or '')+' '+(a.get('class') or '')).casefold()
            if re.search(r'\b(datepublished|published|entry-date)\b',semantic) and not re.search(r'updated|modified',semantic):
                self.times.append(a['datetime'])
        if tag=='link' and 'alternate' in (a.get('rel') or '').split() and a.get('type') in ('application/rss+xml','application/atom+xml') and a.get('href'):
            self.feeds.append(urljoin(self.url,a['href']))
        if tag=='meta' and (a.get('name') or '').lower()=='description': self.description=a.get('content') or ''
        if tag=='meta' and (a.get('property') or a.get('name')):
            self.meta[(a.get('property') or a.get('name')).lower()]=a.get('content') or ''
        if tag=='a' and a.get('href'):
            self.anchor={'url':urljoin(self.url,a['href']), 'text':'','third_party_context':third_party}

    def handle_endtag(self, tag):
        for i in range(len(self.link_context)-1,-1,-1):
            if self.link_context[i][0]==tag:
                del self.link_context[i:];break
        if tag in ('script','style','noscript'):
            if self.script is not None and tag=='script':
                try: self.ld.append(json.loads(''.join(self.script)))
                except ValueError: pass
                self.script=None
            self.skip=max(0,self.skip-1)
        if tag=='title': self.in_title=False
        if tag=='h1' and self.heading is not None:
            self.headings.append(re.sub(r'\s+',' ',self.heading).strip());self.heading=None
        if tag=='a' and self.anchor:
            self.links.append(self.anchor); self.anchor=None

    def handle_data(self, value):
        if self.script is not None: self.script.append(value)
        if self.in_title: self.title += value
        if not self.skip:
            if self.heading is not None:self.heading+=value+' '
            self.parts.append(value)
            if self.anchor: self.anchor['text'] += value

    @property
    def text(self): return re.sub(r'\s+', ' ', ' '.join(self.parts)).strip()

def objects(value):
    if isinstance(value, dict):
        yield value
        for item in value.values(): yield from objects(item)
    elif isinstance(value,list):
        for item in value: yield from objects(item)

def schema_types(item):
    value=item.get('@type',[])
    return {v for v in (value if isinstance(value,list) else [value]) if isinstance(v,str)}

def typed_json(response, expected, required=None):
    value=response.get('json')
    if response['status']=='available' and (not isinstance(value,expected) or (required and required not in value)):
        return {**response,'status':'failed','error':'unexpected source schema','json':None}
    return response

def website_identity(org, page):
    numbers=set(re.sub(r'\s','',v) for v in re.findall(
        r'\b(?:organisasjons(?:nummer|nr\.?)|org\.?\s*(?:nr\.?|no\.?|nummer)|org\.?(?=\s*[:\-])|organisation\s+number|organization\s+number)[\s:\-–—]*(?:NO\s*)?([0-9]{3}[ \t]?[0-9]{3}[ \t]?[0-9]{3})(?![0-9])', page.text, re.I))
    numbers.update(re.sub(r'\s','',v) for v in re.findall(r'\bNO\s*([0-9]{3}\s?[0-9]{3}\s?[0-9]{3})\s*MVA\b',page.text,re.I))
    # Explicit labels with dotted groups or an optional period after the label.
    # Do not interpret phone/order numbers or arbitrary nine digits as identity.
    for value in re.findall(r'\b(?:organisasjons\s*(?:nummer|nr)|org\.?\s*(?:nr|no|nummer)|foretaksnummer|company\s+registration\s+(?:number|no))[.\s:\-]*(?:NO\s*)?([0-9]{3}[.\s]?[0-9]{3}[.\s]?[0-9]{3})(?![0-9])',page.text,re.I):
        number=re.sub(r'\D','',value)
        if valid_org(number):numbers.add(number)
    for item in objects(page.ld):
        if schema_types(item) & {'Organization','Corporation','LocalBusiness'}:
            for key in ('taxID','vatID'):
                value = str(item.get(key,''))
                match=re.fullmatch(r'(?:NO\s*)?([0-9]{3}\s?[0-9]{3}\s?[0-9]{3})(?:\s*MVA)?', value, re.I)
                if match: numbers.add(re.sub(r'\s','',match.group(1)))
    return 'exact' if numbers == {org} else 'conflict' if numbers else 'ambiguous'

def normalized(value):
    return re.sub(r'[^\w]+',' ',str(value).casefold()).strip()

def identity_excerpt(org,page):
    match=re.search(r'\s*'.join(re.escape(n) for n in org),page.text)
    if match:return page.text[max(0,match.start()-180):match.end()+180]
    # Structured identity remains available in the retained source, without
    # pretending an unrelated first paragraph is the identity evidence span.
    return None

def link_family(url):
    path=urlsplit(url).path.casefold()
    if re.search(r'nyhetsbrev|newsletter|\.pdf$|\.jpg$|\.png$',path): return None
    if re.search(r'kontakt|contact|personvern|privacy|beting|vilk|impressum|legal|om-oss|about',path): return 'identity'
    if re.search(r'karriere|career|jobb|jobbe|jobs|stilling|vacanc',path): return 'hiring'
    if re.search(r'news|nyheter|aktuelt|blog|presse|/20\d{2}/',path): return 'activity'
    return None

def article_detail(url):
    return bool(re.search(r'/(?:news|nyheter|aktuelt|blog|presse)/[^/]+|/20\d{2}/',urlsplit(url).path,re.I))

def social_profile(url):
    p=urlsplit(url);host=(p.hostname or '').removeprefix('www.')
    allowed={'linkedin.com','facebook.com','youtube.com','instagram.com','twitter.com','x.com','vimeo.com','tiktok.com'}
    if host not in allowed or p.path in ('','/'):return False
    if re.search(r'/(?:share|sharer|shareArticle|sharing|intent|plugins|widgets|login|watch|home|search)(?:[/.?]|$)',p.path,re.I):return False
    if host in {'twitter.com','x.com'} and re.search(r'/(?:status|statuses)/',p.path,re.I):return False
    if host=='instagram.com' and re.match(r'/(?:p|reel|reels|stories|explore)/',p.path,re.I):return False
    return True

def crawl_company(org, data, response, fetcher, *, registry_redirect_host=None, reserve_requests=0, seed_urls=()):
    """Explore distinct purposes and linked detail pages within the existing request cap."""
    home=Page(response.get('text',''),response['url']); host=urlsplit(response['url']).hostname
    pages=[];verified=[];seen={urlunsplit((*urlsplit(response['url'])[:4],''))};queue={};counts=collections.Counter();discovered=False
    def ingest(page,rsp):
        identity=website_identity(org,page)
        if identity=='conflict': return False
        pages.append((page,rsp,identity))
        if identity=='exact' or corroborated_site(data,page,registry_redirect_host): verified.append((page,rsp))
        for link in page.links:
            url=urlunsplit((*urlsplit(link['url'])[:4],''));family=link_family(url)
            if family is None:
                label=normalized(link['text'])
                if re.search(r'\b(kontakt|contact|personvern|privacy|om oss|about us)\b',label): family='identity'
            if family and urlsplit(url).scheme in ('https','http') and urlsplit(url).hostname==host and url not in seen:
                queue[url]=family
        return True
    if not ingest(home,response): return [],[]
    for url in seed_urls:
        p=urlsplit(url)
        if p.hostname==host and p.scheme in ('https','http') and not p.username and not p.password and link_family(url)=='identity' and url not in seen:
            queue[url]='identity'
    def discover():
        from site_discovery import xml_candidates
        origin=urlunsplit((*urlsplit(response['url'])[:2],'','',''))
        parser=getattr(fetcher,'robots',{}).get(origin)
        declared=parser.site_maps() if parser else []
        sources=list(dict.fromkeys((declared or [])[:2]+[origin+'/sitemap.xml']+home.feeds[:1]))
        used=set()
        while sources and len(used)<3 and fetcher.requests<fetcher.limit-(0 if verified else reserve_requests)-2:
            url=sources.pop(0)
            if url in used or urlsplit(url).hostname!=host:continue
            used.add(url); rsp=fetcher.get(url,site=True,raw=True)
            if rsp['status']!='available' or urlsplit(rsp['url']).hostname!=host:continue
            urls,maps=xml_candidates(rsp.get('text',''),rsp['url'],host)
            sources.extend(sorted(maps,key=lambda u:(not bool(re.search(r'post|page|news',u,re.I)),u)))
            for candidate in urls:
                family=link_family(candidate)
                if family and candidate not in seen:queue.setdefault(candidate,family)
    while len(seen)<9 and fetcher.requests<fetcher.limit-(0 if verified else reserve_requests):
        if not discovered and (not queue or (verified and len(seen)>=4)):
            discovered=True;discover()
        if not queue:break
        def rank(item):
            url,family=item
            base=({'hiring':0,'activity':1,'identity':5} if verified else {'identity':0,'hiring':5,'activity':6})[family]
            depth=len([s for s in urlsplit(url).path.split('/') if s])
            return (base+counts[family]*4, (-min(depth,3) if verified else depth),len(url),url)
        url,family=min(queue.items(),key=rank);del queue[url];seen.add(url);counts[family]+=1
        child=fetcher.get(url,site=True,raw=True)
        if child['status']!='available' or urlsplit(child['url']).hostname!=host: continue
        ingest(Page(child.get('text',''),child['url']),child)
    return verified,pages

def corroborated_site(data, page, registry_redirect_host=None):
    """Only registry-declared domains: name AND exact postal address corroboration.

    Email domains, group sites and name alone cannot satisfy this alternative.
    Explicit conflicting organisation numbers always take precedence.
    """
    if website_identity(str(data.get('organisasjonsnummer','')),page)=='conflict':return False
    registered=data.get('hjemmeside') or ''
    if not registered: return False
    registered=registered if '://' in registered else 'https://'+registered
    registered_host=(urlsplit(registered).hostname or '').casefold().removeprefix('www.')
    page_host=(urlsplit(page.url).hostname or '').casefold().removeprefix('www.')
    if registered_host!=page_host and registry_redirect_host!=page_host:
        return False
    name=normalized(data.get('navn',''))
    name=re.sub(r' (as|asa|sti)$','',name)
    text=' '+normalized(page.text)+' '
    if len(name)<8 or ' '+name+' ' not in text:return False
    for kind in ('forretningsadresse','postadresse'):
        address=data.get(kind) or {}
        street=next(iter(address.get('adresse') or []),''); postal=address.get('postnummer','')
        if street and postal and ' '+normalized(street)+' ' in text and re.search(r'(?<!\d)'+re.escape(postal)+r'(?!\d)',page.text):return True
    return False

def corroboration_evidence(data,page,entry_response):
    """Literal, reviewable name/address spans; never an unrelated opening excerpt."""
    stem=re.sub(r' (as|asa|sti)$','',normalized(data.get('navn','')))
    def span(value):
        pattern=r'\W+'.join(re.escape(t) for t in normalized(value).split())
        match=re.search(r'(?<!\w)'+pattern+r'(?!\w)',page.text,re.I) if pattern else None
        return {'start':match.start(),'end':match.end(),'text':page.text[match.start():match.end()]} if match else None
    name_span=span(stem)
    for kind in ('forretningsadresse','postadresse'):
        address=data.get(kind) or {};street=next(iter(address.get('adresse') or []),'');postal=address.get('postnummer','')
        street_span=span(street);postal_span=span(postal)
        if name_span and street_span and postal_span:
            return {'registered_name':data.get('navn'),'registered_website':data.get('hjemmeside'),
                    'requested_entry_url':entry_response.get('requested_url'),
                    'observed_entry_url':entry_response['url'],'address_kind':kind,
                    'registry_street':street,'registry_postcode':postal,
                    'literal_spans':[name_span,street_span,postal_span]}
    return None

def pick(data, *path):
    for key in path:
        if not isinstance(data,dict) or key not in data: return None
        data=data[key]
    return data

def claim(field, value, response, evidence, *, period=None, state=None, pointer=None, excerpt=None):
    status=state or response['status']
    if status=='available' and value is None: status='not_available'
    ids=[]
    if response.get('content_sha256'):
        eid=digest((response['url']+response['content_sha256']).encode())[:24]
        evidence[eid]={'id':eid, 'source_url':response['url'], 'retrieved_at':response['retrieved_at'],
            'content_sha256':response['content_sha256'], 'source_class':'official_registry' if response['url'].startswith(OFFICIAL+'/') else 'company_website' if response.get('identity_verified') else 'candidate_website',
            'retention':response.get('retention','source bytes retained in local cache')}
        if response.get('requested_url'):
            evidence[eid]['cache_file']=digest(response['requested_url'].encode())+'.json'
        if response.get('snapshot_file'): evidence[eid]['snapshot_file']=response['snapshot_file']
        if 'text' in response:
            evidence[eid]['retained_text_sha256']=digest(response['text'].encode())
        ids=[eid]
    return {'field':field, 'value':value if status=='available' else None, 'availability':status,
        'evidence_ids':ids, 'reporting_period':period, 'extraction_method':'deterministic-v2',
        'source_pointer':pointer, 'evidence_excerpt':excerpt}

def compare(old, new):
    # A temporary outage is an observation failure, not a new factual baseline.
    # Walk retained history newest first and compare with the last supported
    # value for each field, keeping its original evidence references.
    prior={}; snapshot=old; visited=set(); events=[]
    while isinstance(snapshot,dict) and id(snapshot) not in visited:
        visited.add(id(snapshot))
        if (new.get('organisation_number') and snapshot.get('organisation_number')
                and new['organisation_number']!=snapshot['organisation_number']):
            break
        for c in snapshot.get('claims',[]):
            if c.get('availability')=='available': prior.setdefault(c['field'],c)
        snapshot=snapshot.get('previous_snapshot')
    for c in new.get('claims',[]):
        p=prior.get(c['field'])
        if not p or c['availability']!='available' or p['availability']!='available': continue
        a,b=p['value'],c['value']
        if c['field'] in ('roles','locations','website.social_links','website.hiring','website.activity','website.contact_channels'):
            a=sorted(encode(x) for x in a); b=sorted(encode(x) for x in b)
        if a!=b or p.get('reporting_period')!=c.get('reporting_period'):
            events.append({'field':c['field'],'old_value':p['value'],'new_value':c['value'],
                'old_evidence_ids':p['evidence_ids'],'new_evidence_ids':c['evidence_ids'],
                'old_period':p.get('reporting_period'),'new_period':c.get('reporting_period')})
    return events

def synthesis(claims, changes=()):
    from insights import synthesize
    return synthesize(claims, changes)

def research(row, fetcher, previous=None, search=None):
    started=now(); tic=time.monotonic(); org=str(row.get('organisation_number','')); evidence={}; claims=[]; errors=[]
    output={'organisation_number':org,'claims':claims,'evidence':[], 'changes':[], 'errors':errors}
    def add(field, value, response, **kwargs): claims.append(claim(field,value,response,evidence,**kwargs))
    if not valid_org(org):
        raise ValueError('invalid organisation number checksum')
    base=OFFICIAL+'/enhetsregisteret/api/enheter/'+org
    entity=typed_json(fetcher.get(base),dict,'organisasjonsnummer'); data=entity.get('json') or {}
    if data.get('organisasjonsnummer') != org:
        entity={**entity,'status':'ambiguous' if entity['status']=='available' else entity['status']}; data={}
        errors.append({'source':base,'reason':'identity unavailable or mismatch'})
    for field,path in {
        'legal_name':('navn',), 'legal_form':('organisasjonsform','kode'),
        'employees':('antallAnsatte',), 'address':('forretningsadresse',),
        'industry':('naeringskode1',), 'activity':('aktivitet',),
        'founded':('stiftelsesdato',), 'bankrupt':('konkurs',),
        'registered_website':('hjemmeside',),
    }.items(): add(field,pick(data,*path),entity,pointer='/'+ '/'.join(path))
    # One source request per module, no retry storms or paid data.
    accounts=typed_json(fetcher.get(OFFICIAL+'/regnskapsregisteret/regnskap/'+org),list)
    records=accounts.get('json'); records=records if isinstance(records,list) else []
    matching=[r for r in records if isinstance(r,dict) and pick(r,'virksomhet','organisasjonsnummer')==org and r.get('regnskapstype')=='SELSKAP']
    latest=max(matching,key=lambda r:pick(r,'regnskapsperiode','tilDato') or '',default={})
    period=latest.get('regnskapsperiode')
    for field,path in {
        'revenue':('resultatregnskapResultat','driftsresultat','driftsinntekter','sumDriftsinntekter'),
        'net_income':('resultatregnskapResultat','aarsresultat'),
        'assets':('eiendeler','sumEiendeler'), 'equity':('egenkapitalGjeld','egenkapital','sumEgenkapital'),
        'currency':('valuta',),
    }.items(): add('financials.'+field,pick(latest,*path),accounts,period=period,
        pointer=('/'+str(records.index(latest))+'/'+ '/'.join(path)) if latest else None)
    history=[{'period':r.get('regnskapsperiode'),'currency':r.get('valuta'),
        'revenue':pick(r,'resultatregnskapResultat','driftsresultat','driftsinntekter','sumDriftsinntekter'),
        'net_income':pick(r,'resultatregnskapResultat','aarsresultat')} for r in sorted(matching,key=lambda r:pick(r,'regnskapsperiode','tilDato') or '')]
    add('financials.history',history or None,accounts,pointer='selected / items: organisation_number matches; regnskapstype=SELSKAP')
    roles=typed_json(fetcher.get(base+'/roller'),dict,'rollegrupper'); people=[]
    for group in (roles.get('json') or {}).get('rollegrupper',[]):
        for r in group.get('roller',[]):
            if r.get('avregistrert'): continue
            name=pick(r,'person','navn') or {}; company=r.get('enhet') or {}
            label=' '.join(name.get(k,'') for k in ('fornavn','mellomnavn','etternavn')).strip() or company.get('navn')
            people.append({'name':label,'role':pick(r,'type','kode'),'description':pick(r,'type','beskrivelse'),
                'organisation_number':company.get('organisasjonsnummer'),'effective_at':group.get('sistEndret')})
    add('roles',people,roles,pointer='/rollegrupper; active /roller only; names transformed')
    locations=typed_json(fetcher.get(OFFICIAL+'/enhetsregisteret/api/underenheter?overordnetEnhet='+org+'&size=100'),dict,'page')
    sites=[{'organisation_number':r.get('organisasjonsnummer'),'name':r.get('navn'),'address':r.get('beliggenhetsadresse')}
        for r in (pick(locations.get('json') or {},'_embedded','underenheter') or []) if r.get('overordnetEnhet')==org]
    add('locations',sites,locations,pointer='/_embedded/underenheter; overordnetEnhet matches input')
    if (pick(locations.get('json') or {},'page','totalPages') or 0)>1:
        errors.append({'source':locations['url'],'reason':'locations truncated at first 100; incomplete coverage'})
    from registry_discovery import registry_candidates,host_key
    leads=registry_candidates(org,data,pick(locations.get('json') or {},'_embedded','underenheter') or [])
    webstate={'url':'','status':'not_available','retrieved_at':now()}
    attempts=[]
    def candidates():
        for index,lead in enumerate(leads):yield lead['url'],lead['origin'],len(leads)-index-1+(bool(search)),[]
        if search and data.get('navn'):
            if hasattr(search,'iter_candidates'):
                for url,remaining,hints in search.iter_candidates(org,data['navn'],fetcher):yield url,'search',remaining,hints
            else:
                urls=search.discover(org,data['navn'],fetcher)
                for i,url in enumerate(urls):yield url,'search',len(urls)-i-1,[]
    for url,origin,remaining_leads,hints in candidates():
        started_requests=fetcher.requests
        response=fetcher.get(url,site=True,raw=True); webstate=response
        attempt={'url':url,'origin':origin,'fetch_state':response['status'],'resolved_url':response['url'],
                 'identity':'not_checked','pages_inspected':0,'requests':fetcher.requests-started_requests}
        attempts.append(attempt)
        if response['status']=='available':
            # Only an observed redirect from the declared entity URL extends
            # its domain anchor. Search, email and workplace URLs cannot do so.
            redirect_host=host_key(response['url']) if origin=='entity_website' and response.get('requested_url')==url else None
            verified,inspected=crawl_company(org,data,response,fetcher,registry_redirect_host=redirect_host,
                                            reserve_requests=6 if remaining_leads else 0,seed_urls=hints)
            attempt.update(identity='verified' if verified else 'not_established',pages_inspected=len(inspected),
                           requests=fetcher.requests-started_requests)
            if verified:
                verified=[(pg,{**rsp,'identity_verified':True}) for pg,rsp in verified]
                anchor,anchor_response=verified[0]
                # Same-host pages can inherit the established site identity, except conflicts.
                content_pages=[(pg,{**rsp,'identity_verified':True}) for pg,rsp,identity in inspected
                    if identity!='conflict' and urlsplit(rsp['url']).hostname==urlsplit(anchor_response['url']).hostname]
                method='explicit_org_number' if website_identity(org,anchor)=='exact' else 'registry_domain_name_and_postal_address'
                add('website.verified_url',response['url'],anchor_response,pointer=method,
                    excerpt=identity_excerpt(org,anchor) if method=='explicit_org_number' else anchor.text[:1500])
                if method!='explicit_org_number':
                    extra=claim('identity_anchor',org,entity,evidence)
                    claims[-1]['evidence_ids']+=extra['evidence_ids']
                    claims[-1]['identity_support']=corroboration_evidence(data,anchor,response)
                    claims[-1]['evidence_excerpt']=None
                # Identity may be proved on a privacy/contact page. Describe the
                # homepage instead of publishing that legal page's boilerplate.
                description_page,description_response=content_pages[0]
                description=description_page.description or description_page.text[:500]
                add('website.description',description or None,description_response,
                    pointer='meta[name=description]' if description_page.description else 'visible homepage text excerpt',excerpt=description)
                social_by_url={};social_sources=[]
                for pg,rsp in content_pages:
                    for link in pg.links:
                        if social_profile(link['url']) and not link.get('third_party_context'):
                            social_url=urlunsplit((*urlsplit(link['url'])[:4],''))
                            social_by_url[social_url]={'url':social_url,'text':link['text'].strip()};social_sources.append(rsp)
                social=list(social_by_url.values())
                add('website.social_links',social or None,anchor_response,pointer='a[href]; sharing and identified third-party contexts excluded; destination ownership not separately checked')
                for rsp in social_sources:
                    extra=claim('supporting',None,rsp,evidence)
                    claims[-1]['evidence_ids']=list(dict.fromkeys(claims[-1]['evidence_ids']+extra['evidence_ids']))
                from contacts import contact_links
                contacts=[];contact_sources=[];seen_contacts=set()
                for pg,rsp in content_pages:
                    for item in contact_links(pg):
                        key=(item['type'],item['value'])
                        if key not in seen_contacts and len(contacts)<10:
                            contacts.append(item);seen_contacts.add(key);contact_sources.append(rsp)
                add('website.contact_channels',contacts or None,anchor_response,
                    pointer='literal mailto/tel links on verified company pages; third-party contexts excluded; ownership/use not independently checked')
                for rsp in contact_sources:
                    extra=claim('supporting',None,rsp,evidence)
                    claims[-1]['evidence_ids']=list(dict.fromkeys(claims[-1]['evidence_ids']+extra['evidence_ids']))
                for field,types in [('hiring',{'JobPosting'}),('activity',{'NewsArticle','Article','BlogPosting'})]:
                    items=[]; evidence_responses=[]
                    for pg,rsp in content_pages:
                        candidates=list(objects(pg.ld))
                        if field=='activity' and article_detail(rsp['url']) and pg.meta.get('article:published_time'):
                            candidates.append({'@type':'NewsArticle','headline':pg.meta.get('og:title') or pg.title,'datePublished':pg.meta['article:published_time']})
                        if (field=='activity' and article_detail(rsp['url']) and len(pg.headings)==1
                                and len(set(pg.times))==1):
                            candidates.append({'@type':'NewsArticle','headline':pg.headings[0],
                                'datePublished':pg.times[0]})
                        for obj in candidates:
                            if schema_types(obj) & types:
                                if field=='activity' and not (schema_types(obj)&{'NewsArticle','BlogPosting'}) and not article_detail(rsp['url']):
                                    continue
                                title=obj.get('title') or obj.get('headline')
                                date=obj.get('datePosted') or obj.get('datePublished')
                                if not isinstance(title,str) or not isinstance(date,str): continue
                                try:
                                    if dt.date.fromisoformat(date[:10])>dt.date.fromisoformat(rsp['retrieved_at'][:10]): continue
                                except ValueError: continue
                                if field=='hiring':
                                    expiry=obj.get('validThrough')
                                    if isinstance(expiry,str):
                                        try:
                                            if dt.date.fromisoformat(expiry[:10])<dt.date.fromisoformat(rsp['retrieved_at'][:10]): continue
                                        except ValueError: continue
                                    employer=pick(obj,'hiringOrganization','name')
                                    legal=re.sub(r' (as|asa|sti)$','',normalized(data.get('navn','')))
                                    if employer and re.sub(r' (as|asa|sti)$','',normalized(employer))!=legal: continue
                                item={'title':title,'date':date,'url':rsp['url']}
                                if field=='hiring': item.update(valid_through=obj.get('validThrough'),status='published_posting; application availability not independently checked')
                                if not any(i['url']==item['url'] and i['date'][:10]==item['date'][:10] for i in items): items.append(item)
                                evidence_responses.append(rsp)
                    add('website.'+field,items or None,anchor_response,pointer=('JSON-LD, article:published_time, or a single h1/time[datetime] on detail pages' if field=='activity' else 'script[type=application/ld+json]; JobPosting'))
                    for rsp in evidence_responses:
                        extra=claim('supporting',None,rsp,evidence)
                        claims[-1]['evidence_ids']=list(dict.fromkeys(claims[-1]['evidence_ids']+extra['evidence_ids']))
                break
            else:
                errors.append({'source':response['url'],'reason':'exact legal entity not established; no website facts published'})
    for field in ('website.verified_url','website.description','website.social_links','website.hiring','website.activity','website.contact_channels'):
        if not any(c['field']==field for c in claims): add(field,None,webstate,state=webstate['status'] if webstate['status']!='available' else 'ambiguous')
    output['evidence']=list(evidence.values())
    output['website_attempts']=attempts
    output['changes']=compare(previous or {},output)
    output['previous_snapshot']=previous if previous else None
    output['refresh']={'previous_snapshot_sha256':digest(encode(previous).encode()) if previous else None,
        'mode':'offline_replay' if fetcher.replay else 'fresh' if fetcher.fresh else 'cache_allowed',
        'cache_declared':True,'changed_fields':[c['field'] for c in output['changes']]}
    if fetcher.registry_snapshot is not None:
        output['refresh']['registry_snapshot_sha256']=fetcher.registry_snapshot.artifact_sha256
    output['source_snapshots']=[{'evidence_id':e['id'],'cache_file':e.get('cache_file'),
        'snapshot_file':e.get('snapshot_file'),
        'retrieved_at':e['retrieved_at'],'content_sha256':e['content_sha256'],
        'retained_text_sha256':e.get('retained_text_sha256')} for e in output['evidence']]
    output['synthesis']=synthesis(claims, output['changes'])
    for rsp in (entity,accounts,roles,locations):
        if rsp['status'] in ('failed','blocked','ambiguous'):
            errors.append({'source':rsp['url'],'reason':rsp.get('error',rsp['status'])})
    output['summary']={'name':data.get('navn'), 'supported_fields':[c['field'] for c in claims if c['availability']=='available'],
        'unknown_fields':[c['field'] for c in claims if c['availability']!='available'], 'material_changes':len(output['changes'])}
    output['run']={'started_at':started,'completed_at':now(),'terminal_status':'completed','version':VERSION}
    output['operations']={'requests':fetcher.requests,'cache_hits':fetcher.hits,'runtime_ms':round((time.monotonic()-tic)*1000),'third_party_cost_usd':getattr(fetcher,'discovery',{}).get('paid_cost_usd',0)}
    if hasattr(fetcher,'discovery'): output['discovery']=fetcher.discovery
    return output

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--input',required=True); p.add_argument('--output',required=True)
    p.add_argument('--cache',default='cache'); p.add_argument('--previous')
    mode=p.add_mutually_exclusive_group();mode.add_argument('--replay',action='store_true');mode.add_argument('--fresh',action='store_true')
    p.add_argument('--workers',type=int,default=4)
    p.add_argument('--search',choices=['none','tavily'],default='none')
    p.add_argument('--search-credit-limit',type=int,default=100)
    p.add_argument('--search-strategy',choices=['legacy','name_focus','adaptive'],default='legacy')
    p.add_argument('--registry-snapshot',help='Frozen registry responses in the documented local JSONL interchange format')
    args=p.parse_args(); rows=[json.loads(x) for x in Path(args.input).read_text().splitlines() if x.strip()]
    registry_snapshot=None
    if args.registry_snapshot:
        from frozen_registry import FrozenRegistry
        registry_snapshot=FrozenRegistry(args.registry_snapshot)
    search=None
    if args.search=='tavily':
        from search import TavilySearch
        search=TavilySearch(args.cache,args.search_credit_limit,strategy=args.search_strategy)
        if not args.replay and not search.key: p.error('TAVILY_API_KEY is required for live search; no account was created')
    prior={r['organisation_number']:r for r in (json.loads(x) for x in Path(args.previous).read_text().splitlines())} if args.previous else {}
    output=Path(args.output); output.parent.mkdir(parents=True,exist_ok=True); start=time.monotonic()
    def work(row):
        fetcher=Fetcher(args.cache,replay=args.replay,fresh=args.fresh,registry_snapshot=registry_snapshot)
        try: return research(row,fetcher,prior.get(str(row.get('organisation_number',''))),search)
        except Exception as error:
            return {'organisation_number':str(row.get('organisation_number','')),'run':{'terminal_status':'failed','completed_at':now()},
                'claims':[],'evidence':[],'changes':[],'errors':[{'reason':type(error).__name__+': '+str(error)}],
                'operations':{'requests':fetcher.requests,'cache_hits':fetcher.hits,'third_party_cost_usd':getattr(fetcher,'discovery',{}).get('paid_cost_usd',0)}}
    results=[]
    with output.open('w') as target, concurrent.futures.ThreadPoolExecutor(max_workers=max(1,min(8,args.workers))) as pool:
        for i,result in enumerate(pool.map(work,rows),1):
            results.append(result); target.write(encode(result)+'\n'); target.flush()
            if i%10==0: print(encode({'completed':i,'total':len(rows)}),flush=True)
    report={'inputs':len(rows),'outputs':len(results),'failed':sum(r['run']['terminal_status']=='failed' for r in results),
        'requests':sum(r['operations']['requests'] for r in results),'runtime_seconds':round(time.monotonic()-start,2),
        'third_party_cost_usd':None if search and search.attempts else 0,
        'search_request_attempts':search.attempts if search else 0,
        'search_basic_credit_upper_bound':search.attempts if search else 0,
        'coverage':dict(collections.Counter(c['field'] for r in results for c in r['claims'] if c['availability']=='available')),
        'source_statuses':dict(collections.Counter(c['availability'] for r in results for c in r['claims'])),
        'official_score':None,'replay':args.replay,
        'registry_snapshot_sha256':registry_snapshot.artifact_sha256 if registry_snapshot else None}
    output.with_suffix('.report.json').write_text(json.dumps(report,indent=2)); print(json.dumps(report,indent=2))

if __name__=='__main__': main()
