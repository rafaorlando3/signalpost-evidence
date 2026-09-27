"""Bounded, same-host discovery from public XML. XML metadata is not fact evidence."""
import re
from urllib.parse import urljoin, urlsplit, urlunsplit
import xml.etree.ElementTree as ET


def xml_candidates(text, source_url, host):
    if len(text)>2_000_000 or re.search(r'<!\s*(DOCTYPE|ENTITY)\b',text,re.I):
        return [],[]
    try: root=ET.fromstring(text)
    except (ET.ParseError, ValueError): return [],[]
    def tag(e): return e.tag.rsplit('}',1)[-1] if isinstance(e.tag,str) else ''
    kind=tag(root)
    if kind not in {'urlset','sitemapindex','rss','feed'}: return [],[]
    pages=[];maps=[];seen=set()
    for el in root.iter():
        name=tag(el); value=None
        if name=='loc' and kind in {'urlset','sitemapindex'}: value=el.text
        elif name=='link' and kind in {'rss','feed'}:
            if el.get('rel','alternate') not in {'alternate',''}: continue
            value=el.get('href') or el.text
        if not value: continue
        try:
            p=urlsplit(urljoin(source_url,value.strip()))
            if p.scheme not in {'http','https'} or p.hostname!=host or p.username or p.password or p.port not in (None,80,443):continue
            url=urlunsplit((p.scheme,p.netloc,p.path,p.query,''))
        except ValueError:continue
        if url in seen:continue
        seen.add(url)
        (maps if kind=='sitemapindex' else pages).append(url)
        if len(seen)>=500:break
    return pages,maps
