"""Late, bounded detail visits from already nominated public recruitment indexes.

No URL guessing, scripts or application actions. This runs after all established
modules, so it cannot spend their remaining requests. Full legal employer and
publication/date checks remain mandatory; a link is only a lead.
"""
import datetime as dt
import re
from urllib.parse import urljoin,urlsplit,urlunsplit


def canonical(url):
    try:
        p=urlsplit(url);port=p.port
    except (ValueError,TypeError):return None
    if p.scheme not in {'http','https'} or not p.hostname or p.username or p.password or port not in (None,80,443):return None
    return urlunsplit((p.scheme,p.netloc,p.path.rstrip('/') or '/',p.query,''))


def posting_key(item):
    from public_recruiting import job_key
    key=job_key(item)
    return canonical(key) or key


def detail_links(index):
    found=[]
    for link in index.links:
        u=canonical(link.get('url'));p=urlsplit(u or '')
        if (u and p.hostname==urlsplit(index.url).hostname and not link.get('third_party_context')
            and re.search(r'/(?:jobs?|positions?|vacanc(?:y|ies)|stillinger)/[^/?]+/?$',p.path,re.I)
            and not re.search(r'/(?:login|apply|application|profile|connect)(?:/|$)',p.path,re.I)
            and not re.search(r'åpen\s+søknad|(?:open|general|unsolicited) application|spontan',link.get('text',''),re.I)
            and u not in found):found.append(u)
    return found


def trusted_index(data,parent,index,identity,response):
    from agent import website_identity,group_description
    from attribution import same_public_host
    from hiring_discovery import external_career_leads
    if response.get('status')!='available' or website_identity(str(data.get('organisasjonsnummer','')),identity,data)!='exact':return False
    if not same_public_host(parent.url,identity.url):return False
    nominated={canonical(u) for u in external_career_leads(parent)}
    if not nominated.intersection({canonical(index.url),canonical(response.get('requested_url'))}):return False
    return not any(group_description(x) for x in [parent.description,*parent.paragraphs])


def schema_item(page,response,data,parent,index,identity,index_response):
    from agent import objects,schema_types,pick
    from legal_name_identity import fold
    from hiring_discovery import closed_hiring_page
    if response.get('status')!='available' or not trusted_index(data,parent,index,identity,index_response):return None
    if canonical(page.url) not in detail_links(index) or closed_hiring_page(page):return None
    nodes=[o for o in objects(page.ld) if 'JobPosting' in schema_types(o)]
    accepted=[]
    for node in nodes:
        title=node.get('title');employer=pick(node,'hiringOrganization','name');date=node.get('datePosted');expiry=node.get('validThrough')
        if not isinstance(title,str) or not 3<=len(title)<=250 or fold(title) not in fold(page.text):continue
        if re.search(r'åpen\s+søknad|(?:open|general|unsolicited) application|spontan|talent\s+(?:pool|network)',title,re.I):continue
        if not isinstance(employer,str) or fold(employer)!=fold(data.get('navn','')):continue
        # An explicitly contradictory employer identifier overrides a matching name.
        organisation=node.get('hiringOrganization') or {}
        ids=[organisation.get('identifier'),organisation.get('vatID'),organisation.get('taxID')]
        bad=False
        for value in ids:
            if isinstance(value,dict):value=value.get('value')
            if type(value) is int:value=str(value)
            if isinstance(value,str):
                number=re.sub(r'\D','',value)
                if len(number)==9 and number!=str(data.get('organisasjonsnummer','')):bad=True
        if bad:continue
        try:
            today=dt.date.fromisoformat(response['retrieved_at'][:10]);published=dt.datetime.fromisoformat(date.replace('Z','+00:00')).date() if isinstance(date,str) else None
            if not published or published>today:continue
            if expiry is not None and (not isinstance(expiry,str) or dt.datetime.fromisoformat(expiry.replace('Z','+00:00')).date()<today):continue
        except (ValueError,KeyError,TypeError):continue
        declared=node.get('url')
        if declared is not None:
            if not isinstance(declared,str) or canonical(urljoin(page.url,declared))!=canonical(page.url):continue
        elif len(nodes)!=1:continue
        accepted.append({'title':title,'date':date,'url':page.url,'hiring_organisation':employer,'valid_through':expiry,
            'status':'published_posting; application availability not independently checked','discovery':'linked_schema_company_portal',
            'verification_scope':'company_declared','publication_date_basis':{'source':'public job-detail JSON-LD','field':'JobPosting.datePosted'},
            'employer_binding':{'method':'exact_legal_employer_on_detail_linked_from_nominated_portal','target_organisation_number':str(data['organisasjonsnummer']),
                'employer_as_published':employer,'company_link_source':parent.url,'company_identity_source':identity.url,'portal_index_source':index.url}})
    return accepted[0] if len(accepted)==1 else None


def extra_postings(content_pages,known_pages,fetcher,page_type,data,*,max_details=4,request_allowance=0):
    from hiring_discovery import external_career_leads
    from agent import website_identity
    from vilect_careers import index_key,accepted_item
    exact=next(((p,r) for p,r in content_pages if website_identity(str(data.get('organisasjonsnummer','')),p,data)=='exact'),None)
    diagnostics={'phase':'after established website/news/contacts/social/public-board paths','detail_attempts':0,'max_additional_details':min(max_details,4),'checks':[],'shared_request_cap':fetcher.limit}
    if not exact:return [],diagnostics
    seen={posting_key({'url':r['url']}) for _,r in known_pages};leads=[];queued=set()
    for index,index_response in known_pages:
        if not index_response.get('delegated_from_verified_careers'):continue
        parent=next(((p,r) for p,r in content_pages if trusted_index(data,p,index,exact[0],index_response)),None)
        if not parent:continue
        for u in detail_links(index):
            key=posting_key({'url':u})
            if key not in seen and key not in queued:
                leads.append((u,parent,index,index_response));queued.add(key)
    base_limit=fetcher.limit
    allowance=min(max(int(request_allowance),0),4) if leads else 0
    fetcher.limit=base_limit+allowance
    diagnostics.update(base_request_cap=base_limit,additional_request_allowance=allowance,shared_request_cap=fetcher.limit,initial_requests=fetcher.requests)
    initial_requests=fetcher.requests
    out=[]
    for u,parent,index,index_response in leads:
        if diagnostics['detail_attempts']>=min(max_details,4) or fetcher.requests>=fetcher.limit:break
        diagnostics['detail_attempts']+=1;r=fetcher.get(u,site=True,raw=True);pg=page_type(r.get('text',''),r['url'])
        item=(accepted_item(pg,r,data,parent[0],index,exact[0]) if index_key(index.url) else schema_item(pg,r,data,parent[0],index,exact[0],index_response))
        diagnostics['checks'].append({'url':u,'status':r['status'],'accepted':bool(item)})
        if item:out.append({'item':item,'response':r,'support':[parent[1],index_response,exact[1]]})
    diagnostics['late_requests']=fetcher.requests-initial_requests
    diagnostics['unvisited_observed_details']=max(0,len(leads)-diagnostics['detail_attempts'])
    return out,diagnostics
