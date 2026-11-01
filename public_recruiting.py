"""Bounded, anonymous public job-board discovery and exact-entity evidence.

Search results nominate ad URLs only. A posting needs the target's published
corporate number (or a currently registered child), a matching legal employer,
a literal publication date and a current usable detail response. No API key,
login, application endpoint, snippets-as-facts or guessed ad identifiers.
"""
import datetime as dt
import json
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit,urlunsplit,urlencode

FINN={'finn.no','www.finn.no'}
NAV={'arbeidsplassen.nav.no'}


def job_key(item):
    """A publisher's explicit source link can identify a syndicated copy."""
    for raw in [item.get('source_posting_url'),item.get('url')]:
        if not isinstance(raw,str):continue
        try:p=urlsplit(raw)
        except ValueError:continue
        if p.hostname in FINN:
            m=re.fullmatch(r'/(?:job/ad/)?([0-9]+)/?',p.path)
            if m:return 'finn:'+m[1]
    return str(item.get('url',''))


def detail_url(url,provider):
    try:
        p=urlsplit(url)
        if p.scheme not in {'https','http'} or p.username or p.password or p.port not in (None,80,443):return False
        if provider=='finn':return p.hostname in FINN and bool(re.fullmatch(r'/job/ad/[0-9]+/?',p.path))
        return p.hostname in NAV and bool(re.fullmatch(r'/stillinger/stilling/[0-9a-fA-F-]{36}/?',p.path))
    except ValueError:return False


def _current_date(value):
    if not isinstance(value,str):return None
    try:return dt.datetime.fromisoformat(value.replace('Z','+00:00')).date() if 'T' in value else dt.date.fromisoformat(value)
    except ValueError:return None


def _binding(number,name,data,units):
    from agent import normalized,valid_org
    from attribution import legal_stem
    target=str(data.get('organisasjonsnummer',''))
    if not isinstance(number,str) or not valid_org(number) or not isinstance(name,str):return None
    actual=legal_stem(name);expected=legal_stem(data.get('navn',''))
    unit=next((u for u in units if u.get('overordnetEnhet')==target and u.get('organisasjonsnummer')==number),None)
    if number!=target and unit is None:return None
    if actual!=expected and (unit is None or normalized(name)!=normalized(unit.get('navn',''))):return None
    return {'method':'published_corporate_number' if number==target else 'published_registered_child_number',
            'published_organisation_number':number,'target_organisation_number':target,
            'employer_as_published':name,'registered_parent_name':data.get('navn'),
            **({'registered_child_name':unit.get('navn')} if unit else {})}


def _homepage(value):
    from registry_discovery import web_url,host_key
    from search import DIRECTORIES
    url=web_url(value)
    if not url:return None
    p=urlsplit(url);host=host_key(url)
    if host in DIRECTORIES or host in NAV or any(host.endswith('.'+x) for x in ['teamtailor.com','ashbyhq.com']):return None
    # Homepage field is an untrusted identity lead, never website ownership.
    return urlunsplit((p.scheme,p.netloc,'/','',''))


def finn_postings(page,response,data,units):
    from agent import objects,schema_types
    from hiring_discovery import closed_hiring_page
    if not detail_url(response['url'],'finn') or closed_hiring_page(page):return []
    marker=page.text.find('Annonseinformasjon')
    info=page.text[marker:marker+1400] if marker>=0 else ''
    info=info.split('Rapporter annonse',1)[0]
    numbers={re.sub(r'\D','',v) for v in re.findall(r'\bOrg\.?\s*nr\.?\s*[:\-]?\s*(\d{3}[.\s]?\d{3}[.\s]?\d{3})(?!\d)',info,re.I)}
    nodes=[o for o in objects(page.ld) if 'JobPosting' in schema_types(o)]
    out=[];today=_current_date(response.get('retrieved_at','')[:10])
    for obj in nodes:
        employer=obj.get('hiringOrganization') or {};title=obj.get('title');date=obj.get('datePosted');through=obj.get('validThrough')
        if not isinstance(employer,dict) or not isinstance(title,str) or not 3<=len(title)<=250:continue
        if title.casefold() not in page.text.casefold():continue
        if re.search(r'åpen\s+søknad|open application|talent (?:pool|network)|spontan',title,re.I):continue
        source_url=obj.get('url')
        if source_url:
            if not isinstance(source_url,str) or job_key({'url':source_url})!=job_key({'url':response['url']}):continue
        elif len(nodes)!=1:continue
        published=_current_date(date)
        if not published or not today or published>today:continue
        if through is not None:
            expiry=_current_date(through)
            if not expiry or expiry<today:continue
        # The visible ad-information corporate label is scoped to this ad.
        # Other companies in related ads, footers or scripts cannot bind it.
        bindings=[_binding(n,employer.get('name'),data,units) for n in numbers]
        if len(numbers)!=1 or len([b for b in bindings if b])!=1:continue
        binding=next(b for b in bindings if b)
        item={'title':title,'date':date,'url':response['url'],'hiring_organisation':data['navn'],
              'employer_as_published':employer['name'],'employer_binding':binding,
              'valid_through':through,'status':'published_posting; application availability not independently checked',
              'discovery':'public_board_search','publication_date_basis':{'source':'JSON-LD JobPosting','field':'datePosted'}}
        homepage=_homepage(employer.get('url'))
        out.append({'item':item,'response':{**response,'public_job_board':True},'homepage':homepage})
    return out


