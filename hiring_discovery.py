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


def direct_recruiting_post(page,response,data):
    """Specific first-party role with a named employer introduction and deadline."""
    from attribution import normal,legal_stem
    from publication import publication_block
    if not response.get('identity_verified') or response.get('delegated_from_verified_careers'):return []
    heads=page.semantic_headings or page.main_headings or page.content_headings
    if not page.post_container or len(heads)!=1:return []
    title=heads[0]
    if not re.match(r'^(?:vi søker|we are hiring|we seek)\b',title,re.I):return []
    body=re.sub(r'\s+',' ',' '.join(page.article_parts)).strip()
    if re.search(r'åpen\s+søknad|spontan|open application|fristen er utløpt|stillingen er besatt|position (?:is )?(?:filled|closed)',body,re.I):return []
    intro=normal(body)
    heading=normal(title)
    if intro.startswith(heading):intro=intro[len(heading):].strip()
    stem=legal_stem(data.get('navn',''))
    match_intro=re.match(r'^'+re.escape(stem)+r'(?: (?P<form>as|asa|sa))? (?:utvikler|er|søker|tilbyr|driver|is|develops|provides)\b',intro)
    if len(stem)<5 or not match_intro:return []
    if match_intro['form'] and match_intro['form']!=normal(data.get('navn','')).split()[-1]:return []
    match=re.search(r'Søknadsfrist\s*:\s*(\d{1,2})[./](\d{1,2})[./](\d{4})(?!\d)',body,re.I)
    if not match:return []
    try:
        deadline=dt.date(int(match[3]),int(match[2]),int(match[1]))
        if deadline<dt.date.fromisoformat(response['retrieved_at'][:10]):return []
    except ValueError:return []
    host=(urlsplit(page.url).hostname or '').removeprefix('www.')
    email=None
    for link in page.links:
        if link.get('third_party_context'):continue
        raw=link.get('url','')
        if not raw.lower().startswith('mailto:'):continue
        address=raw[7:]
        if re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"+re.escape(host),address,re.I):email=address;break
    if not email:return []
    published=publication_block(page)
    if not published:return []
    return [{'@type':'JobPosting','title':title,'datePosted':published['date'],
        'hiringOrganization':{'name':data.get('navn','')},'validThrough':deadline.isoformat(),
        '_literal_first_party':True,'_application_url':page.url,'_application_contact':email,
        '_publication_date_basis':published,
        '_employer_basis':'target legal-name stem in the first-party employer introduction; verified site identity and same-domain application email',
        '_deadline_basis':'explicit Søknadsfrist in the recruiting post'}]


