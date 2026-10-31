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
                if len(data)>2_000_000:return self.failure(current,'blocked','decoded response size limit')
                charset = response.headers.get_content_charset() or 'utf-8'
                text = data.decode(charset, errors='replace')
                state = 'available' if status == 200 else 'not_available' if status in (404,410) else 'blocked' if status in (401,403,429) else 'failed'
                result = {'url':current, 'requested_url':url, 'status':state, 'status_code':status,
                    'retrieved_at':now(), 'content_sha256':wire_digest, 'text':text}
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
        self.url=url; self.raw_html=text; self.parts=[]; self.links=[]; self.ld=[]; self.skip=0; self.script=None
        self.title=''; self.in_title=False; self.description=''; self.anchor=None;self.meta={};self.post_container=False
        self.headings=[];self.heading=None;self.times=[];self.feeds=[];self.link_context=[]
        self.content_headings=[];self.content_times=[];self.main_headings=[];self.main_times=[];self.semantic_headings=[];self.heading_is_semantic=False;self.heading_is_main=False;self.heading_is_content=False;self.body_parts=[];self.post_parts=[];self.main_parts=[]
        self.footer_parts=[];self.paragraphs=[];self.paragraph=None;self.paragraph_is_content=False
        self.feed(text)

    def content_scope(self):
        # A post's own <article><header> is content. Site navigation headers
        # remain chrome; merely nesting an article inside a global header does
        # not turn that global header into a publication source.
        tags=[t for t,_ in self.link_context]
        if any(t in {'head','title','nav','footer','aside','form','dialog'} for t in tags):return False
        for index,tag in enumerate(tags):
            if tag=='header' and 'article' not in tags[:index]:return False
        return True

    def handle_starttag(self, tag, attrs):
        a=dict(attrs)
        context=' '.join((a.get(k) or '') for k in ('class','id','aria-label','title','data-sentry-component','data-sentry-source-file'))
        post_context=re.sub(r'(?<=[a-z])(?=[A-Z])',' ',a.get('class') or '').replace('_',' ')
        if tag=='article' and re.search(r'(?:^|\s)type-post(?:\s|$)|\bsingle[ -]+post\b',post_context,re.I):self.post_container=True
        third_party=(self.link_context[-1][1] if self.link_context else False) or bool(re.search(r'sponsor|partner|customer|testimonial|shar(?:e|ing)|author|agency|webdesign|site-credit|powered-by|theme-credit',context,re.I))
        if tag not in {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}:
            self.link_context.append((tag,third_party))
        if tag=='img' and self.anchor and re.search(r'sponsor|partner|customer',(a.get('alt') or ''),re.I):
            self.anchor['third_party_context']=True
        if tag in ('script','style','noscript'):
            self.skip += 1
            if tag=='script' and a.get('type')=='application/ld+json': self.script=[]
        if tag=='p':
            self.paragraph=''
            self.paragraph_is_content=not self.skip and not third_party and self.content_scope()
        if tag=='title': self.in_title=True
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
        if tag=='a' and a.get('href'):
            try:self.anchor={'url':urljoin(self.url,a['href']), 'text':'','third_party_context':third_party,'in_navigation':any(t in {'nav','header','footer','aside'} for t,_ in self.link_context)}
            except ValueError:self.anchor=None

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
                if any(t=='article' for t,_ in self.link_context):self.post_parts.append(value)
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
    # Whole path words: 'bestillinger' means orders, not 'stillinger' (jobs).
    if re.search(r'(?:^|[/_-])(?:karriere|careers?|jobb(?:er|e)?|jobs?|stillinger?|vacanc(?:y|ies))(?:$|[/_-])',path): return 'hiring'
    if re.search(r'(?:^|[/_-])(?:news|nyheter?|aktuelt|blogg?|presse|press|artikler|articles?|stories|insights)(?:$|[/_-])|/20\d{2}/',path): return 'activity'
    if re.search(r'kontakt|contact|personvern|privacy|beting|vilk|impressum|legal|om-oss|about',path): return 'identity'
    return None