def _nav_objects(raw):
    """Decode inert Next Flight JSON strings, never JavaScript or HTML code."""
    if len(raw)>2_000_000:return []
    class Scripts(HTMLParser):
        def __init__(self):super().__init__();self.active=False;self.parts=[];self.scripts=[]
        def handle_starttag(self,tag,attrs):
            if tag=='script':self.active=True;self.parts=[]
        def handle_data(self,text):
            if self.active:self.parts.append(text)
        def handle_endtag(self,tag):
            if tag=='script' and self.active:
                if len(self.scripts)<100:self.scripts.append(''.join(self.parts))
                self.active=False
    parser=Scripts();parser.feed(raw);decoder=json.JSONDecoder();out=[]
    for script in parser.scripts:
        m=re.fullmatch(r'\s*self\.__next_f\.push\((.*)\);?\s*',script,re.S)
        if not m:continue
        try:parts=json.loads(m[1])
        except (ValueError,RecursionError):continue
        if not isinstance(parts,list):continue
        for text in parts:
            if not isinstance(text,str) or len(text)>1_000_000:continue
            for index,found in enumerate(re.finditer(r'\{\s*"(?:id|uuid)"\s*:',text)):
                if index>=128:break
                try:obj,_=decoder.raw_decode(text,found.start())
                except (ValueError,RecursionError):continue
                if isinstance(obj,dict) and isinstance(obj.get('employer'),dict) and obj['employer'].get('orgnr'):out.append(obj)
    return out


def nav_postings(page,response,data,units):
    if not detail_url(response['url'],'nav'):return []
    identifier=urlsplit(response['url']).path.rstrip('/').split('/')[-1].casefold();out=[]
    today=_current_date(response.get('retrieved_at','')[:10])
    for obj in _nav_objects(page.raw_html):
        if str(obj.get('id','')).casefold()!=identifier or obj.get('status')!='ACTIVE':continue
        employer=obj['employer'];binding=_binding(employer.get('orgnr'),employer.get('name'),data,units)
        application=obj.get('application')
        if application is not None and not isinstance(application,dict):continue
        title=obj.get('title');date=obj.get('published');through=(application or {}).get('applicationDueDate')
        if not binding or not isinstance(title,str) or not 3<=len(title)<=250 or title.casefold() not in page.text.casefold():continue
        if re.search(r'åpen\s+søknad|open application|talent (?:pool|network)|spontan',title,re.I):continue
        published=_current_date(date)
        if not published or not today or published>today:continue
        if through is not None:
            expiry=_current_date(through)
            if not expiry or expiry<today:continue
        expires=_current_date(obj.get('expires'))
        if expires and expires<today:continue
        item={'title':title,'date':date,'url':response['url'],'hiring_organisation':data['navn'],
              'employer_as_published':employer['name'],'employer_binding':binding,'valid_through':through,
              'status':'published_posting; application availability not independently checked','discovery':'public_board_search',
              'publication_date_basis':{'source':'NAV current-page Next Flight job object','field':'published'}}
        source=obj.get('sourceUrl')
        if isinstance(source,str) and (detail_url(source,'finn') or (urlsplit(source).hostname in FINN and re.fullmatch(r'/[0-9]+/?',urlsplit(source).path))):item['source_posting_url']=source
        out.append({'item':item,'response':{**response,'public_job_board':True},'homepage':_homepage(employer.get('homepage'))})
    return out


def parse_postings(page,response,data,units):
    if response.get('status')!='available' or response.get('status_code')!=200:return []
    try:host=urlsplit(response.get('url','')).hostname
    except ValueError:return []
    return finn_postings(page,response,data,units) if host in FINN else nav_postings(page,response,data,units)