def continuous_first_party_vacancy(page,response,data):
    """Specific first-party recruiting notice; dates can remain unknown.

    This reports a currently published recruitment invitation, not verified
    acceptance of applications or a guessed publication/deadline date.
    """
    from agent import website_identity,normalized
    from attribution import legal_stem
    if not response.get('identity_verified') or response.get('delegated_from_verified_careers'):return []
    if website_identity(str(data.get('organisasjonsnummer','')),page,data)!='exact':return []
    heads=page.semantic_headings or page.main_headings or page.content_headings
    if len(heads)!=1 or not urlsplit(page.url).path.rstrip('/'):return []
    title=heads[0].strip();body=re.sub(r'\s+',' ',' '.join(page.article_parts)).strip()
    page_title=re.split(r'\s+[|–—]\s*|\s+-\s+',page.title)[0].strip()
    if re.match(r'^(?:stilling ledig|ledig stilling)\s+\S',page_title,re.I):title=page_title
    if not 3<=len(title)<=180 or re.fullmatch(r'(?:ledige stillinger|karriere|careers?|jobs?|vacancies|jobb hos oss)',title,re.I):return []
    if re.search(r'åpen\s+søknad|spontan|open application|talent pool|fristen er utløpt|stillingen er (?:besatt|avsluttet)|position (?:is )?(?:filled|closed)|på vegne av|for vår kunde|on behalf of|our client',body,re.I):return []
    stem=legal_stem(data.get('navn',''))
    if len(stem)<5 or not re.search(r'(?<!\w)'+re.escape(stem)+r'(?!\w)',normalized(body)):return []
    named_role=re.match(r'^(?:stilling ledig|ledig stilling)\s+\S',title,re.I)
    if not named_role and not re.search(r'\b(?:vi (?:søker|ser etter)|er du vår nye|we are (?:hiring|looking for))\b',body,re.I):return []
    rolling=bool(re.search(r'\b(?:søknad(?:er|ene) vurderes fortløpende|applications (?:are )?reviewed (?:on a )?rolling basis)\b',body,re.I))
    sections=re.findall(r'\b(?:ønskede kvalifikasjoner|hvem er du|hva du vil jobbe med|vi tilbyr)\b',body,re.I)
    if not rolling and not (named_role and len(set(x.casefold() for x in sections))>=2):return []
    # A partly stated or expired deadline must not become "unknown but open".
    deadline=None;deadline_text=None
    if re.search(r'søknadsfrist|application deadline',body,re.I):
        m=re.search(r'(?:søknadsfrist|application deadline)\s*:?\s*(\d{1,2})[./](\d{1,2})[./](\d{4})(?!\d)',body,re.I)
        rolling_match=re.search(r'(?:søknadsfrist|application deadline)\s*:?\s*(snarest|as soon as possible)(?:[.!]|$|\s)',body,re.I)
        rolling_deadline=bool(rolling and rolling_match)
        if rolling_deadline:deadline_text=rolling_match[1]
        if not m and not rolling_deadline:return []
        try:
            deadline=dt.date(int(m[3]),int(m[2]),int(m[1])) if m else None
            if deadline and deadline<dt.date.fromisoformat(response['retrieved_at'][:10]):return []
        except ValueError:return []
    host=(urlsplit(page.url).hostname or '').removeprefix('www.');contact=None;application=None
    for link in page.links:
        if link.get('third_party_context'):continue
        u=link.get('url','');label=link.get('text','')
        if u.startswith('mailto:'):
            address=urlsplit(u).path
            offset=body.find(address)
            nearby=body[max(0,offset-220):offset] if offset>=0 else ''
            invitation=re.search(r'(?:søknad|application|\bCV\b).{0,160}?(?:send(?:es)?\s+(?:til|to)|sendes|e-?post|email|e-mail)\b|send.{0,100}?(?:søknad|application).{0,60}?\b(?:til|to)\b',nearby,re.I)
            if not re.search(r'søknad|apply|application',label,re.I) and not invitation:continue
            if re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"+re.escape(host),address,re.I):contact=address;application=page.url;break
        try:p=urlsplit(u);port=p.port
        except ValueError:continue
        if (p.scheme in {'http','https'} and p.hostname and not p.username and not p.password and port in (None,80,443)
                and re.fullmatch(r'/(?:[A-Za-z0-9_-]+/){0,2}sok-stilling/[A-Za-z0-9_-]+/?',p.path)
                and re.search(r'\b(?:søk(?: på)? stilling(?:en)?|søk her|send inn søknad|apply (?:now|for))\b',label,re.I)):
            application=u;break
    if not application:return []
    return [{'@type':'JobPosting','title':title,'datePosted':None,'hiringOrganization':{'name':data['navn']},
        'validThrough':deadline.isoformat() if deadline else None,'_literal_first_party':True,
        **({'_deadline_text':deadline_text} if deadline_text else {}),
        '_application_url':application,**({'_application_contact':contact} if contact else {}),
        '_employer_basis':'exact corporate ID on verified first-party page plus named employer in recruiting content',
        '_deadline_basis':'explicit first-party deadline' if deadline else 'rolling ASAP invitation; calendar deadline not stated' if deadline_text else 'not stated; explicit job-specific application invitation on first-party page'}]


def literal_hiring_candidates(page, response, data, hiring_pages):
    """Undated named first-party vacancy + matching linked public ATS deadline.

    Do not manufacture datePosted from a deadline, modified time or retrieval.
    Employer basis is the explicit legal site operator, not a group footer or
    an employer hidden inside an HTML comment on the ATS.
    """
    from agent import normalized
    if contradicted_by_closed_ad(page,hiring_pages,data):return []
    direct=direct_recruiting_post(page,response,data)
    if direct:return direct
    continuous=continuous_first_party_vacancy(page,response,data)
    # An undated mail invitation that explicitly points to a public job ad
    # defers to that ad's checked state and structured publication evidence.
    # Do not count an unchecked/stale mirror as an additional current vacancy.
    if continuous and not continuous[0].get('validThrough') and any(not l.get('in_navigation') and linked_public_job_detail(page,l) for l in page.links):continuous=[]
    if not response.get('identity_verified') or response.get('delegated_from_verified_careers'):return []
    operator=response.get('site_operator',{})
    if operator.get('state')!='target':return continuous
    heads=page.content_headings
    if len(heads)!=1 or not re.search(r'/(?:karriere|careers?|jobs?|stillinger)/[^/]+',urlsplit(page.url).path,re.I):return continuous
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
    return continuous


