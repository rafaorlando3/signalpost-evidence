"""Identified HTTP requests, bounded retries and non-secret diagnostics."""
import datetime as dt
import email.utils
import http.client
import re
import socket
import ssl
from urllib.parse import urlsplit


def request_headers(url,ua):
    accept=('application/json,text/plain;q=0.9,*/*;q=0.5' if urlsplit(url).hostname=='data.brreg.no' else
            'text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.7')
    return {'User-Agent':ua,'Accept':accept,'Accept-Language':'nb,en;q=0.8','Accept-Encoding':'identity'}


def retained_headers(response):
    # Never retain cookies, authentication or arbitrary response headers.
    names=['Server','Retry-After','CF-Ray','CF-Mitigated','Content-Type','Content-Length']
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
