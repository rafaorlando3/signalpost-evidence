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
import io
import zlib
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
    return p, host, port, sorted(addresses,key=lambda a:(ipaddress.ip_address(a).version,a))[0]

class Fetcher:
    locks = collections.defaultdict(threading.Lock)
    host_last = {}
    host_retry_not_before = {}

    def __init__(self, directory, *, replay=False, fresh=False, limit=20, deadline=90, registry_snapshot=None, public_jobs=True, public_search=None):
        self.directory = Path(directory); self.directory.mkdir(parents=True, exist_ok=True)
        self.replay, self.fresh = replay, fresh
        self.limit = limit; self.end = time.monotonic()+deadline
        self.requests = 0; self.hits = 0; self.robots = {}; self.records = []
        self.robots_observations = {}
        self.registry_snapshot=registry_snapshot
        self.public_jobs=public_jobs
        self.public_search=public_search

    def request_headers(self,url):
        from transport_policy import request_headers
        return request_headers(url,UA)

    def store_observation(self,url,result):
        """Persist failures for replay without treating them as factual evidence."""
        result.setdefault('requested_url',url)
        self.retain(result)
        path=self.directory/(digest(url.encode())+'.json')
        temporary=path.with_suffix('.'+uuid.uuid4().hex+'.tmp')
        temporary.write_text(encode(result));temporary.replace(path)
        return result

    def get(self, url, *, site=False, raw=False, _redirect_depth=0):
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
                code=response.get('status_code',0)
                if 200<=code<300:
                    parser.parse(response.get('text', '').splitlines())
                    policy='rules'
                elif 400<=code<500:
                    # RFC9309 2.3.1.3: an unavailable robots resource does not
                    # impose a site-wide ban. Actual pages still undergo the
                    # ordinary status, URL, TLS, IP and request-budget checks.
                    parser.parse([])
                    policy='unavailable_allow'
                else:
                    # RFC9309 2.3.1.4: network errors and 5xx stay fail-closed.
                    parser.parse(['User-agent: *', 'Disallow: /'])
                    policy='unreachable_disallow'
                self.robots[origin] = parser
                self.robots_observations[origin]={
                    'origin':origin,'robots_url':origin+'/robots.txt',
                    'response_url':response.get('url'),'status_code':code,
                    'fetch_state':response.get('status'),'policy_state':policy,
                    'retrieved_at':response.get('retrieved_at'),
                    'content_sha256':response.get('content_sha256'),
                    'error':response.get('error'),'error_kind':response.get('error_kind'),
                    'response_headers':response.get('response_headers'),
                    'protection':response.get('protection'),
                    'transport_attempts':response.get('transport_attempts')}
            if not self.robots[origin].can_fetch(UA, url):
                policy=self.robots_observations.get(origin,{}).get('policy_state')
                return self.failure(url, 'blocked', 'robots unreachable; complete disallow' if policy=='unreachable_disallow' else 'robots rules disallow requested URL')
        path = self.directory/(digest(url.encode())+'.json')
        if path.exists() and (self.replay or not self.fresh):
            result = json.loads(path.read_text())
            if self.replay or not result.get('observation_failure'):
                self.hits += 1;self.retain(result)
                self.records.append(result); return result
        if self.replay:
            return self.failure(url, 'failed', 'missing replay fixture')
        current = url
        result = None; retried=False;trace=[]
        for _ in range(4):
            if self.requests >= self.limit or time.monotonic() >= self.end:
                return self.failure(current, 'failed', 'request/time budget exhausted')
            connection=None
            try:
                p, host, port, address = safe_url(current)
                with self.locks[host]:
                    pause = max(0, self.host_last.get(host, 0)+0.25-time.monotonic(),self.host_retry_not_before.get(host,0)-time.monotonic())
                    if pause>self.end-time.monotonic()-0.1:
                        result=self.failure(current,'blocked','Retry-After exceeds remaining time budget')
                        result.update(observation_failure=True,error_kind='retry_after_deferred',transport_attempts=trace)
                        return self.store_observation(url,result)
                    if pause: time.sleep(pause)
                    self.host_last[host] = time.monotonic()
                self.requests += 1
                timeout = max(0.1, min(16 if retried and urlsplit(current).path=='/robots.txt' else 8, self.end-time.monotonic()))
                connection = (http.client.HTTPSConnection(host, port, timeout=timeout, context=ssl.create_default_context())
                    if p.scheme == 'https' else http.client.HTTPConnection(host, port, timeout=timeout))
                # Pin the validated address while retaining original TLS hostname verification.
                connection._create_connection = lambda *_args, **_kw: socket.create_connection((address, port), timeout)
                connection.request('GET', (p.path or '/')+('?' + p.query if p.query else ''),
                    headers=self.request_headers(current))
                response = connection.getresponse(); status = response.status
                from transport_policy import retained_headers,retry_delay,protection_markers
                headers=retained_headers(response)
                trace.append({'url':current,'status_code':status,'response_headers':headers,'timeout_seconds':timeout})
                transient=status in (429,503) or (host=='data.brreg.no' and status in (500,502,504))
                if transient:
                    delay=retry_delay(headers.get('retry-after'))
                    self.host_retry_not_before[host]=max(self.host_retry_not_before.get(host,0),time.monotonic()+delay)
                    if not retried and self.requests<self.limit and delay<self.end-time.monotonic()-0.1:
                        connection.close();retried=True;trace[-1]['retry']='one bounded retry after host cooldown';continue
                    trace[-1]['retry']='not retried: retry or time/request budget exhausted'
                if status in (301, 302, 303, 307, 308):
                    location = response.getheader('Location'); connection.close()
                    if not location: return self.failure(current, 'failed', 'redirect missing location')
                    target = urljoin(current, location)
                    if site and urlsplit(target).netloc != urlsplit(current).netloc:
                        if _redirect_depth>=3:
                            result=self.failure(current,'blocked','redirect limit');result.update(observation_failure=True,error_kind='redirect_limit',transport_attempts=trace)
                            return self.store_observation(url,result)
                        redirected={**self.get(target,site=True,raw=raw,_redirect_depth=_redirect_depth+1),'requested_url':url}
                        redirected['transport_attempts']=trace+redirected.get('transport_attempts',[])
                        self.retain(redirected)
                        temporary=path.with_suffix('.'+uuid.uuid4().hex+'.tmp')
                        temporary.write_text(encode(redirected));temporary.replace(path)
                        return redirected
                    current = target; continue
                data = response.read(2_000_001); connection.close()
                if len(data) > 2_000_000:
                    result=self.failure(current,'blocked','response size limit');result.update(observation_failure=True,error_kind='response_size_limit',response_headers=headers,transport_attempts=trace)
                    return self.store_observation(url,result)
                wire_digest=digest(data)
                coding=response.getheader('Content-Encoding')
                coding=coding.strip().casefold() if isinstance(coding,str) else 'identity'
                if coding=='gzip':
                    with gzip.GzipFile(fileobj=io.BytesIO(data)) as decoded:
                        data=decoded.read(2_000_001)
                elif coding=='deflate':
                    decoder=zlib.decompressobj();data=decoder.decompress(data,2_000_001)
                elif coding not in ('identity',''):
                    return self.failure(current,'blocked','unsupported content encoding')
                if len(data)>2_000_000:
                    result=self.failure(current,'blocked','decoded response size limit');result.update(observation_failure=True,error_kind='decoded_response_size_limit',response_headers=headers,transport_attempts=trace)
                    return self.store_observation(url,result)
                charset = response.headers.get_content_charset() or 'utf-8'
                text = data.decode(charset, errors='replace')
                state = 'available' if status == 200 else 'not_available' if status in (404,410) else 'blocked' if status in (401,403,429) else 'failed'
                result = {'url':current, 'requested_url':url, 'status':state, 'status_code':status,
                    'retrieved_at':now(), 'content_sha256':wire_digest, 'text':text,
                    'response_headers':headers,'protection':protection_markers(headers,text),'transport_attempts':trace}
                if coding not in ('identity',''):
                    result.update(content_encoding=coding,decoded_content_sha256=digest(data))
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
            except (OSError, ValueError, EOFError, zlib.error, http.client.HTTPException) as error:
                if connection is not None: connection.close()
                result = self.failure(current, 'failed', type(error).__name__)
                from transport_policy import error_kind
                kind=error_kind(error);trace.append({'url':current,'status_code':0,'error':type(error).__name__,'error_kind':kind})
                result.update(observation_failure=True,error_kind=kind,transport_attempts=trace)
                retryable=(isinstance(error,(OSError,http.client.HTTPException)) and urlsplit(current).hostname=='data.brreg.no') or (urlsplit(current).path=='/robots.txt' and kind in {'timeout','tls','tls_certificate'})
                if retryable and not retried:
                    retried=True;continue
                return self.store_observation(url,result)
        result=self.failure(current,'blocked','redirect limit')
        result.update(observation_failure=True,error_kind='redirect_limit',transport_attempts=trace)
        return self.store_observation(url,result)

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
        self.url=url; self.raw_html=text; self.parts=[]; self.links=[]; self.ld=[]; self.skip=0; self.script=None
        self.title=''; self.in_title=False; self.description=''; self.anchor=None;self.meta={};self.post_container=False;self.editorial_listing=False
        self.headings=[];self.heading=None;self.times=[];self.feeds=[];self.link_context=[];self.editorial_scopes=[];self.comment_scopes=[]
        self.content_headings=[];self.content_times=[];self.main_headings=[];self.main_times=[];self.semantic_headings=[];self.heading_is_semantic=False;self.heading_is_main=False;self.heading_is_content=False;self.body_parts=[];self.post_parts=[];self.main_parts=[]
        self.footer_parts=[];self.paragraphs=[];self.paragraph=None;self.paragraph_is_content=False
        self.publication_marker=False;self.publication_marker_source=text
        self.feed(text)

    def content_scope(self):
        # A post's own <article><header> is content. Site navigation headers
        # remain chrome; merely nesting an article inside a global header does
        # not turn that global header into a publication source.
        if self.comment_scopes:return False
        tags=[t for t,_ in self.link_context]
        if any(t in {'head','title','nav','footer','aside','form','dialog'} for t in tags):return False
        for index,tag in enumerate(tags):
            if tag=='header' and 'article' not in tags[:index] and not any(depth<index for depth in self.editorial_scopes):return False
        return True

    def handle_starttag(self, tag, attrs):
        a=dict(attrs)
        if not self.publication_marker:
            classes=set((a.get('class') or '').split())
            self.publication_marker=bool(
                (tag=='span' and ({'meta-date','date','published'}<=classes or 'meta-text' in classes)) or
                (tag=='div' and 'publish-date--article' in classes) or
                (tag=='p' and 'postInfoText' in classes))
        context=' '.join((a.get(k) or '') for k in ('class','id','aria-label','title','data-sentry-component','data-sentry-source-file'))
        from site_discovery import scoped_context
        context=scoped_context(tag,context)
        post_context=re.sub(r'(?<=[a-z])(?=[A-Z])',' ',a.get('class') or '').replace('_',' ')
        if tag=='article' and re.search(r'(?:^|\s)type-post(?:\s|$)|\bsingle[ -]+post\b',post_context,re.I):self.post_container=True
        # WordPress and Squarespace mark an individual editorial view on body,
        # even when its content uses div/main instead of article.type-post.
        # A blog listing, static page or homepage is not a detail view.
        if tag=='body':
            classes=set(post_context.casefold().split())
            single_view='single-post' in classes or {'view-item','collection-type-blog'}<=classes
            self.editorial_listing=bool(classes & {'blog','archive','search'}) or (not single_view and bool(re.search(r'/(?:Blog|CollectionPage|SearchResultsPage)\b',a.get('itemtype') or '')))
            if urlsplit(self.url).path.rstrip('/') and ('single-post' in classes or {'view-item','collection-type-blog'}<=classes):
                self.post_container=True
        if tag=='main' and 'posts-entry' in post_context.split() and article_detail(self.url):self.post_container=True
        third_party=(self.link_context[-1][1] if self.link_context else False) or bool(re.search(r'sponsor|partner|customer|testimonial|shar(?:e|ing)|author|agency|webdesign|site-credit|powered-by|theme-credit',context,re.I))
        if tag not in {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}:
            self.link_context.append((tag,third_party))
        if tag in {'article','div','section','ol','ul','li'} and any(re.fullmatch(r'(?:comments?(?:[-_][\w]+)?|wp-block-post-comments(?:[-_][\w]+)?)',token,re.I) for token in ((a.get('class') or '')+' '+(a.get('id') or '')).split()):
            self.comment_scopes.append(len(self.link_context)-1)
        if self.post_container and tag in {'main','div','section'} and self.content_scope() and re.search(r'(?:^|\s)(?:entry-content|post-content|wp-block-post-content|posts-entry)(?:\s|$)',a.get('class') or '',re.I):
            self.editorial_scopes.append(len(self.link_context)-1)
        if tag=='img' and self.anchor and re.search(r'sponsor|partner|customer',(a.get('alt') or ''),re.I):
            self.anchor['third_party_context']=True
        if tag in ('script','style','noscript'):
            self.skip += 1
            if tag=='script' and a.get('type')=='application/ld+json': self.script=[]
        if tag=='p':
            self.paragraph=''
            self.paragraph_is_content=not self.skip and not third_party and self.content_scope()
        if tag=='title': self.in_title=not bool(self.title)  # first document title; never concatenate distinct title nodes
        if tag=='h1':
            self.heading=''
            self.heading_is_content=self.content_scope()
            self.heading_is_main=self.heading_is_content and any(t in {'article','main'} for t,_ in self.link_context)
            self.heading_is_semantic=self.heading_is_content and 'headline' in (a.get('itemprop') or '').split()
        if tag=='time' and a.get('datetime'):
            semantic=((a.get('itemprop') or '')+' '+(a.get('class') or '')).casefold()
            if re.search(r'\b(datepublished|published|entry-date)\b',semantic) and not re.search(r'updated|modified',semantic):
                self.times.append(a['datetime'])
                if self.content_scope():
                    self.content_times.append(a['datetime'])
                    if any(t in {'article','main'} for t,_ in self.link_context):self.main_times.append(a['datetime'])
        if tag=='link' and 'alternate' in (a.get('rel') or '').split() and a.get('type') in ('application/rss+xml','application/atom+xml') and a.get('href'):
            self.feeds.append(urljoin(self.url,a['href']))
        if tag=='meta' and (a.get('name') or '').lower()=='description': self.description=a.get('content') or ''
        if tag=='meta' and (a.get('property') or a.get('name')):
            self.meta[(a.get('property') or a.get('name')).lower()]=a.get('content') or ''
        if tag=='div' and 'fb-page' in (a.get('class') or '').split() and a.get('data-href'):
            try:self.links.append({'url':urljoin(self.url,a['data-href']),'text':'Facebook page widget','third_party_context':third_party,'in_navigation':False,'source_kind':'fb_page_widget'})
            except ValueError:pass
        if tag=='a' and a.get('href'):
            try:self.anchor={'url':urljoin(self.url,a['href']), 'text':'','third_party_context':third_party,
                'in_navigation':any(t in {'nav','header','footer','aside'} for t,_ in self.link_context)
                    or bool(re.search(r'(?<![\w-])(?:nav-link|dropdown-item|menu-link)(?![\w-])',a.get('class') or '',re.I))}
            except ValueError:self.anchor=None

    def handle_endtag(self, tag):
        for i in range(len(self.link_context)-1,-1,-1):
            if self.link_context[i][0]==tag:
                del self.link_context[i:]
                self.editorial_scopes=[depth for depth in self.editorial_scopes if depth<len(self.link_context)]
                self.comment_scopes=[depth for depth in self.comment_scopes if depth<len(self.link_context)]
                break
        if tag in ('script','style','noscript'):
            if self.script is not None and tag=='script':
                try: self.ld.append(json.loads(''.join(self.script)))
                except ValueError: pass
                self.script=None
            self.skip=max(0,self.skip-1)
        if tag=='p' and self.paragraph is not None:
            paragraph=re.sub(r'\s+',' ',self.paragraph).strip()
            if self.paragraph_is_content and paragraph:self.paragraphs.append(paragraph)
            self.paragraph=None
        if tag=='title': self.in_title=False
        if tag=='h1' and self.heading is not None:
            heading=re.sub(r'\s+',' ',self.heading).strip()
            self.headings.append(heading)
            if self.heading_is_content:self.content_headings.append(heading)
            if self.heading_is_main:self.main_headings.append(heading)
            if self.heading_is_semantic:self.semantic_headings.append(heading)
            self.heading=None
        if tag=='a' and self.anchor:
            # Visible share actions can link directly to profile URLs. Ordinary
            # footer/follow links remain declarations, not proof of ownership.
            if re.search(r'^(?:share(?:\s|$)|del(?:\s+p[åa]\s)|dela(?:\s|$)|teilen(?:\s|$))',
                         self.anchor['text'].strip(), re.I):
                self.anchor['third_party_context']=True
            self.links.append(self.anchor); self.anchor=None

    def handle_data(self, value):
        if self.script is not None: self.script.append(value)
        if self.in_title: self.title += value
        if not self.skip:
            if self.heading is not None:self.heading+=value+' '
            if self.paragraph is not None:self.paragraph+=value+' '
            self.parts.append(value)
            if any(t=='footer' for t,_ in self.link_context):self.footer_parts.append(value)
            if self.content_scope():
                self.body_parts.append(value)
                if any(t=='article' for t,_ in self.link_context) or self.editorial_scopes:self.post_parts.append(value)
                if any(t=='main' for t,_ in self.link_context):self.main_parts.append(value)
            if self.anchor: self.anchor['text'] += value

    @property
    def article_parts(self):return self.post_parts or self.main_parts or self.body_parts

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


