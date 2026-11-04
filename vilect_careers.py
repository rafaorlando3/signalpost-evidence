"""Public Vilect/Done job cards; read metadata and visible labelled fields only.

The brand index and its company backlink are URL/provenance checks, not employer
proof by themselves. Exact full legal stem, verified company identity and a
current specific posting are required. No scripts or application actions run.
"""
import datetime as dt
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

HOSTS={'app.vilect.com','recruiting.done.ai'}

def position_key(url):
    try:p=urlsplit(url);port=p.port
    except (ValueError,TypeError):return None
    if p.scheme not in {'https','http'} or p.hostname not in HOSTS or p.username or p.password or port not in (None,80,443):return None
    m=re.fullmatch(r'/positions/([1-9][0-9]*)/?',p.path)
    return m[1] if m else None

def index_key(url):
    try:p=urlsplit(url);port=p.port
    except (ValueError,TypeError):return None
    if p.scheme not in {'https','http'} or p.hostname not in HOSTS or p.username or p.password or port not in (None,80,443):return None
    m=re.fullmatch(r'/brands/([1-9][0-9]*)/jobs/?',p.path)
    return m[1] if m else None

def labelled_fields(page):
    class Fields(HTMLParser):
        def __init__(self):super().__init__();self.in_p=False;self.kind=None;self.parts=[];self.values={};self.current={};self.duplicate=False
        def handle_starttag(self,tag,attrs):
            a=dict(attrs)
            if tag=='p':self.in_p=True;self.current={}
            if self.in_p and tag=='span':
                classes=set((a.get('class') or '').split())
                self.kind='label' if 'has-text-weight-bold' in classes else 'value' if 'has-word-wrap' in classes else None;self.parts=[]
        def handle_data(self,data):
            if self.in_p and self.kind:self.parts.append(data)
        def handle_endtag(self,tag):
            if tag=='span' and self.kind:self.current[self.kind]=' '.join(''.join(self.parts).split());self.kind=None
            if tag=='p' and self.in_p:
                k=self.current.get('label','').rstrip(':').casefold();v=self.current.get('value')
                if k in {'stillingstittel','arbeidsgiver','arbeidssted','søknadsfrist'} and v:
                    if k in self.values:self.duplicate=True
                    self.values[k]=v
                self.in_p=False
    p=Fields();p.feed(page.raw_html)
    return {} if p.duplicate else p.values

def _date(value):
    if not isinstance(value,str):return None
    try:return dt.datetime.fromisoformat(value.replace('Z','+00:00')).date() if 'T' in value else dt.date.fromisoformat(value)
    except ValueError:return None

def verified_index(data,parent_page,index_page,identity_page):
    from agent import website_identity,group_description
    from attribution import same_public_host
    from legal_name_identity import fold
    from hiring_discovery import external_career_leads
    target=str(data.get('organisasjonsnummer',''));brand_id=index_key(index_page.url)
    if not brand_id or website_identity(target,identity_page,data)!='exact':return False
    if not same_public_host(parent_page.url,identity_page.url):return False
    if not any(index_key(u)==brand_id for u in external_career_leads(parent_page)):return False
    if not any(not l.get('third_party_context') and same_public_host(l.get('url',''),parent_page.url)
               and urlsplit(l['url']).path in ('','/') for l in index_page.links):return False
    full=fold(data.get('navn',''));stem=re.sub(r' (?:as|asa)$','',full)
    if full==stem or len(stem)<5:return False
    headings=index_page.content_headings;brand=fold(headings[0]) if len(headings)==1 else ''
    if not brand.startswith('ledige stillinger ') or brand[len('ledige stillinger '):] not in {full,stem}:return False
    return not any(group_description(x) for x in [parent_page.description,*parent_page.paragraphs])


def accepted_item(page,response,data,parent_page,index_page,identity_page):
    from legal_name_identity import fold
    from hiring_discovery import closed_hiring_page
    target=str(data.get('organisasjonsnummer',''));key=position_key(page.url);brand_id=index_key(index_page.url)
    if response.get('status')!='available' or not key or not verified_index(data,parent_page,index_page,identity_page):return None
    if not any(not l.get('third_party_context') and position_key(l.get('url'))==key for l in index_page.links):return None
    fields=labelled_fields(page);title=fields.get('stillingstittel');employer=fields.get('arbeidsgiver');location=fields.get('arbeidssted');deadline=fields.get('søknadsfrist')
    if not title or not 3<=len(title)<=250 or not employer or not location or not deadline:return None
    full=fold(data.get('navn',''));stem=re.sub(r' (?:as|asa)$','',full)
    if full==stem or len(stem)<5 or fold(employer) not in {full,stem}:return None
    if re.search(r'åpen\s+søknad|spontan|open application|talent\s+(?:pool|network)',title,re.I):return None
    if closed_hiring_page(page) or re.search(r'utløpt|lukket|besatt|avsluttet|expired|closed',deadline,re.I):return None
    if re.search(r'Beklager, denne stillingen er lukket|ikke lenger mulig å søke',page.text,re.I):return None
    if not any(urlsplit(l.get('url','')).fragment=='apply-form' and position_key(l.get('url'))==key
               and re.fullmatch(r'\s*Søk på denne stillingen\s*',l.get('text',''),re.I) for l in page.links):return None
    canonical=page.meta.get('og:url')
    if canonical and position_key(canonical)!=key:return None
    if page.meta.get('og:type')!='article' or page.meta.get('article:section')!='Ledige stillinger':return None
    published=page.meta.get('article:published_time');expires=page.meta.get('article:expiration_time')
    today=_date(response.get('retrieved_at','')[:10]);pub=_date(published);end=_date(expires)
    if not today or not pub or pub>today or not end or end<today:return None
    valid_through=None
    if re.fullmatch(r'Snarest|Fortløpende',deadline,re.I):pass
    else:
        match=re.fullmatch(r'(\d{1,2})\.(\d{1,2})\.(\d{4})',deadline)
        if not match:return None
        try:d=dt.date(int(match[3]),int(match[2]),int(match[1]))
        except ValueError:return None
        if d<today:return None
        valid_through=d.isoformat()
    proof={'method':'verified_company_link_single_brand_index_and_literal_employer','target_organisation_number':target,
        'registered_name':data['navn'],'employer_as_published':employer,'company_link_source':parent_page.url,
        'company_identity_source':identity_page.url,'portal_index_source':index_page.url,'brand_id':brand_id,
        'limitation':'ATS employer omits AS/ASA when applicable; full legal stem is preserved and bound through exact corporate identity on the company site and a reciprocally linked single-brand current index. Corporate number is not asserted as printed by the ATS.'}
    return {'title':title,'date':published,'url':page.url,'hiring_organisation':data['navn'],
        'employer_as_published':employer,'employer_binding':proof,'job_location':location,
        'valid_through':valid_through,'deadline_text':deadline,'listing_expires_at':expires,
        'status':'published_posting; listed on company index with application link; application availability not independently checked',
        'discovery':'linked_vilect_company_portal','verification_scope':'company_declared',
        'publication_date_basis':{'source':'Vilect job-detail OpenGraph','field':'article:published_time'},
        'listing_expiry_basis':{'source':'Vilect job-detail OpenGraph','field':'article:expiration_time','not_an_application_deadline':True}}
