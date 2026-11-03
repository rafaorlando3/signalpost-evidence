"""Read public Nuu Angular transfer-state; never execute scripts or apply.

A card ID is only a lead. The observed client route and same-host detail are
checked independently, with a dedicated linked portal and exact full legal stem.
"""
import json
import re
from html.parser import HTMLParser
from urllib.parse import urljoin,urlsplit


def state_records(page):
    class State(HTMLParser):
        def __init__(self):super().__init__();self.active=False;self.parts=[];self.scripts=[];self.sources=[]
        def handle_starttag(self,tag,attrs):
            if tag!='script':return
            a=dict(attrs);self.active=a.get('type')=='application/json';self.parts=[]
            if a.get('src'):self.sources.append(urljoin(page.url,a['src']))
        def handle_data(self,text):
            if self.active:self.parts.append(text)
        def handle_endtag(self,tag):
            if tag=='script' and self.active:self.scripts.append(''.join(self.parts));self.active=False
    p=State();p.feed(page.raw_html);records=[]
    for raw in p.scripts[:8]:
        if len(raw)>1_500_000:continue
        try:d=json.loads(raw)
        except (ValueError,RecursionError):continue
        if not isinstance(d,dict):continue
        for value in d.values():
            if not isinstance(value,dict) or value.get('s')!=200 or not isinstance(value.get('u'),str):continue
            u=urlsplit(value['u'])
            if u.scheme=='https' and u.hostname=='api.nuu.no' and not u.username and not u.password and u.port in (None,443):records.append(value)
    return records,p.sources


def portal_company(page):
    records,_=state_records(page);path='/companies/domain/'+(urlsplit(page.url).hostname or '')+'/'
    candidates=[r.get('b') for r in records if urlsplit(r['u']).path==path and isinstance(r.get('b'),dict)]
    if len(candidates)!=1:return None
    c=candidates[0]
    if type(c.get('id')) is not int or c.get('sub_companies') or c.get('group_settings'):return None
    return c


def specific_title(value):
    return isinstance(value,str) and 5<=len(value)<=250 and not re.search(r'åpen\s+søknad|open application|spontan|talent\s+(?:pool|network)',value,re.I)


def card_leads(page):
    company=portal_company(page)
    if not company:return []
    records,sources=state_records(page);cards=[];expected='/companies/'+str(company['id'])+'/job-folders/'
    for r in records:
        if urlsplit(r['u']).path!=expected or not isinstance(r.get('b'),list):continue
        for card in r['b'][:100]:
            if (isinstance(card,dict) and card.get('company')==company['id'] and type(card.get('id')) is int
                    and specific_title(card.get('title')) and card['title'] in page.text):cards.append({'id':card['id'],'title':card['title']})
    scripts=[u for u in sources if urlsplit(u).hostname==urlsplit(page.url).hostname and re.fullmatch(r'/(?:main-[A-Za-z0-9_-]+\.js)',urlsplit(u).path)]
    return [{'cards':cards[:2],'script_url':scripts[0]}] if cards and len(scripts)==1 else []


def route_supported(text):
    return isinstance(text,str) and len(text)<=400_000 and bool(re.search(r'path\s*:\s*[\"\']stilling/:jobId[\"\']',text))


def accepted_item(page,response,data,parent_page,index_page,script_response):
    from legal_name_identity import fold
    from public_recruiting import _current_date
    from hiring_discovery import external_career_leads
    host=urlsplit(page.url).hostname;root=urlsplit(parent_page.url).hostname or ''
    if not host or not host.endswith('.'+root.removeprefix('www.')):return None
    if response.get('status')!='available' or not route_supported(script_response.get('text')):return None
    if not any(urlsplit(u).hostname==host for u in external_career_leads(parent_page)):return None
    company=portal_company(index_page);detail_company=portal_company(page)
    if not company or not detail_company or company['id']!=detail_company['id']:return None
    full=fold(data.get('navn',''));stem=re.sub(r' (?:as|asa)$','',full)
    if not stem or stem==full or fold(company.get('name',''))!=stem:return None
    m=re.fullmatch(r'/stilling/(\d+)/?',urlsplit(page.url).path)
    if not m or urlsplit(index_page.url).hostname!=host:return None
    leads=card_leads(index_page)
    if not leads or script_response.get('requested_url',script_response.get('url'))!=leads[0]['script_url']:return None
    if not any(str(c['id'])==m[1] for c in leads[0]['cards']):return None
    records,_=state_records(page)
    jobs=[r.get('b') for r in records if urlsplit(r['u']).path=='/jobs/'+m[1]+'/' and isinstance(r.get('b'),dict)]
    if len(jobs)!=1:return None
    job=jobs[0];employer=job.get('company');title=job.get('title');expiry=job.get('expiration_date')
    today=_current_date(response.get('retrieved_at','')[:10]);until=_current_date(expiry)
    if (job.get('id')!=int(m[1]) or job.get('is_published') is not True or job.get('external') is not True
            or job.get('internal') is not False or not isinstance(employer,dict)
            or employer.get('id')!=company['id'] or fold(employer.get('name',''))!=stem
            or not specific_title(title) or title not in page.text or not today or not until or until<today):return None
    translations=job.get('translations');body=(translations or {}).get('no',{}) if isinstance(translations,dict) else {}
    if not isinstance(body,dict) or body.get('title')!=title or not isinstance(body.get('description'),str) or len(body['description'])<80:return None
    proof={'method':'linked_dedicated_nuu_company_and_exact_legal_stem','portal_company_id':company['id'],
        'organisation_number':data.get('organisasjonsnummer'),'registered_name':data.get('navn'),
        'employer_as_published':employer['name'],'company_link_source':parent_page.url,
        'portal_index_source':index_page.url,'route_source':script_response['url'],'job_id':job['id'],
        'limitation':'ATS has no organisation number; bound by explicit company career link, dedicated subdomain, exact full legal stem and same single-company identifier; AS/ASA omitted by ATS'}
    return {'title':title,'date':None,'url':page.url,'hiring_organisation':data['navn'],
        'employer_as_published':employer['name'],'employer_binding':proof,'valid_through':expiry,
        'status':'listed_vacancy; published flag and literal deadline checked; application acceptance not tested',
        'publication_date_state':'not_stated','deadline_basis':{'source':'Nuu current-page transfer-state','field':'expiration_date'},
        'discovery':'linked_dedicated_nuu_portal'}
