"""Bounded, same-host discovery from public XML. XML metadata is not fact evidence."""
import re
from urllib.parse import urljoin, urlsplit, urlunsplit
import xml.etree.ElementTree as ET


def scoped_context(tag, context):
    """Squarespace body style switches are not local author/share owners."""
    if tag!='body':return context
    return ' '.join(token for token in context.split()
                    if token.casefold() not in {'hide-article-author','show-article-author','product-social-sharing'})


def excluded_content_url(url):
    """Assets and action/confirmation endpoints are not research documents."""
    path=urlsplit(url).path
    return bool(re.search(r"\.(?:pdf|jpe?g|png|gif|svg|webp|avif|ico|bmp|tiff?|woff2?|ttf|eot|mp[34]|webm|mov|zip|gz|css|js)$",path,re.I)
                or re.search(r"(?:^|/)(?:contact-form-confirmation|form-confirmation|submit|logout)(?:/|$)",path,re.I))


def identity_content_candidate(url):
    """Drop an isolated cookie-dialog UI toggle from an identity-page lead.

    The requested content response still supplies all identity evidence. Other
    query parameters, including combined/versioned queries, are left intact.
    """
    try:
        p=urlsplit(url)
        if p.scheme in {'http','https'} and not p.username and not p.password and p.query=='cookie_settings=true':
            return urlunsplit((p.scheme,p.netloc,p.path,'',''))
    except ValueError:pass
    return url


def xml_candidates(text, source_url, host, *, canonical_alias=False):
    if len(text)>2_000_000 or re.search(r'<!\s*(DOCTYPE|ENTITY)\b',text,re.I):
        return [],[]
    try: root=ET.fromstring(text)
    except (ET.ParseError, ValueError): return [],[]
    def tag(e): return e.tag.rsplit('}',1)[-1] if isinstance(e.tag,str) else ''
    kind=tag(root)
    if kind not in {'urlset','sitemapindex','rss','feed'}: return [],[]
    pages=[];maps=[];seen=set()
    # Only top-level <url>/<sitemap> locations. Image/video extension loc
    # elements are assets, not candidate company pages. lastmod orders leads
    # only and is never exported as a publication date.
    if kind in {'urlset','sitemapindex'}:
        entries=[]
        for entry in root:
            loc=next((e for e in entry if tag(e)=='loc'),None)
            modified=next((str(e.text or '') for e in entry if tag(e)=='lastmod'),'')
            if loc is not None:entries.append((loc,modified))
        if kind=='urlset':entries.sort(key=lambda x:x[1] if re.match(r'20[0-9]{2}-[0-9]{2}-[0-9]{2}',x[1]) else '',reverse=True)
        elements=[x[0] for x in entries]
    else:
        # Feed/channel home links and reply/comment endpoints are navigation,
        # not individual post leads. Only item/entry alternate links count.
        elements=[link for entry in root.iter() if tag(entry) in {'item','entry'}
                  for link in entry if tag(link)=='link']
    for el in elements:
        name=tag(el); value=None
        if name=='loc' and kind in {'urlset','sitemapindex'}: value=el.text
        elif name=='link' and kind in {'rss','feed'}:
            if el.get('rel','alternate') not in {'alternate',''}: continue
            value=el.get('href') or el.text
        if not value: continue
        try:
            p=urlsplit(urljoin(source_url,value.strip()))
            if p.scheme not in {'http','https'} or p.username or p.password or p.port not in (None,80,443):continue
            if p.hostname!=host:
                if not canonical_alias or (p.hostname or '').casefold().removeprefix('www.')!=host.casefold().removeprefix('www.'):continue
                # URL lead only: request the path on the already verified host.
                # Never grant identity or share facts from the alternate host.
                p=p._replace(netloc=host)
            url=urlunsplit((p.scheme,p.netloc,p.path,p.query,''))
        except ValueError:continue
        if url in seen:continue
        seen.add(url)
        (maps if kind=='sitemapindex' else pages).append(url)
        if len(seen)>=500:break
    return pages,maps
