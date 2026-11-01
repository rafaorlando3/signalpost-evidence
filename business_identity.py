"""Scoped first-party self-description plus registered address, linked on site.

Name/domain heuristics are URL leads only. Identity requires a business's own
explicit legal self-description, its exact registered street/postcode and an
observed path from its homepage. Quotes, customer widgets, group operators and
cross-host pages must never provide a shortcut to legal identity.
"""
import re
from collections import deque
from html.parser import HTMLParser
from urllib.parse import urlsplit,urlunsplit


def normal(value):return re.sub(r'[^\w]+',' ',str(value).casefold()).strip()


def canonical(url):
    try:
        p=urlsplit(url)
        if p.scheme not in {'http','https'} or p.username or p.password or p.port not in (None,80,443):return None
        return urlunsplit((p.scheme,p.netloc.casefold(),p.path.rstrip('/'),p.query,''))
    except ValueError:return None


def literal_span(text,value):
    pattern=r'\W+'.join(re.escape(x) for x in normal(value).split())
    m=re.search(r'(?<!\w)'+pattern+r'(?!\w)',text,re.I) if pattern else None
    return {'start':m.start(),'end':m.end(),'text':text[m.start():m.end()]} if m else None


def self_description_blocks(page):
    """Visible business text, including CMS blocks that do not use paragraphs."""
    if hasattr(page,'_business_self_description_blocks'):return page._business_self_description_blocks
    class Blocks(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True);self.stack=[];self.blocks=[]
        def handle_starttag(self,tag,attrs):
            if tag in {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}:return
            a=dict(attrs);context=' '.join(str(a.get(k) or '') for k in ('class','id','role','aria-label'))
            excluded=bool(self.stack and self.stack[-1]['excluded']) or tag in {'head','script','style','noscript','nav','header','footer','aside','form','dialog','blockquote','q'} or bool(re.search(r'sponsor|partner|customer|testimonial|author|agency|webdesign|site.credit|powered.by',context,re.I))
            node={'tag':tag,'excluded':excluded,'parts':[],'size':0};self.stack.append(node)
            if tag in {'p','div','section','font','span','h1','h2','h3'}:self.blocks.append(node)
        def handle_data(self,value):
            if not self.stack or self.stack[-1]['excluded']:return
            for node in self.stack:
                if not node['excluded'] and node['size']<2200:node['parts'].append(value);node['size']+=len(value)+1
        def handle_endtag(self,tag):
            for i in range(len(self.stack)-1,-1,-1):
                if self.stack[i]['tag']==tag:del self.stack[i:];break
    parser=Blocks();parser.feed(page.raw_html)
    page._business_self_description_blocks=list(dict.fromkeys(re.sub(r'\s+',' ',' '.join(n['parts'])).strip() for n in parser.blocks if not n['excluded'] and n['parts'] and n['size']<=2000))
    return page._business_self_description_blocks


def business_identity(data,pages,identity_check=None):
    """Return reproducible literal proof or None; takes only fetched pages."""
    if not pages or identity_check is None:return None
    home=pages[0][0];entry=canonical(home.url)
    if not entry or urlsplit(entry).path not in ('','/home','/hjem','/index.html','/index.php'):return None
    host=urlsplit(entry).hostname
    full=normal(data.get('navn',''));stem=re.sub(r' (as|asa|sti|nuf|sa)$','',full)
    if len(stem)<5 or full==stem:return None
    # Every legal differentiator stays in the pattern; no short brand matching.
    role=re.compile(r'^(?:(?:vi(?: i)?|we(?: at)?) )?'+re.escape(full)+r' (?:(?:er|har|tilbyr|leverer|driver|utvikler|produserer|holder)\b|(?:is|has|offers|provides|develops|was founded)\b)')
    eligible=[];graph={}
    for page,response in pages:
        key=canonical(page.url)
        if not key or urlsplit(key).hostname!=host or not identity_check(page):continue
        path=urlsplit(key).path
        if path and not re.search(r'/(?:kontakt[^/]*|contact[^/]*|om[-_]?oss|about(?:-us)?|imprint|impressum|legal)(?:/|$)',path,re.I):continue
        eligible.append((key,page,response))
        graph[key]=[(canonical(l['url']),l['url']) for l in page.links if not l.get('third_party_context') and canonical(l['url']) and urlsplit(l['url']).hostname==host]
    keys={key for key,_,_ in eligible}
    def path_to(target):
        queue=deque([(entry,[])]);seen=set()
        while queue:
            key,links=queue.popleft()
            if key in seen:continue
            seen.add(key)
            if key==target:return links
            if len(links)>=2:continue
            for child,raw in graph.get(key,[]):
                if child in keys:queue.append((child,links+[{'source_url':key,'target_url':child,'literal_href':raw}]))
        return None
    legal=[]
    for key,page,response in eligible:
        links=path_to(key)
        if links is None:continue
        for paragraph in self_description_blocks(page):
            if not role.search(normal(paragraph)):continue
            offset=page.text.find(paragraph)
            if offset<0:continue
            part=literal_span(paragraph,full)
            span={**part,'start':part['start']+offset,'end':part['end']+offset} if part else None
            if span:
                legal.append((key,page,{'source_url':page.url,'self_description':paragraph,'name_span':span,'links':links}))
    if not legal:return None
    brands=[home.title,home.meta.get('og:site_name',''),home.meta.get('og:title',''),*home.content_headings]
    branded=any(re.search(r'(?<!\w)'+re.escape(stem)+r'(?!\w)',normal(b)) for b in brands)
    if not branded and not any(key==entry for key,_,_ in legal):return None
    for key,page,response in eligible:
        links=path_to(key)
        if links is None:continue
        for field in ('forretningsadresse','postadresse'):
            address=data.get(field) or {};street=next(iter(address.get('adresse') or []),'');postal=address.get('postnummer')
            if not street or not postal:continue
            # Do not select unrelated matching numbers elsewhere in the site.
            street_span=literal_span(page.text,street)
            if not street_span:continue
            local=page.text[max(0,street_span['start']-400):street_span['end']+400]
            if not re.search(r'(?<!\w)'+re.escape(stem)+r'(?!\w)',normal(local)):continue
            start=max(0,street_span['start']-150);near=page.text[start:street_span['end']+150]
            match=re.search(r'(?<!\d)'+re.escape(str(postal))+r'(?!\d)',near)
            if not match:continue
            postal_span={'start':start+match.start(),'end':start+match.end(),'text':match[0]}
            return {'method':'linked_business_self_description_and_registered_address',
                'registered_name':data.get('navn'),'organisation_number':data.get('organisasjonsnummer'),
                'entry_url':home.url,'legal_name_source':legal[0][2],
                'address_source':{'source_url':page.url,'address_kind':field,'registered_street':street,'registered_postcode':postal,
                                  'literal_spans':[street_span,postal_span],'links':links},
                'scope':'first-party legal self-description plus exact registered address; no registry contact published'}
    return None