def article_detail(url):
    return bool(re.search(r'/(?:news|nyheter?|aktuelt|blogg?|presse|press|artikler|articles?|stories|insights)(?:[-_](?:og[-_])?(?:presse|press|news))?/[^/]+|/20\d{2}/',urlsplit(url).path,re.I))

def social_profile(url):
    from attribution import canonical_profile
    return canonical_profile(url) is not None


def crawl_company(org, data, response, fetcher, *, registry_redirect_host=None, reserve_requests=0, seed_urls=()):
    """Explore distinct purposes and linked detail pages within the existing request cap."""
    home=Page(response.get('text',''),response['url']); host=urlsplit(response['url']).hostname
    pages=[];verified=[];seen={urlunsplit((*urlsplit(response['url'])[:4],''))};queue={};counts=collections.Counter();discovered=False
    post_leads={}
    operator_blocked=False;known_operator=None
    def ingest(page,rsp):
        nonlocal operator_blocked,known_operator
        operator=site_operator_identity(org,page,data,response['url'])
        if page is home and operator['state']=='absent':
            from attribution import group_site_reason
            reason=group_site_reason(page,data)
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
        for link in page.links:
            url=urlunsplit((*urlsplit(link['url'])[:4],''));family=link_family(url)
            if family is None:
                label=normalized(link['text'])
                if re.search(r'\b(kontakt|contact|personvern|privacy|om oss|about us)\b',label): family='identity'
            if (family not in ('identity',) and verified and link_family(rsp['url'])=='activity'
                    and not link.get('in_navigation') and not link.get('third_party_context')
                    and len(link['text'].strip())>=5 and urlsplit(url).path not in ('','/')
                    and url!=rsp['url']):
                # A real post may use a root slug. This only discovers it;
                # publication still requires dated, scoped article evidence.
                family='activity'
                post_leads.setdefault(url,len(post_leads))
            if family and urlsplit(url).scheme in ('https','http') and urlsplit(url).hostname==host and url not in seen:
                queue[url]=family
        return True
    if not ingest(home,response): return [],pages
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
            sources.extend(sorted(maps,key=lambda u:(0 if re.search(r'post|news',u,re.I) else 1 if re.search(r'page',u,re.I) else 2,u)))
            for candidate in urls:
                family=link_family(candidate)
                if (family is None and verified and re.search(r'post|news|feed',url,re.I)
                        and not re.search(r'\.(?:pdf|jpe?g|png|gif|svg|webp|mp4|xml)(?:$|[?#])',candidate,re.I)):
                    family='activity'
                if family and candidate not in seen:queue.setdefault(candidate,family)
    while len(seen)<12 and fetcher.requests<fetcher.limit-(0 if verified else reserve_requests):
        # An already fetched news index provides stronger discovery leads than
        # another map request. XML remains a fallback when those leads run out.
        pending_posts=any(u not in seen and u in queue for u in post_leads)
        if not discovered and (not queue or (verified and len(seen)>=4 and not pending_posts)):
            discovered=True;discover()
        if not queue:break
        def rank(item):
            url,family=item
            base=({'hiring':0,'activity':1,'identity':5} if verified else {'identity':0,'hiring':5,'activity':6})[family]
            depth=len([s for s in urlsplit(url).path.split('/') if s])
            # Inspect legal ownership before repeatedly exploring auxiliary
            # identity pages; still leave a balanced path to jobs and articles.
            legal=bool(re.search(r'personvern|privacy|legal|impressum|vilk|beting',urlsplit(url).path,re.I))
            penalty=counts[family]*4
            identity_order=0 if legal else 1 if re.search(r'kontakt|contact|kundeservice',urlsplit(url).path,re.I) else 2
            detail_order=post_leads.get(url,10_000+list(queue).index(url)) if family=='activity' else list(queue).index(url)
            return (base+penalty, identity_order if family=='identity' and verified else 0,
                    (0 if verified else depth),detail_order,len(url),url)
        url,family=min(queue.items(),key=rank);del queue[url];seen.add(url);counts[family]+=1
        child=fetcher.get(url,site=True,raw=True)
        if child['status']!='available' or urlsplit(child['url']).hostname!=host: continue
        ingest(Page(child.get('text',''),child['url']),child)
        if operator_blocked:break
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
    product_or_index=False
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
        if not same_page(obj.get('url')) or not same_page(obj.get('mainEntityOfPage')):
            limit('article describes another URL; fetch its own page before attribution')
            continue
        if not (types & {'NewsArticle','BlogPosting'}) and not article_detail(response['url']) and not page.post_container:
            limit('generic Article outside a dated-activity detail path')
            continue
        if product_or_index:
            limit('product or collection metadata does not establish a real post')
            continue
        if not (isinstance(obj.get('articleBody'),str) and len(obj['articleBody'].strip())>=80) and (not page.content_headings or len(' '.join(page.article_parts).strip())<80):
            limit('structured article lacks visible post heading/body')
            continue
        candidates.append(obj)
    detail=article_detail(response['url']) or page.post_container
    headings=page.semantic_headings or page.main_headings or page.content_headings
    publication_times=page.main_times or page.content_times
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
                               'datePublished':visible})
        elif not publication_times and page.meta.get('article:published_time'):
            candidates.append({'@type':'NewsArticle',
                'headline':page.meta.get('og:title') or headings[0],
                'datePublished':page.meta['article:published_time']})
        elif publication_times:
            limit('multiple content publication dates; no unique date established')
    elif detail and (page.meta.get('article:published_time') or page.times):
        limit('publication metadata lacks a single content heading; menu/header/footer is insufficient')
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
        if street and postal and ' '+normalized(street)+' ' in text and re.search(r'(?<!\d)'+re.escape(postal)+r'(?!\d)',evidence_text):return True
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
            'content_sha256':response['content_sha256'], 'source_class':'official_registry' if response['url'].startswith(OFFICIAL+'/') else 'company_website' if response.get('identity_verified') else 'candidate_website',
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
    leads=registry_candidates(org,data,pick(locations.get('json') or {},'_embedded','underenheter') or [])
    webstate={'url':'','status':'not_available','retrieved_at':now()}
    attempts=[];operator_limits=[]
    def candidates():
        for index,lead in enumerate(leads):
            lead_url=lead['url'];parsed=urlsplit(lead_url)
            remaining=len(leads)-index-1+bool(search)+2
            yield lead_url,lead['origin'],remaining,[]
            # Ordinary canonical hostname candidate, independently identity-
            # checked. TLS validation, robots policy and public-IP checks stay on.
            if (parsed.hostname or '').startswith('www.'):
                root=parsed.hostname[4:]+(':'+str(parsed.port) if parsed.port else '')
                alternate=urlunsplit((parsed.scheme,root,parsed.path,parsed.query,''))
                yield alternate,'canonical_host_candidate',remaining,[]
        if search and data.get('navn'):
            if hasattr(search,'iter_candidates'):
                for url,remaining,hints in search.iter_candidates(org,data['navn'],fetcher):yield url,'search',remaining,hints
            else:
                urls=search.discover(org,data['navn'],fetcher)
                for i,url in enumerate(urls):yield url,'search',len(urls)-i-1,[]
        from registry_discovery import name_domain_candidates
        existing={host_key(lead['url']) for lead in leads}
        derived=[u for u in name_domain_candidates(data) if host_key(u) not in existing]
        for index,url in enumerate(derived):yield url,'name_domain_heuristic',len(derived)-index-1,[]
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
            blockers=[(rsp,rsp['site_operator']) for pg,rsp,identity in inspected
                      if rsp.get('site_operator',{}).get('state') in ('different','unresolved')]
            if blockers:
                operator_limits.extend(blockers)
                attempt['operator_limitations']=[operator for rsp,operator in blockers]
            if verified:
                verified=[(pg,{**rsp,'identity_verified':True}) for pg,rsp in verified]
                anchor,anchor_response=verified[0]
                # Same-host pages can inherit the established site identity, except conflicts.
                content_pages=[(pg,{**rsp,'identity_verified':True}) for pg,rsp,identity in inspected
                    if identity!='conflict' and urlsplit(rsp['url']).hostname==urlsplit(anchor_response['url']).hostname]
                method=('explicit_site_operator' if anchor_response.get('site_operator',{}).get('state')=='target' else
                        'explicit_org_number' if website_identity(org,anchor,data)=='exact' else
                        'exact_legal_footer_and_registered_address' if legal_footer_identity(data,anchor) else 'registry_domain_name_and_postal_address')
                add('website.verified_url',response['url'],anchor_response,pointer=method,
                    excerpt=identity_excerpt(org,anchor) if method=='explicit_org_number' else anchor.text[:1500])
                if method in {'registry_domain_name_and_postal_address','exact_legal_footer_and_registered_address'}:
                    extra=claim('identity_anchor',org,entity,evidence)
                    claims[-1]['evidence_ids']+=extra['evidence_ids']
                    claims[-1]['identity_support']=corroboration_evidence(data,anchor,response)
                    claims[-1]['evidence_excerpt']=None
                elif method=='explicit_site_operator':
                    claims[-1]['identity_support']=anchor_response['site_operator']
                    claims[-1]['evidence_excerpt']=None
                # Identity may be proved on a privacy/contact page. Describe the
                # homepage instead of publishing that legal page's boilerplate.
                description_page,description_response=content_pages[0]
                description=description_page.description
                if not isinstance(description,str) or len(description.strip())<20 or len(description.split())<4:
                    description=next((v for v in description_page.paragraphs if 70<=len(v)<=2000 or (len(v)>=20 and group_description(v))),None)
                if description and re.search(r'lorem ipsum|dolor sit amet|(?:web\s*site|nettside).{0,45}(?:under construction|coming soon|underveis|under arbeid)|^(?:under construction|coming soon)[.! ]*$',description,re.I):description=None
                if description:description=description[:700]
                collective=group_description(description or '')
                add('website.description',description or None,description_response,
                    state='ambiguous' if collective else None,
                    pointer='meta[name=description] or scoped visible homepage paragraph; navigation and footer excluded',excerpt=description)
                if collective:
                    claims[-1]['qualifiers']={'subject_scope':'group',
                        'own_entity_description':'not_established',
                        'reason':'explicit collective wording; legal site identity does not attribute group statements to this entity'}
                from contacts import entity_contacts
                contacts=[];contact_sources=[];seen_contacts=set();contact_limits=[]
                for pg,rsp in content_pages:
                    scoped,held=entity_contacts(pg,data,sites)
                    contact_limits.extend(held[:10])
                    for item in scoped:
                        key=(item['type'],item['value'])
                        if key not in seen_contacts and len(contacts)<10:
                            contacts.append(item);seen_contacts.add(key);contact_sources.append(rsp)
                contact_anchor=contact_sources[0] if contact_sources else anchor_response
                add('website.contact_channels',contacts or None,contact_anchor,excerpt=(contacts[0].get('source_href') or contacts[0]['value']) if contacts else None,
                    pointer='literal mailto/tel links on verified company pages; third-party and unresolved regional contact blocks excluded; ownership/use not independently checked')
                if contact_limits:
                    claims[-1]['qualifiers']={'coverage':'partial' if contacts else 'unresolved','candidate_limitations':contact_limits[:20]}
                for rsp in contact_sources:
                    item=next((c for c in contacts if c['source_url']==rsp['url']),None)
                    extra=claim('website.contact_channels',None,rsp,evidence,
                                pointer='literal contact href or visible company contact block',
                                excerpt=(item.get('source_href') or item['value']) if item else None)
                    claims[-1]['evidence_ids']=list(dict.fromkeys(claims[-1]['evidence_ids']+extra['evidence_ids']))
                from hiring_discovery import delegated_hiring_pages
                hiring_pages=content_pages+delegated_hiring_pages(content_pages,fetcher,Page)
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
                            candidates=list(objects(pg.ld))
                        for obj in candidates:
                            if schema_types(obj) & types:
                                if field=='activity' and not (schema_types(obj)&{'NewsArticle','BlogPosting'}) and not article_detail(rsp['url']) and not pg.post_container:
                                    continue
                                title=obj.get('title') or obj.get('headline')
                                date=obj.get('datePublished') if field=='activity' else obj.get('datePosted')
                                if not isinstance(title,str) or not isinstance(date,str):
                                    limitation(rsp,'candidate lacks a literal title and publication date')
                                    continue
                                try:
                                    dt.datetime.fromisoformat(date.replace('Z','+00:00'))
                                    if dt.date.fromisoformat(date[:10])>dt.date.fromisoformat(rsp['retrieved_at'][:10]):
                                        limitation(rsp,'candidate publication date is in the future')
                                        continue
                                except ValueError:
                                    limitation(rsp,'candidate publication date is not a valid ISO date')
                                    continue
                                if field=='hiring':
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
                                if field=='hiring': item.update(valid_through=obj.get('validThrough'),status='published_posting; application availability not independently checked')
                                if not any(i['url']==item['url'] and i['date'][:10]==item['date'][:10] for i in items): items.append(item)
                                evidence_responses.append(rsp);positive_responses.append(rsp)
                    add('website.'+field,items or None,positive_responses[0] if positive_responses else anchor_response,excerpt=items[0]['title'] if items else None,state='ambiguous' if not items and limitations else None,pointer=('JSON-LD, article:published_time, or a single h1/time[datetime] on detail pages' if field=='activity' else 'script[type=application/ld+json]; JobPosting'))
                    if limitations:
                        claims[-1]['qualifiers']={'coverage':'partial' if items else 'unresolved',
                            'candidate_limitations':limitations}
                    for rsp in evidence_responses:
                        source_text=Page(rsp.get('text',''),rsp['url']).text
                        literal_title=next((item['title'] for item in items if item['title'] in source_text),None)
                        extra=claim('website.'+field,None,rsp,evidence,pointer='literal post title; publication date retained in source snapshot',excerpt=literal_title)
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
                add(field,None,webstate,state=webstate['status'] if webstate['status']!='available' else 'ambiguous')
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
    from output_contract import complete_envelope
    return complete_envelope(output)

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--input',required=True); p.add_argument('--output',required=True)
    p.add_argument('--cache',default='cache'); p.add_argument('--previous')
    mode=p.add_mutually_exclusive_group();mode.add_argument('--replay',action='store_true');mode.add_argument('--fresh',action='store_true')
    p.add_argument('--workers',type=int,default=4)
    p.add_argument('--search',choices=['none','tavily','tavily-free'],default='none')
    p.add_argument('--search-free-credit-limit',type=int,help='root-confirmed remaining free basic credits; requires account/PayGo verification')
    p.add_argument('--search-credit-limit',type=int,default=100)
    p.add_argument('--search-strategy',choices=['legacy','name_focus','adaptive'],default='legacy')
    p.add_argument('--registry-snapshot',help='Frozen registry responses in the documented local JSONL interchange format')
    args=p.parse_args(); rows=[json.loads(x) for x in Path(args.input).read_text().splitlines() if x.strip()]
    registry_snapshot=None
    if args.registry_snapshot:
        from frozen_registry import FrozenRegistry
        registry_snapshot=FrozenRegistry(args.registry_snapshot)
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
    prior={r['organisation_number']:r for r in (json.loads(x) for x in Path(args.previous).read_text().splitlines())} if args.previous else {}
    output=Path(args.output); output.parent.mkdir(parents=True,exist_ok=True); start=time.monotonic()
    def work(row):
        fetcher=Fetcher(args.cache,replay=args.replay,fresh=args.fresh,registry_snapshot=registry_snapshot)
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
        'search_request_attempts':search.attempts if search else 0,
        'search_basic_credit_upper_bound':search.attempts if search else 0,
        'coverage':dict(collections.Counter(c['field'] for r in results for c in r['claims'] if c['availability']=='available')),
        'source_statuses':dict(collections.Counter(c['availability'] for r in results for c in r['claims'])),
        'official_score':None,'replay':args.replay,
        'registry_snapshot_sha256':registry_snapshot.artifact_sha256 if registry_snapshot else None}
    output.with_suffix('.report.json').write_text(json.dumps(report,indent=2)); print(json.dumps(report,indent=2))

if __name__=='__main__': main()
