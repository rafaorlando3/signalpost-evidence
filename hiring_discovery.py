"""Bounded job-board delegation from verified first-party career links.

No platform search or account access. A career link is a discovery lead, never
proof that a posting's hiring entity is the requested organisation.
"""
import datetime as dt
import re
from urllib.parse import urlsplit,urljoin,urlunsplit


def application_links(page):
    """Explicit public GET landing links, never an application submit endpoint."""
    out=[]
    for link in page.links:
        try:
            p=urlsplit(link.get('url',''));port=p.port
        except ValueError:continue
        if (p.scheme not in ('https','http') or not p.hostname or p.username or p.password
                or port not in (None,80,443) or link.get('third_party_context')):continue
        if not re.search(r'\b(?:søk\s+på\s+stilling|søk\s+stillingen|apply\s+(?:now|for|to))',link.get('text',''),re.I):continue
        # ApplicationInit is the public job-description GET view. Generic
        # login/profile/application/submit endpoints remain excluded.
        if not re.search(r'/ApplicationInit\.aspx$',p.path,re.I):continue
        if p.hostname==urlsplit(page.url).hostname:continue
        out.append(urlunsplit((p.scheme,p.netloc,p.path,p.query,'')))
    return list(dict.fromkeys(out))


def literal_hiring_candidates(page, response, data, hiring_pages):
    """Undated named first-party vacancy + matching linked public ATS deadline.

    Do not manufacture datePosted from a deadline, modified time or retrieval.
    Employer basis is the explicit legal site operator, not a group footer or
    an employer hidden inside an HTML comment on the ATS.
    """
    from agent import normalized
    if not response.get('identity_verified') or response.get('delegated_from_verified_careers'):return []
    operator=response.get('site_operator',{})
    if operator.get('state')!='target':return []
    heads=page.content_headings
    if len(heads)!=1 or not re.search(r'/(?:karriere|careers?|jobs?|stillinger)/[^/]+',urlsplit(page.url).path,re.I):return []
    title=heads[0]
    if re.search(r'åpen\s+søknad|spontan|open\s+application|talent\s+pool',title,re.I):return []
    body=' '.join(page.main_parts or page.body_parts)
    if not (re.search(r'\bledig\s+stilling\b',body,re.I) and re.search(r'\bvi\s+(?:søker|ser etter)\b',body,re.I)):return []
    if re.search(r'fristen er utløpt|stillingen er besatt|stillingen er avsluttet|position (?:is )?(?:filled|closed)',page.text,re.I):return []
    for ats,ats_response in hiring_pages:
        if ats_response.get('delegated_from_url')!=response['url'] or ats_response.get('requested_url',ats_response['url']) not in application_links(page):continue
        if re.search(r'fristen er utløpt|stillingen er besatt|stillingen er avsluttet|position (?:is )?(?:filled|closed)|no longer accepting applications',ats.text,re.I):continue
        ats_title=ats.title.strip()
        if not normalized(ats_title).endswith(normalized(title)):continue
        # Parse a labelled deadline only from the readable ATS text, not comments.
        match=re.search(r'Application due\s+(\d{2})[./](\d{2})[./](\d{4})(?!\d)',ats.text,re.I)
        if not match:continue
        try:
            deadline=dt.date(int(match[3]),int(match[2]),int(match[1]))
            retrieved=dt.date.fromisoformat(ats_response['retrieved_at'][:10])
        except ValueError:continue
        if deadline<retrieved:continue
        return [{'@type':'JobPosting','title':title,'datePosted':None,
            'hiringOrganization':{'name':data.get('navn','')},'validThrough':deadline.isoformat(),
            '_literal_first_party':True,'_ats_response':ats_response,
            '_employer_basis':'explicit legal operator of first-party recruiting page; ATS employer not independently displayed',
            '_deadline_basis':'Application due on explicitly linked public ATS job description'}]
    return []


def delegated_hiring_pages(content_pages, fetcher, page_type):
    seeds=[];seen={rsp['url'] for _,rsp in content_pages};out=[]
    for page,rsp in content_pages:
        for link in page.links:
            u=link.get('url','');text=link.get('text','')
            public_application=u in application_links(page)
            try:
                p=urlsplit(u);port=p.port
            except ValueError:continue
            if p.scheme not in ('http','https') or not p.hostname or p.username or p.password:continue
            if port not in (None,80,443) or link.get('third_party_context'):continue
            if re.search(r'login|sign[-_]?in|profile|apply|application',p.path,re.I) and not public_application:continue
            if not public_application and not re.search(r'\b(?:careers?|karriere|jobbe?\s+(?:hos|i)|ledige\s+stillinger|vacancies|jobs?)\b',text,re.I):continue
            if p.hostname==urlsplit(rsp['url']).hostname:continue
            u=urlunsplit((p.scheme,p.netloc,p.path,p.query,''))
            if not any(x[0]==u for x in seeds):seeds.append((u,rsp['url']))
    # Three public career endpoints total, within the shared company request cap.
    while seeds and len(out)<3 and fetcher.requests<fetcher.limit:
        u,parent=seeds.pop(0)
        if u in seen:continue
        seen.add(u);rsp=fetcher.get(u,site=True,raw=True)
        if rsp['status']!='available':continue
        pg=page_type(rsp.get('text',''),rsp['url'])
        if re.search(r'\b(?:sign in|logg inn|access denied|captcha)\b',pg.title,re.I):continue
        rsp={**rsp,'identity_verified':False,'delegated_from_verified_careers':True,'delegated_from_url':parent}
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
                seeds.append((v,rsp['url']))
    return out