def linked_public_job_detail(page,link):
    """Observed job-board detail link in a first-party recruiting context."""
    p=urlsplit(link.get('url',''))
    # Reject non-ad links before examining page content. A page can have
    # thousands of ordinary links; body parsing is once per eligible page.
    if p.hostname not in {'finn.no','www.finn.no'}:return False
    if link.get('third_party_context') or not 3<=len(link.get('text','').strip())<=180:return False
    detail=bool(re.fullmatch(r'/job/ad/[0-9]+/?',p.path)
                or (p.path=='/job/fulltime/ad.html' and re.fullmatch(r'finnkode=[0-9]+',p.query)))
    if not detail:return False
    context=getattr(page,'_linked_public_job_context',None)
    if context is None:
        path=urlsplit(page.url).path;body=' '.join(page.article_parts)
        career_context=bool(re.search(r'(?:^|[/_-])(?:careers?|karriere|jobs?|stillinger)(?:$|[/_-])',path,re.I))
        role_context=(len(page.content_headings)==1 and bool(re.search(r'søknadsfrist|application deadline',body,re.I))
                      and bool(re.search(r'arbeidsoppgaver|kvalifikasjoner|qualifications|responsibilities',body,re.I)))
        context=page._linked_public_job_context=bool(career_context or role_context)
    return context


def closed_hiring_page(page):
    return bool(re.search(r'fristen er utløpt|stillingen er (?:besatt|avsluttet)|position (?:is )?(?:filled|closed)|no longer accepting applications',page.text,re.I)
                or re.search(r'(?<!\w)Besatt(?!\w)',page.text,re.I))


def contradicted_by_closed_ad(page,hiring_pages,data):
    """A same-role, exact-employer, explicitly linked closed ad vetoes a notice.

    An expired unrelated ad, merely linked in navigation, must not veto another
    vacancy. Without fetched public evidence the application state stays unknown.
    """
    from agent import objects,normalized,schema_types
    from attribution import legal_stem
    heads=page.semantic_headings or page.main_headings or page.content_headings
    if len(heads)!=1:return False
    title=normalized(heads[0]);employer=legal_stem(data.get('navn',''))
    observed={l['url'] for l in page.links if linked_public_job_detail(page,l)}
    for board,response in hiring_pages:
        if response.get('delegated_from_url')!=page.url or not closed_hiring_page(board):continue
        if response.get('requested_url',board.url) not in observed:continue
        for obj in objects(board.ld):
            if 'JobPosting' not in schema_types(obj):continue
            hiring=obj.get('hiringOrganization') or {}
            if (isinstance(hiring,dict) and legal_stem(hiring.get('name',''))==employer
                    and normalized(obj.get('title',''))==title):return True
    return False


def delegated_hiring_pages(content_pages, fetcher, page_type):
    seeds=[];seen={rsp['url'] for _,rsp in content_pages};out=[]
    for page,rsp in content_pages:
        for link in page.links:
            u=link.get('url','');text=link.get('text','')
            public_application=u in application_links(page)
            public_job=bool(rsp.get('identity_verified') and linked_public_job_detail(page,link))
            try:
                p=urlsplit(u);port=p.port
            except ValueError:continue
            if p.scheme not in ('http','https') or not p.hostname or p.username or p.password:continue
            if port not in (None,80,443) or link.get('third_party_context'):continue
            if re.search(r'login|sign[-_]?in|profile|apply|application',p.path,re.I) and not public_application:continue
            if not public_application and not public_job and not re.search(r'\b(?:careers?|karriere|jobbe?\s+(?:hos|i)|ledige\s+stillinger|vacancies|jobs?)\b',text,re.I):continue
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