def site_operator_identity(org, page, data=None, site_url=None):
    """Resolve local JSON-LD WebSite publisher/operator assertions only.

    Article publishers, sponsors and parent/subOrganization links do not declare
    the site's operator. A different legal name without an ID is unresolved,
    not proof that two legally distinct companies exist.
    """
    data=data or {};site_url=site_url or page.url
    records=[];by_id={}
    def walk(value, script, pointer):
        if isinstance(value,dict):
            records.append((value,script,pointer))
            identifier=value.get('@id')
            if isinstance(identifier,str):
                key=urljoin(page.url,identifier)
                by_id.setdefault(key,[]).append((value,script,pointer))
            for key,item in value.items():
                escaped=str(key).replace('~','~0').replace('/','~1')
                walk(item,script,pointer+'/'+escaped)
        elif isinstance(value,list):
            for index,item in enumerate(value):walk(item,script,pointer+'/'+str(index))
    for index,value in enumerate(page.ld):walk(value,index,'')
    def current_site(value):
        if not isinstance(value,str) or not value.strip():return False
        try:
            p=urlsplit(urljoin(page.url,value));q=urlsplit(site_url)
            if (p.scheme not in {'http','https'} or p.username or p.password
                    or p.port not in (None,80,443)
                    or (p.hostname or '').casefold().removeprefix('www.') !=
                       (q.hostname or '').casefold().removeprefix('www.')):
                return False
            prefix=p.path.rstrip('/')
            return not prefix or q.path.rstrip('/')==prefix or q.path.startswith(prefix+'/')
        except ValueError:return False
    def resolve(value, script, pointer):
        if isinstance(value,str):
            return by_id.get(urljoin(page.url,value),[])
        if not isinstance(value,dict):return []
        reference=value.get('@id')
        resolved=by_id.get(urljoin(page.url,reference),[]) if isinstance(reference,str) else []
        if resolved:
            # Inspect all local definitions; never pick an arbitrary winner
            # when the same @id has conflicting corporate identifiers.
            return [*resolved,(value,script,pointer)]
        return [(value,script,pointer)]
    def number(value):
        if type(value) is int:value=str(value)
        if not isinstance(value,str):return None
        match=re.fullmatch(r'(?:NO\s*)?([0-9]{3}[.\s]?[0-9]{3}[.\s]?[0-9]{3})(?:\s*MVA)?',
                           value.strip(),re.I)
        result=re.sub(r'\D','',match.group(1)) if match else None
        return result if result and valid_org(result) else None
    def operator_numbers(operator):
        numbers=set()
        for field in ('taxID','vatID'):
            found=number(operator.get(field))
            if found:numbers.add(found)
        identifiers=operator.get('identifier',[])
        if not isinstance(identifiers,list):identifiers=[identifiers]
        allowed={'organisasjonsnummer','organisasjonsnr','orgnr','noorgnr',
                 'organizationnumber','organisationnumber',
                 'norwegianorganizationnumber','norwegianorganisationnumber'}
        for identifier in identifiers:
            if not isinstance(identifier,dict):continue
            label=re.sub(r'[^a-z0-9]','',str(identifier.get('propertyID','')).casefold())
            if label in allowed:
                found=number(identifier.get('value'))
                if found:numbers.add(found)
        return sorted(numbers)
    proofs=[];states=[]
    expected=normalized(data.get('navn',''))
    for website,script,pointer in records:
        if 'WebSite' not in schema_types(website):continue
        # An explicit URL governs the WebSite binding, even when malformed
        # or foreign. A local fragment must never override that declaration.
        location=website['url'] if 'url' in website else website.get('@id')
        declared=location if current_site(location) else None
        if declared is None:continue
        for relationship in ('publisher','operator'):
            operators=website.get(relationship,[])
            if not isinstance(operators,list):operators=[operators]
            for index,value in enumerate(operators):
                reference=pointer+'/'+relationship+('/'+str(index) if isinstance(website.get(relationship),list) else '')
                for operator,operator_script,operator_pointer in resolve(value,script,reference):
                    numbers=operator_numbers(operator)
                    legal_name=operator.get('legalName')
                    legal_name=legal_name if isinstance(legal_name,str) else None
                    if numbers and valid_org(org):
                        state='target' if set(numbers)=={org} else 'different'
                    elif legal_name and expected and normalized(legal_name)!=expected:
                        state='unresolved'
                    else:
                        # Matching names alone are not new identity proof. Unknown
                        # operator metadata does not veto the baseline checks.
                        continue
                    proof={'relationship':relationship,'website_url':urljoin(page.url,declared),
                        'website_script_index':script,'website_json_pointer':pointer,
                        'operator_script_index':operator_script,'operator_json_pointer':operator_pointer,
                        'organisation_numbers':numbers,'legal_name':legal_name,
                        'source_url':page.url}
                    if proof not in proofs:
                        if len(proofs)>=20:
                            return {'state':'unresolved','reason':'operator assertion limit exceeded; own-entity attribution unresolved',
                                    'operators':proofs}
                        proofs.append(proof)
                    states.append(state)
    if 'different' in states:
        return {'state':'different','reason':'current WebSite declares an operator organisation number different from the requested entity',
                'operators':proofs}
    if 'unresolved' in states:
        return {'state':'unresolved','reason':'current WebSite declares a different legal name without an organisation number; own-entity operator is unresolved',
                'operators':proofs}
    if 'target' in states:
        return {'state':'target','reason':'current WebSite explicitly declares the requested organisation as operator',
                'operators':proofs}
    # Literal legal-page owner declarations are also role-specific. A VAT
    # number elsewhere in a page (customer, sponsor or product) is insufficient.
    if re.search(r'/(?:imprint|impressum|legal)(?:/|$)',urlsplit(page.url).path,re.I):
        body=re.sub(r'\s+',' ',' '.join(page.main_parts or page.body_parts))
        match=re.search(r'(?:Eieren av dette nettstedet er|The owner of this website is)\s*:\s*(.{1,350}?)\s+MVA\s*ID\s*:\s*(?:NO\s*)?(\d{3}[.\s]?\d{3}[.\s]?\d{3})(?!\d)',body,re.I)
        if match:
            owner_number=re.sub(r'\D','',match[2])
            if valid_org(owner_number):
                own_name=normalized(match[1]);expected=normalized(data.get('navn',''))
                state=('different' if owner_number!=org else 'target' if expected and
                       (own_name==expected or own_name.startswith(expected+' ')) else 'unresolved')
                return {'state':state,'reason':'literal legal-page website-owner declaration',
                    'operators':[{'relationship':'literal_site_owner','organisation_numbers':[owner_number],
                        'source_url':page.url,'evidence_excerpt':match[0]}]}
    return {'state':'absent','reason':'no conflicting or exact operator assertion for this WebSite','operators':[]}

