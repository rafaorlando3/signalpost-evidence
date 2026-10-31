"""Bounded job-board delegation from verified first-party career links.

No platform search or account access. A career link is a discovery lead, never
proof that a posting's hiring entity is the requested organisation.
"""
import re
from urllib.parse import urlsplit,urljoin,urlunsplit


def delegated_hiring_pages(content_pages, fetcher, page_type):
    seeds=[];seen={rsp['url'] for _,rsp in content_pages};out=[]
    for page,rsp in content_pages:
        for link in page.links:
            u=link.get('url','');text=link.get('text','')
            try:
                p=urlsplit(u);port=p.port
            except ValueError:continue
            if p.scheme not in ('http','https') or not p.hostname or p.username or p.password:continue
            if port not in (None,80,443) or link.get('third_party_context'):continue
            if re.search(r'login|sign[-_]?in|profile|apply|application',p.path,re.I):continue
            if not re.search(r'\b(?:careers?|karriere|jobbe?\s+(?:hos|i)|ledige\s+stillinger|vacancies|jobs?)\b',text,re.I):continue
            if p.hostname==urlsplit(rsp['url']).hostname:continue
            u=urlunsplit((p.scheme,p.netloc,p.path,p.query,''))
            if u not in seeds:seeds.append(u)
    # Two career endpoints total; remaining requests are reserved for evidence.
    while seeds and len(out)<2 and fetcher.requests<fetcher.limit-2:
        u=seeds.pop(0)
        if u in seen:continue
        seen.add(u);rsp=fetcher.get(u,site=True,raw=True)
        if rsp['status']!='available':continue
        pg=page_type(rsp.get('text',''),rsp['url'])
        if re.search(r'\b(?:sign in|logg inn|access denied|captcha)\b',pg.title,re.I):continue
        rsp={**rsp,'identity_verified':False,'delegated_from_verified_careers':True}
        out.append((pg,rsp))
        # Follow only explicit job-detail links within the observed career host.
        for link in pg.links:
            v=link['url']
            try:q=urlsplit(v);port=q.port
            except ValueError:continue
            if (q.hostname==urlsplit(rsp['url']).hostname and q.scheme in ('http','https')
                    and not q.username and not q.password and port in (None,80,443)
                    and re.search(r'/(?:jobs?|positions?|vacancies|stillinger)/[^/?]+',q.path,re.I)
                    and not re.search(r'login|apply|profile',q.path,re.I) and v not in seen):
                seeds.append(v)
    return out