def search_employers(page,provider):
    """Read visible search-card employer labels for ordering, never facts."""
    class Cards(HTMLParser):
        def __init__(self):
            super().__init__();self.active=False;self.depth=0;self.skip=0;self.values=[];self.out={}
        def handle_starttag(self,tag,attrs):
            attrs=dict(attrs)
            if tag=='article':
                if not self.active:self.active=True;self.urls=[];self.paragraphs=[];self.strong=[]
                self.depth+=1
            if not self.active:return
            if tag in {'script','style'}:self.skip+=1
            if tag in {'p','strong'}:self.values.append([tag,[]])
            if tag=='a':
                from urllib.parse import urljoin
                try:url=urljoin(page.url,attrs.get('href',''))
                except ValueError:return
                if detail_url(url,provider) and url not in self.urls:self.urls.append(url)
        def handle_data(self,text):
            if self.active and not self.skip:
                for _,parts in self.values:parts.append(text)
        def handle_endtag(self,tag):
            if not self.active:return
            if tag in {'script','style'}:self.skip=max(0,self.skip-1)
            if self.values and self.values[-1][0]==tag:
                _,parts=self.values.pop();value=' '.join(''.join(parts).split())
                (self.paragraphs if tag=='p' else self.strong).append(value)
            if tag=='article':
                self.depth-=1
                if self.depth:return
                labels=(self.strong if provider=='finn' else [self.paragraphs[i+1] for i,v in enumerate(self.paragraphs[:-1]) if v.casefold() in {'arbeidsgiver','arbeidsgivar','employer'}])
                labels=list(dict.fromkeys(v for v in labels if v))
                if len(self.urls)==1 and len(labels)==1:self.out[self.urls[0]]=labels[0]
                self.active=False;self.values=[]
    parser=Cards();parser.feed(page.raw_html);return parser.out


def ranked_search_links(page,provider,data,units):
    from attribution import legal_stem
    names={legal_stem(data.get('navn',''))}
    names.update(legal_stem(u.get('navn','')) for u in units if u.get('overordnetEnhet')==data.get('organisasjonsnummer'))
    labels=search_employers(page,provider);links=[]
    for link in page.links:
        u=link['url']
        if detail_url(u,provider) and not link.get('third_party_context') and u not in links:links.append(u)
    preferred=[u for u in links if labels.get(u) and legal_stem(labels[u]) in names]
    return preferred+[u for u in links if u not in preferred],len(preferred)


def discover(data,units,fetcher,*,max_details=2):
    """One query per board, at most two details total; same20-request budget."""
    from agent import Page
    out={'records':[],'website_leads':[],'checks':[],'sources':[],'detail_attempts':0}
    name=data.get('navn');target=data.get('organisasjonsnummer')
    if not isinstance(name,str) or not target:return out
    queries=[('finn','https://www.finn.no/job/search?'+urlencode({'q':name})),
             ('nav','https://arbeidsplassen.nav.no/stillinger?'+urlencode({'q':name}))]
    seen=set();deferred=[]
    def inspect(links):
        for u in links:
            if out['detail_attempts']>=max_details or fetcher.requests>=fetcher.limit:break
            if u in seen:continue
            seen.add(u);out['detail_attempts']+=1;detail=fetcher.get(u,site=True,raw=True);out['sources'].append(detail)
            if detail['status']!='available':continue
            records=parse_postings(Page(detail.get('text',''),detail['url']),detail,data,units)
            for record in records:
                if any(job_key(r['item'])==job_key(record['item']) for r in out['records']):continue
                out['records'].append(record)
                if record['homepage'] and record['homepage'] not in out['website_leads']:out['website_leads'].append(record['homepage'])
    for provider,url in queries:
        if fetcher.requests>=fetcher.limit-1:break
        rsp=fetcher.get(url,site=True,raw=True)
        out['sources'].append(rsp);check={'provider':provider,'url':url,'state':rsp['status'],'detail_candidates':0};out['checks'].append(check)
        if rsp['status']!='available':continue
        pg=Page(rsp.get('text',''),rsp['url']);links,preferred=ranked_search_links(pg,provider,data,units)
        check['detail_candidates']=len(links)
        check['matching_employer_labels']=preferred
        # Ambiguous broad results do not consume both detail slots before the
        # other board can supply a clearly labelled employer. They remain a
        # fallback, and every chosen detail still needs its corporate ID.
        inspect(links[:preferred]);deferred.extend(links[preferred:])
        if out['records'] or out['detail_attempts']>=max_details:break
    if not out['records']:inspect(deferred)
    return out