def website_identity(org, page, data=None, *, site_url=None):
    operator=site_operator_identity(org,page,data,site_url)
    if operator['state']=='target':return 'exact'
    if operator['state'] in ('different','unresolved'):return 'ambiguous'
    numbers=set(re.sub(r'\s','',v) for v in re.findall(
        r'\b(?:organisasjons(?:nummer|nr\.?)|org\.?\s*(?:nr\.?|no\.?|nummer)|org\.?(?=\s*[:\-])|organisation\s+number|organization\s+number)[\s:\-–—]*(?:NO\s*)?([0-9]{3}[ \t]?[0-9]{3}[ \t]?[0-9]{3})(?![0-9])', page.text, re.I))
    numbers.update(re.sub(r'\s','',v) for v in re.findall(r'\bNO\s*([0-9]{3}\s?[0-9]{3}\s?[0-9]{3})\s*MVA\b',page.text,re.I))
    # Explicit labels with dotted groups or an optional period after the label.
    # Do not interpret phone/order numbers or arbitrary nine digits as identity.
    for value in re.findall(r'\b(?:organisasjons\s*(?:nummer|nr)|org\.?\s*(?:nr|no|nummer)|foretaksnummer|company\s+registration\s+(?:number|no))[.\s:\-]*(?:NO\s*)?([0-9]{3}[.\s]?[0-9]{3}[.\s]?[0-9]{3})(?![0-9])',page.text,re.I):
        number=re.sub(r'\D','',value)
        if valid_org(number):numbers.add(number)
    # Legal footers can insert the owner's name between the corporate label
    # and number ("Organisasjonsnummer Example AS: ..."). Do not miss that
    # conflicting owner merely because the digits do not follow the label.
    for value in re.findall(r'\b(?:organisasjonsnummer|organisasjonsnr\.?|org\.?\s*nr\.?)\s+[^:;\n]{3,100}?\b(?:AS|ASA|SA|NUF|STI)\s*[:\-]\s*(?:NO\s*)?([0-9]{3}[.\s]?[0-9]{3}[.\s]?[0-9]{3})(?![0-9])',page.text,re.I):
        number=re.sub(r'\D','',value)
        if valid_org(number):numbers.add(number)
    # A literal "Org." label with a valid Norwegian checksum is also explicit
    # corporate identity. Unlabelled numbers, order IDs and phone labels are not.
    for value in re.findall(r'\borg\.[ \t]*[:\-]?[ \t]*(?:NO[ \t]*)?([0-9]{3}[.\s]?[0-9]{3}[.\s]?[0-9]{3})(?![0-9])',page.text,re.I):
        number=re.sub(r'\D','',value)
        if valid_org(number):numbers.add(number)
    if data and re.search(r'/(?:kontakt[^/]*|contact[^/]*|imprint|impressum|legal)(?:/|$)',urlsplit(page.url).path,re.I):
        from business_identity import self_description_blocks
        full=normalized(data.get('navn',''));stem=re.sub(r' (as|asa|sa|nuf|sti)$','',full)
        brand=' '+normalized(page.title+' '+' '.join(page.content_headings))+' '
        if full!=stem and len(stem)>=5 and ' '+stem+' ' in brand:
            for block in self_description_blocks(page):
                # A contact block beginning with the complete legal name and
                # its checksum-valid identifier is explicit self-identification.
                # Customer/quote/form blocks and arbitrary nine digits do not qualify.
                match=re.match(r'^\s*'+r'\W+'.join(re.escape(t) for t in full.split())+
                               r'\s*\(\s*([0-9]{3}[.\s]?[0-9]{3}[.\s]?[0-9]{3})\s*\)',block,re.I)
                number=re.sub(r'\D','',match[1]) if match else None
                if number and valid_org(number):numbers.add(number)
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
    from site_discovery import excluded_content_url
    if excluded_content_url(url):return None
    path=urlsplit(url).path.casefold()
    if re.search(r'nyhetsbrev|newsletter|\.pdf$|\.jpg$|\.png$',path): return None
    # Whole path words: 'bestillinger' means orders, not 'stillinger' (jobs).
    if re.search(r'(?:^|[/_-])(?:karriere|careers?|jobb(?:er|e)?|jobs?|stillinger?|vacanc(?:y|ies))(?:$|[/_-])',path): return 'hiring'
    if re.search(r'(?:^|[/_-])(?:news|nyheter?|aktuelt|blogg?|presse|press|presserom|pressroom|newsroom|artikler|articles?|stories|insights)(?:$|[/_-])|/20\d{2}/',path): return 'activity'
    if re.search(r'kontakt|contact|personvern|privacy|beting|vilk|impressum|imprint|legal|om-oss|about',path): return 'identity'
    if re.search(r'/(?:utsalg(?:ene)?|avdelinger?|locations?|offices?)(?:/|$)',path):return 'identity'
    return None

def catalog_route(url):
    return bool(re.search(r'/(?:products?|produkter|produktkategori|collections?|shop|butikk|catalog|katalog|services?|tjenester)(?:/|$)',urlsplit(url).path,re.I))

def activity_taxonomy(url):
    return bool(re.search(r'/(?:post-tags|tags?|categories|category|authors?|page)/',urlsplit(url).path,re.I))

def article_detail(url):
    if activity_taxonomy(url):return False
    return bool(re.search(r'/(?:news|nyheter?|aktuelt|blogg?|presse|press|artikler|articles?|stories|insights)(?:[-_](?:og[-_])?(?:presse|press|news))?/[^/]+|/(?:[\w]+[-_])?(?:presserom|pressroom|newsroom)/[^/]+|/20\d{2}/',urlsplit(url).path,re.I))

def social_profile(url):
    from attribution import canonical_profile
    return canonical_profile(url) is not None


