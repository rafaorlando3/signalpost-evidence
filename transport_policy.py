"""Identified HTTP requests, bounded retries and non-secret diagnostics."""
import datetime as dt
import email.utils
import http.client
import re
import socket
import ssl
import collections
import copy
import threading
import time
from urllib.parse import urlsplit,quote


def request_target(url):
    """Encode an observed internationalized path/query for an HTTP request.

    Preserve existing percent escapes and reserved separators. Destination,
    TLS, redirect, robots and request-budget checks stay with Fetcher.
    """
    p=urlsplit(url)
    if any(ord(c)<32 or ord(c)==127 for c in p.path+p.query):
        raise ValueError('Control character in HTTP request target')
    path=quote(p.path or '/',safe="/:@!$&'()*+,;=-._~%")
    query=quote(p.query,safe="/?:@!$&'()*+,;=-._~%[]")
    return path+('?' +query if query else '')


class RunRobotsCache:
    """Short run-local reuse of successful/unavailable robots responses only.

    Policy parsing/enforcement remains in Fetcher. Failed, protected and
    rate-limited responses are never cached here. No cross-run/disk trust.
    """
    def __init__(self, ttl=300, clock=None, max_entries=512):
        self.ttl=ttl;self.clock=clock or time.monotonic;self.max_entries=max_entries
        self.lock=threading.Lock();self.host_locks=collections.defaultdict(threading.Lock)
        self.entries={};self.hits=0;self.loads=0

    def get(self, origin, load, deadline):
        with self.lock:guard=self.host_locks[origin]
        if not guard.acquire(timeout=max(0,deadline-self.clock())):
            raise TimeoutError('shared robots lookup exceeds remaining company deadline')
        try:
            if self.clock()>=deadline:
                raise TimeoutError('shared robots lookup exceeds remaining company deadline')
            with self.lock:
                cached=self.entries.get(origin)
                if cached and cached[0]>self.clock():
                    self.hits+=1
                    return copy.deepcopy(cached[1]),True
                self.loads+=1
            response=load()
            code=response.get('status_code')
            reusable=(code==200 and response.get('status')=='available') or code in (404,410)
            ttl=self.ttl
            headers=response.get('response_headers') or {}
            control=headers.get('cache-control','')
            if re.search(r'(?:^|,)\s*(?:no-cache|no-store|private)(?:[=,\s]|$)',control,re.I):ttl=0
            age=headers.get('age','0')
            age=int(age) if isinstance(age,str) and re.fullmatch(r'\d+',age) else 0
            max_age=re.search(r'(?:^|,)\s*max-age\s*=\s*"?(\d+)"?(?:\s*,|\s*$)',control,re.I)
            if max_age:ttl=min(ttl,max(0,int(max_age[1])-age))
            if reusable and ttl>0 and isinstance(response.get('text',''),str) and len(response.get('text',''))<=256_000:
                with self.lock:
                    if len(self.entries)>=self.max_entries:
                        self.entries={k:v for k,v in self.entries.items() if v[0]>self.clock()}
                        if len(self.entries)>=self.max_entries:self.entries.pop(next(iter(self.entries)))
                    self.entries[origin]=(self.clock()+ttl,copy.deepcopy(response))
            return response,False
        finally:guard.release()

    def summary(self):
        with self.lock:return {'policy_cache_hits':self.hits,'policy_loads':self.loads,'ttl_seconds':self.ttl,
                              'scope':'run-local same-origin robots200/404/410 only; policy remains enforced'}


def request_headers(url,ua):
    accept=('application/json,text/plain;q=0.9,*/*;q=0.5' if urlsplit(url).hostname=='data.brreg.no' else
            'text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.7')
    return {'User-Agent':ua,'Accept':accept,'Accept-Language':'nb,en;q=0.8','Accept-Encoding':'identity'}


def retained_headers(response):
    # Never retain cookies, authentication or arbitrary response headers.
    names=['Server','Retry-After','CF-Ray','CF-Mitigated','Content-Type','Content-Length','Cache-Control','Age']
    return {k.casefold():v[:250] for k in names if isinstance((v:=response.getheader(k)),str)}


def retry_delay(value,at=None):
    if not isinstance(value,str):return 1.0
    if re.fullmatch(r'\s*\d+\s*',value):return max(1.0,float(value))
    try:
        stamp=email.utils.parsedate_to_datetime(value)
        if stamp.tzinfo is None:stamp=stamp.replace(tzinfo=dt.timezone.utc)
        return max(1.0,(stamp-(at or dt.datetime.now(dt.timezone.utc))).total_seconds())
    except (ValueError,TypeError,OverflowError):return 1.0


def error_kind(error):
    if isinstance(error,socket.gaierror):return 'dns'
    if isinstance(error,ssl.SSLCertVerificationError):return 'tls_certificate'
    if isinstance(error,ssl.SSLError):return 'tls'
    if isinstance(error,TimeoutError):return 'timeout'
    if isinstance(error,ConnectionRefusedError):return 'connection_refused'
    if isinstance(error,ConnectionError):return 'connection'
    if isinstance(error,http.client.HTTPException):return 'http_protocol'
    if isinstance(error,ValueError):return 'url_policy_or_decode'
    return 'network_or_io'


def protection_markers(headers,text):
    title=re.search(r'<title[^>]*>(.*?)</title>',text[:200_000],re.I|re.S)
    title=re.sub(r'<[^>]+>',' ',title[1]).strip() if title else ''
    challenge=bool(headers.get('cf-mitigated','').casefold()=='challenge' or
        (re.search(r'just a moment|checking your browser|attention required',title,re.I) and
         re.search(r'cf-chl-|challenge-platform|enable javascript and cookies',text,re.I)))
    return {'cf_ray_present':bool(headers.get('cf-ray')),
            'server_cloudflare':headers.get('server','').casefold()=='cloudflare',
            'javascript_challenge':challenge}