def crawl_company(org, data, response, fetcher, *, registry_redirect_host=None, reserve_requests=0, seed_urls=(), portal_child=False, priority_urls=()):
    """Explore distinct purposes and linked detail pages within the existing request cap."""
    home=Page(response.get('text',''),response['url']); host=urlsplit(response['url']).hostname
    pages=[];verified=[];seen={urlunsplit((*urlsplit(response['url'])[:4],''))};queue={};counts=collections.Counter();discovered=False
    post_leads={};exploratory_roles=set();attempted_pages=1
    operator_blocked=False;known_operator=None
    def ingest(page,rsp):
        nonlocal operator_blocked,known_operator
        operator=site_operator_identity(org,page,data,response['url'])
        if operator['state']=='absent' and (page is home or (not verified and link_family(page.url)=='identity')):
            from attribution import group_site_reason
            reason=group_site_reason(page,data,identity_page=page is not home)
            if reason:operator={'state':'unresolved','reason':reason,'operators':[]}
        if operator['state'] in ('different','unresolved'):
            operator_blocked=True
            pages.append((page,{**rsp,'site_operator':operator},'operator_ambiguous'))
            return False
        if operator['state']=='target':
            known_operator=operator
            rsp={**rsp,'site_operator':operator}
        # A declared target operator is role-specific proof. IDs of article
        # subjects or sponsors must not be a global census veto on this site.
        identity=('exact' if known_operator else website_identity(org,page,data,site_url=response['url']))
        if identity=='conflict': return False
        pages.append((page,rsp,identity))
        if identity=='exact' or corroborated_site(data,page,registry_redirect_host): verified.append((page,rsp))
        if not verified:
            from business_identity import business_identity
            compatible=lambda pg:website_identity(org,pg,data)!='conflict' and site_operator_identity(org,pg,data)['state'] not in {'different','unresolved'}
            proof=business_identity(data,[(pg,r) for pg,r,_ in pages],compatible)
            if proof:
                # The homepage is established by the linked bundle; all proof
                # pages remain retained and are referenced in the final claim.
                root_pg,root_rsp,_=pages[0]
                verified.append((root_pg,{**root_rsp,'business_identity_support':proof}))
        activity_index=(link_family(rsp['url'])=='activity' and not article_detail(rsp['url'])
                        and not activity_candidates(page,rsp)[0])
        for link in page.links:
            label=normalized(link['text'])
            if link.get('in_navigation') and re.fullmatch(r'english|engelsk|norsk|norwegian|bokmål|nynorsk|deutsch|svenska|dansk|en|no|nb|nn',label):
                continue
            url=urlunsplit((*urlsplit(link['url'])[:4],''))
            from site_discovery import excluded_content_url
            if excluded_content_url(url):continue
            family=link_family(url)
            if family is None:
                if re.search(r'\b(kontakt|contact|personvern|privacy|om oss|about us)\b',label): family='identity'
                elif re.match(r'^(?:vi søker|we are hiring|ledige stillinger|job vacancies)\b',label):family='hiring'
            if family is None and verified and page is home:
                # A shallow branded business page may contain the contact or
                # imprint without being labelled "about". This is only a URL
                # lead on an already checked site, never identity evidence.
                path_parts=[p for p in urlsplit(url).path.split('/') if p]
                brand=re.sub(r'[^a-z0-9]','',(host or '').removeprefix('www.').split('.')[0].casefold())
                slug=re.sub(r'[^a-z0-9]','',path_parts[0].casefold()) if len(path_parts)==1 else ''
                shared=0
                for a,b in zip(brand,slug):
                    if a!=b:break
                    shared+=1
                if shared>=6:family='identity'
            if (family not in ('identity',) and verified and activity_index
                    and not link.get('in_navigation') and not link.get('third_party_context')
                    and len(link['text'].strip())>=5 and urlsplit(url).path not in ('','/')
                    and not activity_taxonomy(url) and not catalog_route(url)
                    and not re.search(r'\.(?:pdf|jpe?g|png|gif|svg|webp|mp4|xml)$',urlsplit(url).path,re.I)
                    and url!=rsp['url']):
                # A real post may use a root slug. This only discovers it;
                # publication still requires dated, scoped article evidence.
                family='activity'
                post_leads.setdefault(url,len(post_leads))
            if family and urlsplit(url).scheme in ('https','http') and urlsplit(url).hostname==host and url not in seen:
                from site_discovery import identity_content_candidate
                if family=='identity':url=identity_content_candidate(url)
                if url not in seen:queue[url]=family
        return True
    if not ingest(home,response): return [],pages
    prior_content=set()
    for prior in priority_urls:
        url=prior.get('url') if isinstance(prior,dict) else prior
        if not isinstance(url,str):continue
        try:p=urlsplit(url);port=p.port
        except ValueError:continue
        family=prior.get('family') if isinstance(prior,dict) else link_family(url)
        if family not in {'identity','activity','hiring'}:continue
        if (family and p.hostname==host and p.scheme in {'https','http'} and not p.username
                and not p.password and port in (None,80,443) and url not in seen):
            queue[url]=family;prior_content.add(url)
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
            map_host=urlsplit(rsp['url']).hostname or ''
            if (rsp['status']!='available' and not (verified and rsp.get('status_code')==404)) or (map_host!=host and not (verified and map_host.removeprefix('www.')==host.removeprefix('www.'))):continue
            urls,maps=xml_candidates(rsp.get('text',''),rsp['url'],host,canonical_alias=bool(verified))
            sources.extend(sorted(maps,key=lambda u:(0 if re.search(r'post|news',u,re.I) else 1 if re.search(r'page',u,re.I) else 2,u)))
            careers_seen=verified and (any(link_family(pg.url)=='hiring' for pg,_,_ in pages)
                or any(family=='hiring' and url not in exploratory_roles for url,family in queue.items()))
            for candidate in urls:
                from site_discovery import excluded_content_url
                if excluded_content_url(candidate):continue
                family=link_family(candidate)
                if (family is None and verified and re.search(r'post|news|feed',url,re.I)
                        and not re.search(r'\.(?:pdf|jpe?g|png|gif|svg|webp|mp4|xml)(?:$|[?#])',candidate,re.I)):
                    family='activity'
                if family and candidate not in seen:queue.setdefault(candidate,family)
                elif (careers_seen and len(exploratory_roles)<2 and candidate not in seen
                      and len([p for p in urlsplit(candidate).path.split('/') if p])==1
                      and not catalog_route(candidate) and not re.search(r'\.(?:pdf|jpe?g|png|gif|svg|webp|mp4|xml)$',urlsplit(candidate).path,re.I)):
                    exploratory_roles.add(candidate);queue.setdefault(candidate,'hiring')
    from hiring_discovery import application_links,linked_public_job_detail,external_career_leads
    def has_application_lead():
        return any(application_links(pg) or any(linked_public_job_detail(pg,l) for l in pg.links) for pg,_,_ in pages)
    def crawl_reserve():
        # Public application landing pages can contain the only literal deadline.
        # Leave room for their robots request, three GETs and one redirect once a role links one.
        if verified and any(u not in seen for u in prior_content):return 0
        if verified and has_application_lead():return 5
        # An observed external careers portal needs a robots check, index and
        # job detail. Do not spend every slot on internal auxiliary pages first.
        if (verified and any(u not in seen
                for pg,_,_ in pages for u in external_career_leads(pg))):return 4
        return 0 if verified else reserve_requests
    while attempted_pages<18 and fetcher.requests<fetcher.limit-crawl_reserve():
        # An already fetched news index provides stronger discovery leads than
        # another map request. XML remains a fallback when those leads run out.
        pending_posts=any(u not in seen and u in queue for u in post_leads)
        pending_roles=any(f=='hiring' and not any(urlsplit(v).path.rstrip('/')==urlsplit(u).path.rstrip('/') and urlsplit(v).query==urlsplit(u).query for v in seen) for u,f in queue.items())
        # Save map requests for a pending recruiting portal by following an
        # already observed editorial index first. Refresh keeps its established
        # source priorities; unrelated sites retain their previous crawl order.
        pending_index=(not prior_content and any(external_career_leads(pg) for pg,_,_ in pages)
            and any(f=='activity' and not article_detail(u) and not activity_taxonomy(u) for u,f in queue.items() if u not in seen))
        has_application=has_application_lead()
        if not discovered and (not queue or (verified and len(seen)>=4 and not pending_posts and not pending_index)) and not (pending_roles and (has_application or portal_child)):
            discovered=True;discover()
        if not queue:break
        def rank(item):
            url,family=item
            base=({'hiring':0,'activity':1,'identity':5} if verified else {'identity':0,'hiring':5,'activity':6})[family]
            if verified and url in prior_content:base-=80
            if url in exploratory_roles:base+=100
            depth=len([s for s in urlsplit(url).path.split('/') if s])
            # Up to three observed named role links precede redundant career indexes.
            role_count=sum(link_family(r['url'])=='hiring' and len([p for p in urlsplit(r['url']).path.split('/') if p])>=2 for _,r,_ in pages)
            if verified and (has_application or portal_child) and family=='hiring' and depth>=2 and role_count<3:base-=20
            pagination=bool(re.search(r'/page/[2-9][0-9]*/?$',urlsplit(url).path,re.I))
            detail_seen=sum(bool(article_detail(r['url']) or pg.post_container) for pg,r,_ in pages)
            pagination_seen=any(re.search(r'/page/[2-9][0-9]*/?$',urlsplit(r['url']).path,re.I) for _,r,_ in pages)
            if verified and pagination and detail_seen>=2 and not pagination_seen and not has_application:base-=40
            if verified and has_application and role_count>=3 and family=='identity' and re.search(r'kontakt|contact',urlsplit(url).path,re.I):base-=20
            # Inspect legal ownership before repeatedly exploring auxiliary
            # identity pages; still leave a balanced path to jobs and articles.
            legal=bool(re.search(r'personvern|privacy|legal|impressum|imprint|vilk|beting',urlsplit(url).path,re.I))
            penalty=counts[family]*4
            identity_order=0 if legal else 1 if re.search(r'kontakt|contact|kundeservice',urlsplit(url).path,re.I) else 2
            if re.search(r'/(?:map(?:[-_][0-9]+)?|kart)(?:/|$)',urlsplit(url).path,re.I):identity_order=3
            parts=[s.casefold() for s in urlsplit(url).path.split('/') if s]
            entry_parts=[s.casefold() for s in urlsplit(response['url']).path.split('/') if s]
            locale=bool(parts and parts[0] in {'en','no','nb','nn','de','sv','da'} and parts[:1]!=entry_parts[:1])
            detail_order=post_leads.get(url,10_000+list(queue).index(url)) if family=='activity' else list(queue).index(url)
            alias=(not verified or has_application) and any(urlsplit(u).path.rstrip('/')==urlsplit(url).path.rstrip('/') and urlsplit(u).query==urlsplit(url).query for u in seen)
            return (alias,base+penalty+(30 if family=='activity' and activity_taxonomy(url) else 0), locale if verified else False, identity_order if family=='identity' and (verified or portal_child) else 0,
                    (0 if verified else depth),detail_order,len(url),url)
        url,family=min(queue.items(),key=rank);del queue[url];seen.add(url);counts[family]+=1;attempted_pages+=1
        child=fetcher.get(url,site=True,raw=True)
        if child['status']!='available' or urlsplit(child['url']).hostname!=host: continue
        seen.add(child['url']);queue.pop(child['url'],None)
        ingest(Page(child.get('text',''),child['url']),child)
        if operator_blocked:break
    # Late fallback preserves the crawl path and all previously established facts.
    # A title or a registry domain alone never establishes first-party identity.
    if not verified and not operator_blocked:
        from legal_name_identity import legal_name_identity
        compatible=lambda pg:website_identity(org,pg,data)!='conflict' and site_operator_identity(org,pg,data)['state'] not in {'different','unresolved'}
        proof=legal_name_identity(data,[(pg,rsp) for pg,rsp,_ in pages],compatible)
        if proof:
            pg,rsp=next((pg,rsp) for pg,rsp,_ in pages if rsp['url']==proof['source_url'])
            verified.append((pg,{**rsp,'legal_name_identity_support':proof}))
    return ([] if operator_blocked else verified),pages


def group_description(text):
    """Explicit collective wording cannot establish an own-entity description."""
    return bool(re.search(
        r"\b(?:the|our|entire|whole)\s+group\b|"
        r"\bwe\s+(?:are|operate)\s+(?:a|an)\s+group\b|"
        r"\b(?:group|gruppen)\s+(?:consists|comprises|includes|employs)\b|"
        r"\b(?:konsernet|konsernets|hele\s+gruppen|vårt\s+konsern)\b",
        text, re.I))


def activity_candidates(page, response):
    """Return article candidates tied to this page, plus bounded limitations.

    Menu/product/collection metadata and modified-only timestamps cannot be
    promoted to published news. One uncertain item never removes valid siblings.
    """
    if page.editorial_listing:return [],['editorial index or archive is a discovery source, not an individual dated post']
    candidates=[];limitations=[]
    def limit(reason):
        if reason not in limitations:limitations.append(reason)
    def same_page(value):
        if isinstance(value,dict):value=value.get('@id') or value.get('url')
        if value is None:return True
        if not isinstance(value,str):return False
        try:
            p=urlsplit(urljoin(response['url'],value))
            q=urlsplit(response['url'])
            return (p.scheme,p.netloc,p.path.rstrip('/'),p.query)==(q.scheme,q.netloc,q.path.rstrip('/'),q.query)
        except ValueError:return False
    path=urlsplit(response['url']).path
    product_or_index=activity_taxonomy(response['url']) or bool(not article_detail(response['url']) and re.search(
        r'/(?:products?|produkter|produktkategori|collections?|shop|butikk|catalog|katalog|services?|tjenester)(?:/|$)',path,re.I))
    headings=page.semantic_headings or page.main_headings or page.content_headings
    if len(headings)==1:
        title=headings[0].strip()
        test_title=re.fullmatch(r'test[ -]?(?:post|page|article|innlegg)(?:[ -]?(?:mobile|mobil))?[.! ]*',title,re.I)
        default_title=re.fullmatch(r'(?:hello world|hei[, ]+verden|lorem ipsum)[.! ]*',title,re.I)
        default_body=re.search(r'welcome to wordpress|velkommen til wordpress|this is your first post|dette er ditt første innlegg|lorem ipsum dolor sit amet',' '.join(page.article_parts),re.I)
        if test_title or (default_title and default_body):
            return [],['placeholder/test post is not a publishable company activity']
    from publication import publication_block
    literal=publication_block(page)
    editorial_view=page.post_container or bool(literal and page.meta.get('og:type')=='article' and page.meta.get('og:url') and same_page(page.meta.get('og:url')) and urlsplit(response['url']).path.rstrip('/') and len(headings)==1)
    for root in page.ld:
        roots=list(root) if isinstance(root,list) else [root]
        if isinstance(root,dict) and isinstance(root.get('@graph'),list):
            roots.extend(root['@graph'])
        for obj in roots:
            if not isinstance(obj,dict):continue
            if schema_types(obj) & {'Product','Offer','Service','ItemList','CollectionPage','SearchResultsPage'}:
                product_or_index=True
            main=obj.get('mainEntity')
            if isinstance(main,dict) and schema_types(main) & {'Product','Offer','Service','ItemList'}:
                product_or_index=True
    for obj in objects(page.ld):
        types=schema_types(obj)
        if not types & {'NewsArticle','Article','BlogPosting'}:continue
        obj={key:value for key,value in obj.items() if not key.startswith('_')}
        if not same_page(obj.get('url')) or not same_page(obj.get('mainEntityOfPage')):
            limit('article describes another URL; fetch its own page before attribution')
            continue
        if not (types & {'NewsArticle','BlogPosting'}) and not article_detail(response['url']) and not editorial_view:
            limit('generic Article outside a dated-activity detail path')
            continue
        if product_or_index:
            limit('product or collection metadata does not establish a real post')
            continue
        if not (isinstance(obj.get('articleBody'),str) and len(obj['articleBody'].strip())>=80) and (not page.content_headings or len(' '.join(page.article_parts).strip())<80):
            limit('structured article lacks visible post heading/body')
            continue
        # SEO titles frequently append the publisher brand to unrelated posts.
        # The actual single visible heading governs title and subject matching.
        if len(headings)==1:obj={**obj,'headline':headings[0]}
        visible_times=page.main_times or page.content_times or ([literal['date']] if literal and editorial_view else [])
        visible_headings=page.semantic_headings or page.main_headings or page.content_headings
        if len(visible_headings)==1 and len(set(visible_times))==1 and isinstance(obj.get('datePublished'),str) and obj['datePublished'][:10]!=visible_times[0][:10]:
            limit('visible publication date differs from structured article; visible date retained')
            obj={**obj,'datePublished':visible_times[0]}
        candidates.append(obj)
    detail=article_detail(response['url']) or editorial_view
    headings=page.semantic_headings or page.main_headings or page.content_headings
    publication_times=page.main_times or page.content_times
    if not publication_times and literal:publication_times=[literal['date']]
    if detail and product_or_index:
        limit('product or collection page metadata is not publication evidence')
    elif detail and len(headings)==1 and len(' '.join(page.article_parts).strip())>=80:
        # The visible, semantically published date governs the post. CMS
        # migrations often overwrite OpenGraph dates with the import time.
        if len(set(publication_times))==1:
            visible=publication_times[0]
            meta=page.meta.get('article:published_time')
            if meta and meta[:10]!=visible[:10]:
                limit('visible publication date differs from OpenGraph; visible date retained')
            candidates.append({'@type':'NewsArticle','headline':headings[0],
                               'datePublished':visible,**({'_publication_date_basis':literal} if literal and not (page.main_times or page.content_times) else {})})
        elif not publication_times and page.meta.get('article:published_time'):
            candidates.append({'@type':'NewsArticle',
                'headline':headings[0],
                'datePublished':page.meta['article:published_time']})
        elif publication_times:
            limit('multiple content publication dates; no unique date established')
    elif detail and (page.meta.get('article:published_time') or page.times):
        limit('publication metadata lacks a single content heading; menu/header/footer is insufficient')
    from attribution import page_publisher
    publisher=page_publisher(page)
    if publisher:
        candidates=[({**obj,'publisher':publisher} if not obj.get('publisher') else obj) for obj in candidates]
    return candidates,limitations

def legal_footer_identity(data,page):
    """An exact own legal imprint, not a directory/customer paragraph."""
    from registry_discovery import FREE_EMAIL
    p=urlsplit(page.url)
    if (p.hostname or '').casefold().removeprefix('www.') in FREE_EMAIL:return False
    if p.path.rstrip('/') not in ('','/home','/hjem','/index.html','/index.php'):return False
    if website_identity(str(data.get('organisasjonsnummer','')),page,data)=='conflict':return False
    full=normalized(data.get('navn',''));stem=re.sub(r' (as|asa|sti|nuf)$','',full)
    if len(stem)<5 or not full:return False
    title=re.split(r'\s+[|–—-]\s*|\|',page.title)[0]
    brand=normalized(page.meta.get('og:site_name') or title)
    neutral={'','hjem','home','homepage','velkommen','welcome','coming soon','under construction','ny nettside underveis'}
    if brand not in {stem,full} and brand not in neutral:return False
    blocks=[]
    footer=' '.join(page.footer_parts)
    if ' '+full+' ' in ' '+normalized(footer)+' ':blocks.append(footer)
    # Some simple builders have no footer tag. A standalone full legal-name
    # paragraph followed by its exact registered address is an explicit imprint.
    for index,paragraph in enumerate(page.paragraphs):
        if normalized(paragraph)==full:blocks.append(' '.join(page.paragraphs[index:index+4]))
    for block in blocks:
        text=' '+normalized(block)+' '
        for field in ('forretningsadresse','postadresse'):
            a=data.get(field) or {};street=next(iter(a.get('adresse') or []),'');code=a.get('postnummer')
            if street and code and ' '+normalized(street)+' ' in text and re.search(r'(?<!\d)'+re.escape(str(code))+r'(?!\d)',text):return True
    return False


def corroborated_site(data, page, registry_redirect_host=None):
    """Only registry-declared domains: name AND exact postal address corroboration.

    Email domains, group sites and name alone cannot satisfy this alternative.
    Explicit conflicting organisation numbers always take precedence.
    """
    org=str(data.get('organisasjonsnummer',''))
    if site_operator_identity(org,page,data)['state'] in ('different','unresolved'):return False
    if website_identity(org,page,data)=='conflict':return False
    if legal_footer_identity(data,page):return True
    registered=data.get('hjemmeside') or ''
    footer_only=False
    if not registered:
        # An official corporate email domain is only a lead. Require the full
        # legal name AND exact registered street/postcode in the site's legal
        # footer, plus a matching first-party brand. Never publish the email.
        from registry_discovery import FREE_EMAIL
        email=data.get('epostadresse')
        domain=email.rsplit('@',1)[-1].strip().casefold() if isinstance(email,str) and '@' in email else ''
        footer=' '+normalized(' '.join(page.footer_parts))+' '
        full=normalized(data.get('navn',''))
        brand=page.meta.get('og:site_name') or page.title
        stem=re.sub(r' (as|asa|sti)$','',full)
        compact=lambda v:re.sub(r'[^\w]','',normalized(v))
        if (not domain or domain in FREE_EMAIL or not full or ' '+full+' ' not in footer
                or len(stem)<5 or compact(stem) not in compact(brand)):
            return False
        registered='https://'+domain;footer_only=True
    registered=registered if '://' in registered else 'https://'+registered
    registered_host=(urlsplit(registered).hostname or '').casefold().removeprefix('www.')
    page_host=(urlsplit(page.url).hostname or '').casefold().removeprefix('www.')
    if registered_host!=page_host and registry_redirect_host!=page_host:
        return False
    name=normalized(data.get('navn',''))
    name=re.sub(r' (as|asa|sti)$','',name)
    evidence_text=' '.join(page.footer_parts) if footer_only else page.text
    text=' '+normalized(evidence_text)+' '
    if len(name)<3 or ' '+name+' ' not in text:return False
    if len(name)<8 and ' '+normalized(data.get('navn',''))+' ' not in text:return False
    for kind in ('forretningsadresse','postadresse'):
        address=data.get(kind) or {}
        street=next(iter(address.get('adresse') or []),''); postal=address.get('postnummer','')
        if street and postal and ' '+normalized(street)+' ' in text and re.search(r'(?<!\d)'+re.escape(postal)+r'(?!\d)',evidence_text):
            return True
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
                    'domain_origin':('exact first-party legal footer, matching homepage brand and official postal address; URL may originate as an untrusted lead' if legal_footer_identity(data,page) else 'entity website declaration' if data.get('hjemmeside') else 'corporate email domain lead plus full legal footer and registered address; registry email not published'),
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
        previous_spans=evidence.get(eid,{}).get('claim_spans',[])
        evidence[eid]={'id':eid, 'source_url':response['url'], 'retrieved_at':response['retrieved_at'],
            'content_sha256':response['content_sha256'], 'source_class':'public_job_board' if response.get('public_job_board') else 'official_registry' if response['url'].startswith(OFFICIAL+'/') else 'company_website' if response.get('identity_verified') else 'candidate_website',
            'retention':response.get('retention','source bytes retained in local cache')}
        spans=list(previous_spans)
        if not excerpt and value is not None:
            # Retain a literal source span as well as the precise JSON/DOM
            # pointer. Do not substitute a fabricated narrative for evidence.
            raw=response.get('text','')
            def leaves(item):
                if isinstance(item,dict):
                    for child in item.values():yield from leaves(child)
                elif isinstance(item,list):
                    for child in item:yield from leaves(child)
                elif item is not None:yield item
            values=[]
            for literal in leaves(value):
                values.append(literal)
                if len(values)>=30:break
            for literal in values:
                if literal is None:continue
                for token in (json.dumps(literal,ensure_ascii=False),json.dumps(literal,ensure_ascii=True),str(literal)):
                    if not token or len(token)>1500:continue
                    position=raw.find(token)
                    if position>=0:
                        excerpt=(token if response['url'].startswith(OFFICIAL+'/') else raw[max(0,position-60):position+len(token)+100])
                        break
                if excerpt:break
        if excerpt and isinstance(excerpt,str):
            span={'field':field,'text':excerpt[:1500],'source_pointer':pointer}
            if span not in spans:spans.append(span)
        evidence[eid]['claim_spans']=spans[:30]
        evidence[eid]['claim_span']='\n'.join(span['text'] for span in spans[:30])
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
    units=pick(locations.get('json') or {},'_embedded','underenheter') or []
    leads=registry_candidates(org,data,units)
    # Previous observations nominate URLs only. Fresh primary responses still
    # establish identity and every fact; previous values are never copied.
    previous_urls=[]
    if isinstance(previous,dict) and previous.get('organisation_number')==org:
        for item in previous.get('claims',[]):
            if not isinstance(item,dict) or item.get('availability')!='available':continue
            field=item.get('field');value=item.get('value')
            if field=='website.verified_url' and isinstance(value,str):
                from registry_discovery import web_url
                checked=web_url(value)
                if checked and not any(host_key(x['url'])==host_key(checked) for x in leads):
                    leads.append({'url':checked,'origin':'previous_verified_url_revalidation'})
            if field in {'website.activity','website.hiring','website.contact_channels'} and isinstance(value,list):
                for fact in value:
                    if not isinstance(fact,dict):continue
                    url=fact.get('source_url') if field=='website.contact_channels' else fact.get('url')
                    family={'website.activity':'activity','website.hiring':'hiring','website.contact_channels':'identity'}[field]
                    if (isinstance(url,str) and not any(p['url']==url for p in previous_urls)
                            and sum(p['family']==family for p in previous_urls)<8):
                        previous_urls.append({'url':url,'family':family})
    public_jobs_result=None
    def public_jobs():
        nonlocal public_jobs_result
        if public_jobs_result is None:
            from public_recruiting import discover
            public_jobs_result=(discover(data,units,fetcher) if getattr(fetcher,'public_jobs',True) else {'records':[],'website_leads':[],'checks':[],'sources':[],'detail_attempts':0})
        return public_jobs_result
    webstate={'url':'','status':'not_available','retrieved_at':now()}
    attempts=[];operator_limits=[];inspected_observations=set();unverified_pages=[]
    def candidates():
        for index,lead in enumerate(leads):
            lead_url=lead['url'];parsed=urlsplit(lead_url)
            remaining=len(leads)-index-1+bool(search)+2
            yield lead_url,lead['origin'],remaining,[]
            # A registry portal may link the entity's own branded child domain.
            # Follow only observed links matching generic legal-name domain leads;
            # the child still needs independent legal identity verification.
            if lead['origin']=='entity_website' and webstate.get('status')=='available':
                from registry_discovery import scoped_entity_candidates
                for scoped in scoped_entity_candidates(data,Page(webstate.get('text',''),webstate['url'])):
                    yield scoped,'entity_scoped_page',remaining,[]
                from registry_discovery import name_domain_candidates,web_url
                child_hosts={host_key(u) for u in name_domain_candidates(data)}
                linked=[]
                for link in Page(webstate.get('text',''),webstate['url']).links:
                    child=web_url(link.get('url',''))
                    if not child:continue
                    pc=urlsplit(child)
                    if (pc.scheme in ('https','http') and not pc.username and not pc.password
                            and pc.port in (None,80,443) and host_key(child) in child_hosts
                            and host_key(child)!=host_key(lead_url) and not link.get('third_party_context')
                            and child not in linked):linked.append(child)
                for child in linked[:2]:yield child,'entity_portal_link',remaining,[]
            # Ordinary canonical hostname candidate, independently identity-
            # checked. TLS validation, robots policy and public-IP checks stay on.
            if (parsed.hostname or '').startswith('www.'):
                root=parsed.hostname[4:]+(':'+str(parsed.port) if parsed.port else '')
                alternate=urlunsplit((parsed.scheme,root,parsed.path,parsed.query,''))
                yield alternate,'canonical_host_candidate',remaining,[]
        from registry_discovery import name_domain_candidates,industry_city_candidates
        existing={host_key(lead['url']) for lead in leads}
        derived=[u for u in name_domain_candidates(data) if host_key(u) not in existing]
        for index,url in enumerate(derived):yield url,'name_domain_heuristic',len(derived)-index-1,[]
        for index,url in enumerate(industry_city_candidates(data)):
            if host_key(url) not in existing and url not in derived:yield url,'industry_city_heuristic',1-index,[]
        # Preserve the established website-discovery request budget. Query
        # boards after those leads fail, so redirects and legal identity pages
        # are not starved by an unrelated recruiting search.
        for index,homepage in enumerate(public_jobs()['website_leads'][:2]):
            yield homepage,'public_ad_employer_homepage',1-index,[]
        from registry_discovery import legal_form_domain_candidates
        for homepage in legal_form_domain_candidates(data):
            if fetcher.requests<=fetcher.limit-2:
                yield homepage,'legal_form_domain_heuristic',0,[]
        # Preserve all earlier discovery paths. Only then try the other normal
        # schemes/host aliases of the literal registry URL and a compact .com.
        # These are leads, never proof, and share the same company request cap.
        from registry_discovery import declared_url_variants,additional_name_domain_candidates
        already={a['url'] for a in attempts}
        for alternate in declared_url_variants(data.get('hjemmeside')):
            if alternate not in already and fetcher.requests<=fetcher.limit-2:
                yield alternate,'late_declared_url_variant',1,[]
        # The corporate email domain is only a lead. Some such domains serve
        # the site on www while the bare host has no reachable robots resource.
        # One late normal alias still needs its own robots and legal proof.
        for lead in leads:
            parsed=urlsplit(lead['url'])
            if lead['origin']=='email_domain' and parsed.hostname and not parsed.hostname.startswith('www.'):
                alternate=urlunsplit((parsed.scheme,'www.'+parsed.netloc,parsed.path,parsed.query,''))
                if alternate not in already and fetcher.requests<=fetcher.limit-2:
                    yield alternate,'late_email_domain_www_variant',1,[]
        for alternate in additional_name_domain_candidates(data):
            if alternate not in already and fetcher.requests<=fetcher.limit-2:
                yield alternate,'late_name_com_heuristic',0,[]
        # Optional broad search must not consume the slots that already recover
        # a first-party site or an exact-employer public ad without credentials.
        # A site found earlier closes this lazy generator without a search call.
        if search and data.get('navn') and fetcher.requests<=fetcher.limit-3:
            if hasattr(search,'iter_candidates'):
                for url,remaining,hints in search.iter_candidates(org,data['navn'],fetcher):
                    yield url,'search_scoped_page' if urlsplit(url).path not in ('','/') else 'search',remaining,hints
            else:
                urls=search.discover(org,data['navn'],fetcher)
                for i,url in enumerate(urls):yield url,'search',len(urls)-i-1,[]
        if getattr(fetcher,'public_search',None):
            candidates=fetcher.public_search.discover(data,fetcher)
            for index,candidate in enumerate(candidates):
                yield candidate['url'],'anonymous_search',len(candidates)-index-1,candidate['hints']
    for url,origin,remaining_leads,hints in candidates():
        # Redirect aliases and a final unverified site must not consume the
        # reserve left for a current exact-employer public posting. No prior
        # facts are accepted here; public detail pages still prove each ad.
        if public_jobs_result is None and getattr(fetcher,'public_jobs',True) and fetcher.requests>=fetcher.limit-8:
            public_jobs()
        started_requests=fetcher.requests
        response=fetcher.get(url,site=True,raw=True); webstate=response
        attempt={'url':url,'origin':origin,'fetch_state':response['status'],'resolved_url':response['url'],
                 'identity':'not_checked','pages_inspected':0,'requests':fetcher.requests-started_requests,
                 'status_code':response.get('status_code'),'fetch_error':response.get('error'),
                 'error_kind':response.get('error_kind'),'response_headers':response.get('response_headers'),
                 'protection':response.get('protection'),'transport_attempts':response.get('transport_attempts')}
        origins=list(dict.fromkeys(urlunsplit((*urlsplit(u)[:2],'','','')) for u in (url,response['url'])))
        attempt['robots']=[fetcher.robots_observations[o] for o in origins if o in getattr(fetcher,'robots_observations',{})]
        attempts.append(attempt)
        if response['status']=='available':
            unverified_pages.append(response)
            # Only an observed redirect from the declared entity URL extends
            # its domain anchor. Search, email and workplace URLs cannot do so.
            redirect_host=host_key(response['url']) if origin=='entity_website' and response.get('requested_url')==url else None
            observed=(response['url'],response.get('content_sha256'),redirect_host,origin=='entity_portal_link')
            if response.get('content_sha256') and observed in inspected_observations and not hints:
                attempt.update(identity='not_established',reused_inspection=True,
                               reason='same resolved URL, body hash and identity-anchor context already inspected in this observation')
                continue
            # Prefer an observed entity-specific page on a shared host before
            # spending the crawl budget on its generic root. Explicit org proof
            # on the entry page always takes precedence over this navigation.
            from registry_discovery import scoped_entity_candidates
            entry_page=Page(response.get('text',''),response['url'])
            from attribution import mentions
            entry_brand=entry_page.meta.get('og:site_name') or entry_page.title
            if (origin=='entity_website' and not mentions(entry_brand,data.get('navn',''))
                    and website_identity(org,entry_page,data)!='exact'
                    and scoped_entity_candidates(data,entry_page)):
                attempt.update(identity='not_established',rejection_reason='entity_scoped_link_preferred',
                               reason='observed complete legal-name company path; inspect that page before the generic entry')
                continue
            verified,inspected=crawl_company(org,data,response,fetcher,registry_redirect_host=redirect_host,
                                            reserve_requests=6 if remaining_leads or (public_jobs_result is None and getattr(fetcher,'public_jobs',True)) else 0,seed_urls=hints,
                                            portal_child=origin=='entity_portal_link',priority_urls=previous_urls)
            if response.get('content_sha256'):inspected_observations.add(observed)
            attempt.update(identity='verified' if verified else 'not_established',pages_inspected=len(inspected),
                           requests=fetcher.requests-started_requests)
            blockers=[(rsp,rsp['site_operator']) for pg,rsp,identity in inspected
                      if rsp.get('site_operator',{}).get('state') in ('different','unresolved')]
            if blockers:
                operator_limits.extend(blockers)
                attempt['operator_limitations']=[operator for rsp,operator in blockers]
            if not verified:
                direct=website_identity(org,Page(response.get('text',''),response['url']),data,site_url=response['url'])
                attempt['rejection_reason']=('conflicting_site_operator' if blockers and blockers[0][1].get('state')=='different' else
                    'group_or_operator_unresolved' if blockers else 'conflicting_org_number' if direct=='conflict' else
                    'own_entity_evidence_insufficient')
            if verified:
                verified=[(pg,{**rsp,'identity_verified':True}) for pg,rsp in verified]
                anchor,anchor_response=verified[0]
                # Same-host pages can inherit the established site identity, except conflicts.
                content_pages=[(pg,{**rsp,'identity_verified':True,
                    'site_operator':rsp.get('site_operator',anchor_response.get('site_operator',{}))}) for pg,rsp,identity in inspected
                    if identity!='conflict' and urlsplit(rsp['url']).hostname==urlsplit(anchor_response['url']).hostname]
                if origin in {'entity_scoped_page','search_scoped_page'}:
                    scope=urlsplit(response['url']).path.rstrip('/')
                    content_pages=[(pg,rsp) for pg,rsp in content_pages
                        if urlsplit(rsp['url']).path.rstrip('/')==scope
                        or urlsplit(rsp['url']).path.startswith(scope+'/')
                        or website_identity(org,pg,data)=='exact']
                method=('explicit_site_operator' if anchor_response.get('site_operator',{}).get('state')=='target' else
                        'linked_business_self_description_and_registered_address' if anchor_response.get('business_identity_support') else
                        'linked_first_party_legal_name' if anchor_response.get('legal_name_identity_support') else
                        'explicit_org_number' if website_identity(org,anchor,data)=='exact' else
                        'exact_legal_footer_and_registered_address' if legal_footer_identity(data,anchor) else 'registry_domain_name_and_postal_address')
                add('website.verified_url',response['url'],anchor_response,pointer=method,
                    excerpt=identity_excerpt(org,anchor) if method=='explicit_org_number' else anchor.text[:1500])
                if origin in {'entity_scoped_page','search_scoped_page'}:
                    claims[-1]['qualifiers']={'site_scope':'specific company page on a shared host; ownership of the whole host is not inferred'}
                if method in {'registry_domain_name_and_postal_address','exact_legal_footer_and_registered_address'}:
                    extra=claim('identity_anchor',org,entity,evidence)
                    claims[-1]['evidence_ids']+=extra['evidence_ids']
                    claims[-1]['identity_support']=corroboration_evidence(data,anchor,response)
                    claims[-1]['evidence_excerpt']=None
                elif method=='linked_first_party_legal_name':
                    proof=anchor_response['legal_name_identity_support'];claims[-1]['identity_support']=proof;claims[-1]['evidence_excerpt']=None
                    wanted={proof['entry_url'],proof['source_url']}
                    for link in proof['links']:wanted.update([link['source_url'],link['target_url']])
                    from business_identity import canonical
                    for pg,rsp,_ in inspected:
                        if canonical(rsp['url']) in {canonical(u) for u in wanted}:
                            extra=claim('identity_bundle',None,rsp,evidence)
                            claims[-1]['evidence_ids']=list(dict.fromkeys(claims[-1]['evidence_ids']+extra['evidence_ids']))
                    extra=claim('identity_anchor',org,entity,evidence)
                    claims[-1]['evidence_ids']=list(dict.fromkeys(claims[-1]['evidence_ids']+extra['evidence_ids']))
                elif method=='explicit_site_operator':
                    claims[-1]['identity_support']=anchor_response['site_operator']
                    claims[-1]['evidence_excerpt']=None
                elif method=='linked_business_self_description_and_registered_address':
                    proof=anchor_response['business_identity_support'];claims[-1]['identity_support']=proof;claims[-1]['evidence_excerpt']=None
                    from business_identity import canonical
                    wanted={canonical(proof['legal_name_source']['source_url']),canonical(proof['address_source']['source_url']),canonical(proof['entry_url'])}
                    for part in ('legal_name_source','address_source'):
                        for link in proof[part]['links']:wanted.update([link['source_url'],link['target_url']])
                    for pg,rsp,_ in inspected:
                        if canonical(rsp['url']) in wanted:
                            extra=claim('identity_bundle',None,rsp,evidence)
                            claims[-1]['evidence_ids']=list(dict.fromkeys(claims[-1]['evidence_ids']+extra['evidence_ids']))
                    extra=claim('identity_anchor',org,entity,evidence)
                    claims[-1]['evidence_ids']=list(dict.fromkeys(claims[-1]['evidence_ids']+extra['evidence_ids']))
                # Identity may be proved on a privacy/contact page. Describe the
                # homepage instead of publishing that legal page's boilerplate.
                description_page,description_response=content_pages[0]
                description=description_page.description
                description_pointer='meta[name=description] or scoped visible homepage paragraph; navigation and footer excluded'
                if method=='linked_business_self_description_and_registered_address' and (not isinstance(description,str) or len(description.strip())<20 or len(description.split())<4 or re.match(r'^(?:\d{1,2}[./-]){2}\d{2,4}\s*[:–-]',description.strip())):
                    own_description=anchor_response['business_identity_support']['legal_name_source']
                    description=own_description['self_description']
                    description_page,description_response=next((pg,rsp) for pg,rsp in content_pages if rsp['url']==own_description['source_url'])
                    description_pointer='literal scoped own-company self-description from the linked legal identity source'
                if not isinstance(description,str) or len(description.strip())<20 or len(description.split())<4:
                    description=next((v for v in description_page.paragraphs if 70<=len(v)<=2000 or (len(v)>=20 and group_description(v))),None)
                if description and re.search(r'lorem ipsum|dolor sit amet|(?:web\s*site|nettside).{0,45}(?:under construction|coming soon|underveis|under arbeid)|^(?:under construction|coming soon)[.! ]*$',description,re.I):description=None
                if description:description=description[:700]
                collective=group_description(description or '')
                add('website.description',description or None,description_response,
                    state='ambiguous' if collective else None,
                    pointer=description_pointer,excerpt=description)
                if collective:
                    claims[-1]['qualifiers']={'subject_scope':'group',
                        'own_entity_description':'not_established',
                        'reason':'explicit collective wording; legal site identity does not attribute group statements to this entity'}
                from contacts import collect_entity_contacts
                contacts,contact_limits,contact_sources=collect_entity_contacts(content_pages,data,sites)
                contact_anchor=contact_sources[0] if contact_sources else anchor_response
                add('website.contact_channels',contacts or None,contact_anchor,excerpt=(contacts[0].get('source_href') or contacts[0]['value']) if contacts else None,
                    state='ambiguous' if not contacts and contact_limits else None,
                    pointer='literal mailto/tel links on verified company pages; third-party and unresolved regional contact blocks excluded; ownership/use not independently checked')
                if contact_limits:
                    claims[-1]['qualifiers']={'coverage':'partial' if contacts else 'unresolved','candidate_limitations':contact_limits[:20]}
                for rsp in contact_sources:
                    item=next((c for c in contacts if c['source_url']==rsp['url']),None)
                    extra=claim('website.contact_channels',None,rsp,evidence,
                                pointer='literal contact href or visible company contact block',
                                excerpt=(item.get('source_href') or item['value']) if item else None)
                    claims[-1]['evidence_ids']=list(dict.fromkeys(claims[-1]['evidence_ids']+extra['evidence_ids']))
                from hiring_discovery import delegated_hiring_pages, literal_hiring_candidates
                hiring_pages=content_pages+delegated_hiring_pages(content_pages,fetcher,Page,data=data,units=units)
                for field,types in [('hiring',{'JobPosting'}),('activity',{'NewsArticle','Article','BlogPosting'})]:
                    items=[]; evidence_responses=[];positive_responses=[];limitations=[]
                    def limitation(response,reason):
                        item={'source_url':response['url'],'reason':reason}
                        if item not in limitations and len(limitations)<20:limitations.append(item)
                        # Unknown/partial attribution also needs the retained
                        # source that caused it, not only the site's anchor.
                        if not any(r['url']==response['url'] and r.get('content_sha256')==response.get('content_sha256')
                                   for r in evidence_responses):
                            evidence_responses.append(response)
                    for pg,rsp in (hiring_pages if field=='hiring' else content_pages):
                        if field=='activity':
                            candidates,reasons=activity_candidates(pg,rsp)
                            for reason in reasons:limitation(rsp,reason)
                        else:
                            from hiring_discovery import closed_hiring_page
                            if rsp.get('delegated_from_verified_careers') and closed_hiring_page(pg):
                                limitation(rsp,'linked job posting is explicitly closed or expired');continue
                            literal_candidates=literal_hiring_candidates(pg,rsp,data,hiring_pages)
                            if not literal_candidates:
                                from hiring_discovery import continuous_first_party_vacancy,linked_public_job_detail
                                if any(not l.get('in_navigation') and linked_public_job_detail(pg,l) for l in pg.links) and continuous_first_party_vacancy(pg,rsp,data):
                                    limitation(rsp,'undated first-party notice defers to its explicitly linked public advertisement; verify publication and current state there')
                            candidates=list(objects(pg.ld))+literal_candidates
                        for obj in candidates:
                            if schema_types(obj) & types:
                                if field=='activity' and not (schema_types(obj)&{'NewsArticle','BlogPosting'}) and not article_detail(rsp['url']) and not pg.post_container:
                                    continue
                                title=obj.get('title') or obj.get('headline')
                                date=obj.get('datePublished') if field=='activity' else obj.get('datePosted')
                                literal_candidate=field=='hiring' and any(obj is candidate for candidate in literal_candidates)
                                literal_undated=(literal_candidate or bool(obj.get('_nuu_item'))) and date is None
                                if not isinstance(title,str) or (not isinstance(date,str) and not literal_undated):
                                    limitation(rsp,'candidate lacks a literal title and publication date')
                                    continue
                                try:
                                    if not literal_undated:dt.datetime.fromisoformat(date.replace('Z','+00:00'))
                                    if not literal_undated and dt.date.fromisoformat(date[:10])>dt.date.fromisoformat(rsp['retrieved_at'][:10]):
                                        limitation(rsp,'candidate publication date is in the future')
                                        continue
                                except ValueError:
                                    limitation(rsp,'candidate publication date is not a valid ISO date')
                                    continue
                                if field=='hiring':
                                    if re.search(r'åpen\s+søknad|open application|spontan|talent\s+(?:pool|network)',title,re.I):
                                        limitation(rsp,'spontaneous application or talent pool is not a specific vacancy');continue
                                    expiry=obj.get('validThrough')
                                    if isinstance(expiry,str):
                                        try:
                                            if dt.date.fromisoformat(expiry[:10])<dt.date.fromisoformat(rsp['retrieved_at'][:10]): continue
                                        except ValueError: continue
                                    employer=pick(obj,'hiringOrganization','name')
                                    legal=re.sub(r' (as|asa|sti)$','',normalized(data.get('navn','')))
                                    if not employer or re.sub(r' (as|asa|sti)$','',normalized(employer))!=legal:
                                        limitation(rsp,'posting lacks an exact named hiring entity; own-entity attribution unresolved')
                                        continue
                                    if (rsp.get('delegated_from_verified_careers') and not obj.get('_public_board_item')
                                            and normalized(employer)!=normalized(data.get('navn',''))):
                                        limitation(rsp,'delegated posting names only a brand or group; exact legal hiring employer unresolved')
                                        continue
                                attribution=None
                                if field=='activity':
                                    from attribution import article_attribution
                                    attribution=article_attribution(obj,pg,data)
                                    if not attribution:
                                        limitation(rsp,'dated post does not establish the target company as its subject; footer identity is insufficient')
                                        continue
                                item={'title':title,'date':date,'url':rsp['url']}
                                if field=='hiring' and isinstance(obj.get('url'),str):
                                    job_url=urljoin(rsp['url'],obj['url']);pjob=urlsplit(job_url)
                                    if (pjob.scheme in ('http','https') and not pjob.username and not pjob.password
                                            and pjob.port in (None,80,443) and pjob.hostname==urlsplit(rsp['url']).hostname):
                                        item['url']=job_url
                                if field=='hiring':item['hiring_organisation']=employer
                                if attribution:item['attribution']=attribution
                                if obj.get('_publication_date_basis'):item['publication_date_basis']=obj['_publication_date_basis']
                                if field=='hiring': item.update(valid_through=obj.get('validThrough'),status='published_posting; application availability not independently checked')
                                if obj.get('_public_board_item'):
                                    item.update(obj['_public_board_item'])
                                    evidence_responses.extend([entity,locations])
                                if obj.get('_vilect_item'):
                                    item.update(obj['_vilect_item'])
                                    evidence_responses.extend([entity,anchor_response,*rsp.get('vilect_support_responses',[])])
                                if obj.get('_nuu_item'):
                                    item.update(obj['_nuu_item'])
                                    evidence_responses.extend([entity,anchor_response,*rsp.get('nuu_support_responses',[])])
                                if literal_candidate:
                                    ats=obj.get('_ats_response')
                                    item.update(publication_date_state='not_stated' if date is None else 'literal_publication_block',hiring_organisation_basis=obj['_employer_basis'],
                                        deadline_basis=obj['_deadline_basis'],application_url=ats['url'] if ats else obj['_application_url'],
                                        status=('listed_vacancy; literal deadline checked; application acceptance not tested' if obj.get('validThrough') else 'published first-party vacancy invitation; deadline not stated; application acceptance not tested'))
                                    if obj.get('_application_contact'):item['application_contact']=obj['_application_contact']
                                    if obj.get('_deadline_text'):
                                        item['deadline_text']=obj['_deadline_text']
                                        item['status']='published first-party vacancy invitation; rolling ASAP, no calendar deadline; application acceptance not tested'
                                    evidence_responses.extend(([ats] if ats else [])+[anchor_response])
                                if not any(i['url']==item['url'] and str(i['date'])[:10]==str(item['date'])[:10] for i in items): items.append(item)
                                evidence_responses.append(rsp);positive_responses.append(rsp)
                    add('website.'+field,items or None,positive_responses[0] if positive_responses else anchor_response,excerpt=items[0]['title'] if items else None,state='ambiguous' if not items and limitations else None,pointer=('JSON-LD, article:published_time, scoped published time or labelled CMS publication block on editorial detail pages' if field=='activity' else 'JobPosting, explicit first-party named vacancy invitation, matching linked public ATS deadline, or Vilect labelled fields and publication metadata with a verified company chain; unknown publication/deadline dates stay null'))
                    if limitations:
                        claims[-1]['qualifiers']={'coverage':'partial' if items else 'unresolved',
                            'candidate_limitations':limitations}
                    for rsp in evidence_responses:
                        source_text=Page(rsp.get('text',''),rsp['url']).text
                        literal_title=next((item['title'] for item in items if item['title'] in source_text),None)
                        extra=claim('website.'+field,None,rsp,evidence,pointer='literal post title and source snapshot; unknown publication date is not inferred',excerpt=literal_title)
                        claims[-1]['evidence_ids']=list(dict.fromkeys(claims[-1]['evidence_ids']+extra['evidence_ids']))
                # Verify social destinations after collecting dated activity, so
                # the small social budget cannot starve post detail discovery.
                from attribution import canonical_profile, declared_profiles, profile_identity
                declarations=declared_profiles(content_pages,data)
                from social_ownership import asserted_profiles
                assertions,contradictions=asserted_profiles(content_pages,data)
                candidates={};social_sources=[];social_limitations=[];social=[]
                for pg,rsp in content_pages:
                    for link in pg.links:
                        profile=canonical_profile(link['url'])
                        if profile and not link.get('third_party_context'):
                            candidates.setdefault(profile,(link,rsp))
                for profile,sources in declarations.items():
                    candidates.setdefault(profile,({'text':''},sources[0]))
                for profile,records in assertions.items():
                    candidates.setdefault(profile,({'text':'','url':records[0]['proof']['source_href']},records[0]['response']))
                checked=0
                for profile,(link,rsp) in list(candidates.items())[:20]:
                    proof=None;supports=[rsp]
                    ownership_evidence=None
                    if profile in contradictions:
                        social_limitations.append({'url':profile,'state':'ambiguous','reason':contradictions[profile]})
                    elif profile in declarations:
                        proof='exact_entity_sameAs_declaration';supports+=declarations[profile]
                    elif profile in assertions:
                        proof='explicit_company_declaration_and_entity_identifier'
                        ownership_evidence=[record['proof'] for record in assertions[profile]][:3]
                        supports += [record['response'] for record in assertions[profile]]
                        if any(record['proof'].get('historical_name_binding') for record in assertions[profile]):
                            supports.append(entity)
                    elif checked<2 and fetcher.requests<fetcher.limit-1:
                        checked+=1
                        destination=fetcher.get(link.get('url') or profile,site=True,raw=True)
                        supports.append(destination)
                        if destination['status']=='available' and canonical_profile(destination['url'])==profile:
                            proof=profile_identity(Page(destination.get('text',''),destination['url']),data,response['url'])
                        if not proof:
                            social_limitations.append({'url':profile,'state':destination['status'],
                                'reason':'destination ownership could not be established; a footer link alone is insufficient'})
                    else:
                        social_limitations.append({'url':profile,'state':'ambiguous',
                            'reason':'bounded destination checks exhausted; ownership unverified'})
                    if proof:
                        item={'url':profile,'text':link['text'].strip(),'attribution':proof}
                        if ownership_evidence:item['ownership_evidence']=ownership_evidence
                        social.append(item)
                    social_sources+=supports
                add('website.social_links',social or None,anchor_response,
                    state='ambiguous' if not social and social_limitations else None,
                    pointer='exact-entity sameAs, scoped company social declaration with full entity identifier, or public destination identity; isolated footer links withheld')
                claims[-1]['qualifiers']={'profile_ownership':'company_declared_or_destination_corroborated' if social else 'unresolved',
                    'coverage':'partial' if social_limitations and social else 'unresolved' if social_limitations else 'checked',
                    'candidate_limitations':social_limitations}
                for rsp in social_sources:
                    extra=claim('supporting',None,rsp,evidence)
                    claims[-1]['evidence_ids']=list(dict.fromkeys(claims[-1]['evidence_ids']+extra['evidence_ids']))
                break
            else:
                errors.append({'source':response['url'],'reason':'exact legal entity not established; no website facts published'})
    current_hiring=next((c for c in claims if c['field']=='website.hiring'),None)
    if public_jobs_result is None and (not current_hiring or current_hiring.get('availability')!='available') and fetcher.requests<fetcher.limit-2:
        public_jobs()
    if public_jobs_result:
        records=public_jobs_result['records']
        if records:
            from public_recruiting import job_key
            old_items=(current_hiring.get('value') or []) if current_hiring and current_hiring.get('availability')=='available' else []
            items=list(old_items);known_keys={job_key(i) for i in items}
            for record in records:
                key=job_key(record['item'])
                if key not in known_keys:items.append(record['item']);known_keys.add(key)
            added=claim('website.hiring',items,records[0]['response'],evidence,
                pointer='public board search URL leads; current detail plus explicit corporate number and exact employer; independent of website verification',excerpt=records[0]['item']['title'])
            if current_hiring:
                ids=current_hiring.get('evidence_ids',[]);qualifiers=current_hiring.get('qualifiers',{})
                current_hiring.update(added);current_hiring['evidence_ids']=list(dict.fromkeys(ids+added['evidence_ids']))
            else:
                current_hiring=added;claims.append(current_hiring);qualifiers={}
            current_hiring['qualifiers']={**qualifiers,'public_board_attribution':'published corporate number matches target or registered child; exact named employer',
                'website_identity_independent':True,'coverage':'bounded public ad search; not all possible vacancies'}
            for rsp in [*[r['response'] for r in records],entity,locations]:
                extra=claim('job_identity_support',None,rsp,evidence,pointer='retained primary ad or official parent/child identity response')
                current_hiring['evidence_ids']=list(dict.fromkeys(current_hiring['evidence_ids']+extra['evidence_ids']))
        output['public_recruitment_discovery']={'checks':public_jobs_result['checks'],'detail_attempts':public_jobs_result['detail_attempts'],
            'verified_ads':len(records),'website_leads':public_jobs_result['website_leads'],
            'source_mode':'anonymous public FINN/NAV pages, robots/TLS/IP checks on; URLs are leads only; same20-request cap'}
    for field in ('website.verified_url','website.description','website.social_links','website.hiring','website.activity','website.contact_channels'):
        if not any(c['field']==field for c in claims):
            if operator_limits:
                blocker,operator=operator_limits[0]
                add(field,None,blocker,state='ambiguous',pointer='current WebSite publisher/operator assertion',
                    excerpt=None)
                claims[-1]['identity_support']=operator
                claims[-1]['qualifiers']={'own_entity_attribution':'unresolved','reason':operator['reason']}
                for rsp,proof in operator_limits:
                    extra=claim('operator_support',None,rsp,evidence)
                    claims[-1]['evidence_ids']=list(dict.fromkeys(claims[-1]['evidence_ids']+extra['evidence_ids']))
                extra=claim('identity_anchor',org,entity,evidence)
                claims[-1]['evidence_ids']=list(dict.fromkeys(claims[-1]['evidence_ids']+extra['evidence_ids']))
            else:
                # A later failed alias cannot erase an earlier page whose legal
                # identity remained unresolved. This changes diagnostics, not facts.
                unresolved=unverified_pages[0] if unverified_pages else webstate
                add(field,None,unresolved,state=unresolved['status'] if unresolved['status']!='available' else 'ambiguous')
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
    if hasattr(fetcher,'public_search_discovery'):output['public_search_discovery']=fetcher.public_search_discovery
    from output_contract import complete_envelope
    return complete_envelope(output)

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--input',required=True); p.add_argument('--output',required=True)
    p.add_argument('--cache',default='cache'); p.add_argument('--previous')
    mode=p.add_mutually_exclusive_group();mode.add_argument('--replay',action='store_true');mode.add_argument('--fresh',action='store_true')
    p.add_argument('--workers',type=int,default=4)
    p.add_argument('--public-search',choices=['auto','off'],default='off',help='late anonymous Mwmbl URL discovery, no key or paid fallback')
    p.add_argument('--public-jobs',choices=['auto','off'],default='auto',help='bounded anonymous FINN/NAV discovery; same shared request cap')
    p.add_argument('--search',choices=['none','tavily','tavily-free'],default='none')
    p.add_argument('--search-free-credit-limit',type=int,help='root-confirmed remaining free basic credits; requires account/PayGo verification')
    p.add_argument('--search-credit-limit',type=int,default=100)
    p.add_argument('--search-strategy',choices=['legacy','name_focus','adaptive'],default='legacy')
    p.add_argument('--registry-snapshot',help='Frozen registry responses in the documented local JSONL interchange format')
    args=p.parse_args(); rows=[json.loads(x) for x in Path(args.input).read_text().split('\n') if x.strip()]
    registry_snapshot=None
    if args.registry_snapshot:
        from frozen_registry import FrozenRegistry
        registry_snapshot=FrozenRegistry(args.registry_snapshot)
    from free_search import AnonymousSearch
    anonymous_search=AnonymousSearch() if args.public_search=='auto' else None
    search=None
    if args.search in ('tavily','tavily-free'):
        from search import TavilySearch,FreeTavilySearch
        if args.search=='tavily-free':
            if args.search_free_credit_limit is None:
                p.error('--search tavily-free requires --search-free-credit-limit with a root-confirmed allowance')
            search=FreeTavilySearch(args.cache,args.search_credit_limit,
                strategy=args.search_strategy,free_credit_limit=args.search_free_credit_limit)
        else:
            search=TavilySearch(args.cache,args.search_credit_limit,strategy=args.search_strategy)
        if not args.replay and not search.key: p.error('TAVILY_API_KEY is required for live search; no account was created')
    elif args.search_free_credit_limit is not None:
        p.error('--search-free-credit-limit is valid only with --search tavily-free')
    prior={r['organisation_number']:r for r in (json.loads(x) for x in Path(args.previous).read_text().split('\n') if x.strip())} if args.previous else {}
    output=Path(args.output); output.parent.mkdir(parents=True,exist_ok=True); start=time.monotonic()
    def work(row):
        fetcher=Fetcher(args.cache,replay=args.replay,fresh=args.fresh,registry_snapshot=registry_snapshot,public_jobs=args.public_jobs!='off',public_search=anonymous_search)
        try: return research(row,fetcher,prior.get(str(row.get('organisation_number',''))),search)
        except Exception as error:
            return {'organisation_number':str(row.get('organisation_number','')),'run':{'terminal_status':'failed','completed_at':now()},
                'claims':[],'evidence':[],'changes':[],'errors':[{'reason':type(error).__name__+': '+str(error)}],
                'source_snapshots':[], 'previous_snapshot':prior.get(str(row.get('organisation_number',''))),
                'refresh':{'mode':'collector_failed','changed_fields':[],'cache_declared':True}, 'synthesis':[],
                'operations':{'requests':fetcher.requests,'cache_hits':fetcher.hits,'third_party_cost_usd':getattr(fetcher,'discovery',{}).get('paid_cost_usd',0)}}
    results=[]
    with output.open('w') as target, concurrent.futures.ThreadPoolExecutor(max_workers=max(1,min(8,args.workers))) as pool:
        for i,result in enumerate(pool.map(work,rows),1):
            results.append(result); target.write(encode(result)+'\n'); target.flush()
            if i%10==0: print(encode({'completed':i,'total':len(rows)}),flush=True)
    report={'inputs':len(rows),'outputs':len(results),'failed':sum(r['run']['terminal_status']=='failed' for r in results),
        'requests':sum(r['operations']['requests'] for r in results),'runtime_seconds':round(time.monotonic()-start,2),
        'third_party_cost_usd':None if search and search.attempts else 0,
        'public_search_request_attempts':anonymous_search.attempts if anonymous_search else 0,
        'search_request_attempts':search.attempts if search else 0,
        'search_basic_credit_upper_bound':search.attempts if search else 0,
        'coverage':dict(collections.Counter(c['field'] for r in results for c in r['claims'] if c['availability']=='available')),
        'source_statuses':dict(collections.Counter(c['availability'] for r in results for c in r['claims'])),
        'official_score':None,'replay':args.replay,
        'registry_snapshot_sha256':registry_snapshot.artifact_sha256 if registry_snapshot else None}
    output.with_suffix('.report.json').write_text(json.dumps(report,indent=2)); print(json.dumps(report,indent=2))

if __name__=='__main__': main()
