"""Reproducible first-party legal-name proof, preserving legal differentiators.

Registry URLs and guessed domains are leads. A matching title alone is not proof:
the same linked site must identify itself in scoped visible business content.
"""
import re
import unicodedata
from collections import deque
from urllib.parse import urlsplit
from business_identity import canonical, self_description_blocks


def fold(value):
    value=str(value).casefold().replace('æ','ae').replace('ø','o')
    value=unicodedata.normalize('NFKD',value)
    value=''.join(c for c in value if not unicodedata.combining(c))
    return re.sub(r'[^\w]+',' ',value).strip()


def literal_name(text, value):
    # Keep original offsets even when one Norwegian character expands to two.
    chars=[];offsets=[]
    for i,ch in enumerate(text):
        translated=unicodedata.normalize('NFKD',ch.casefold().replace('æ','ae').replace('ø','o'))
        for part in translated:
            if not unicodedata.combining(part):chars.append(part if part.isalnum() or part=='_' else ' ');offsets.append(i)
    normalized=''.join(chars);name=fold(value)
    pattern=r'\s+'.join(re.escape(x) for x in name.split())
    match=re.search(r'(?<!\w)'+pattern+r'(?!\w)',normalized) if pattern else None
    if not match:return None
    start=offsets[match.start()];end=offsets[match.end()-1]+1
    return {'start':start,'end':end,'text':text[start:end]}


def legal_name_identity(data,pages,compatible):
    if not pages or not compatible:return None
    home=pages[0][0];entry=canonical(home.url)
    if not entry or urlsplit(entry).path not in ('','/home','/hjem','/index.html','/index.php'):return None
    host=urlsplit(entry).hostname;full=fold(data.get('navn',''))
    stem=re.sub(r' (?:as|asa|sa|nuf|da|ans|sti)$','',full)
    # No shortening of initials, geography or other legal differentiators.
    if full==stem or len(stem)<5:return None
    brands=[home.title,home.meta.get('og:site_name',''),*home.content_headings]
    if not any(literal_name(b,stem) for b in brands):return None
    if any(not compatible(pg) for pg,_ in pages):return None
    eligible={canonical(pg.url):(pg,rsp) for pg,rsp in pages if canonical(pg.url) and urlsplit(pg.url).hostname==host}
    graph={key:[canonical(link['url']) for link in pg.links if not link.get('third_party_context') and canonical(link['url']) in eligible] for key,(pg,_) in eligible.items()}
    paths={entry:[]};queue=deque([entry])
    while queue:
        key=queue.popleft()
        if len(paths[key])>=2:continue
        for child in graph.get(key,[]):
            if child not in paths:paths[child]=paths[key]+[{'source_url':key,'target_url':child}];queue.append(child)
    verbs=r'(?:er|har|tilbyr|leverer|driver|utvikler|produserer|holder|utforer|bestar|ble|vart|is|has|offers|provides|develops|was)\b'
    for key,(pg,rsp) in eligible.items():
        if key not in paths:continue
        path=urlsplit(key).path
        contact=bool(re.search(r'/(?:kontakt[^/]*|contact[^/]*|connect|imprint|impressum|legal)(?:/|$)',path,re.I))
        if path and not contact and not re.search(r'/(?:om[-_]?oss|about(?:-us)?)(?:/|$)',path,re.I):continue
        for block in sorted(self_description_blocks(pg),key=len):
            normal=fold(block)
            # Full legal name remains required in the visible self-identification.
            role=re.match(r'^(?:(?:vi(?: i)?|we(?: at)?) )?'+re.escape(full)+r' '+verbs,normal)
            contact_owner=contact and (normal==full or normal.startswith(full+' ')) and len(block)<=650 and bool(re.search(r'@|\b(?:telefon|phone|tlf|adresse|address)\b|\b\d{4}\b',block,re.I))
            if not role and not contact_owner:continue
            span=literal_name(pg.text,data['navn'])
            # The literal span must belong to this scoped block, not a customer list.
            local=literal_name(block,data['navn'])
            if not span or not local:continue
            return {'method':'linked_first_party_legal_name','organisation_number':data.get('organisasjonsnummer'),
                'registered_name':data.get('navn'),'entry_url':home.url,'source_url':pg.url,
                'self_identification':block,'literal_spans':[span],'links':paths[key],
                'name_normalization':'casefold; ae/oe are not inferred; æ=ae, ø=o, combining accents removed; legal differentiators retained',
                'scope':'matching homepage brand plus linked scoped visible legal self-identification; domain alone is not identity'}
    # A compact contact-owner line need not have a /contact URL or a semantic
    # footer element. Require the declared domain, complete brand/legal name,
    # an immediate contact separator and a labelled literal telephone.
    declared=data.get('hjemmeside')
    if isinstance(declared,str):
        declared=canonical(declared if '://' in declared else 'https://'+declared)
    declared_host=(urlsplit(declared).hostname or '').removeprefix('www.') if declared else ''
    if declared_host and declared_host==host.removeprefix('www.'):
        for block in sorted(self_description_blocks(home),key=len):
            if len(block)>350:continue
            local=literal_name(block,data.get('navn',''))
            if not local or block[:local['start']].strip():continue
            if not re.match(r'\s*[•|;–—]',block[local['end']:]):continue
            phone=re.search(r'\b(?:tel(?:efon)?|tlf|phone)\s*:\s*(\+?[0-9 () .-]{7,25})',block,re.I)
            if not phone or not 8<=len(re.sub(r'\D','',phone[1]))<=15:continue
            span=literal_name(home.text,data.get('navn',''))
            if not span:continue
            return {'method':'linked_first_party_legal_name','organisation_number':data.get('organisasjonsnummer'),
                'registered_name':data.get('navn'),'entry_url':home.url,'source_url':home.url,
                'self_identification':block,'literal_spans':[span],'links':[],
                'contact_footer_statement':block,'literal_contact_phone':phone[1].strip(),
                'registered_domain_match':declared_host,
                'name_normalization':'casefold; ae/oe are not inferred; æ=ae, ø=o, combining accents removed; legal differentiators retained',
                'scope':'declared domain and matching complete brand; full legal owner starts a scoped contact line with an immediate separator and labelled telephone; no corporate number asserted as printed'}
    # Some sites put the complete legal owner in a copyright line rather than
    # repeating it in a grammatical company introduction. Require that explicit
    # owner role, the unchanged full brand and an own-business introduction.
    footer=re.sub(r'\s+',' ',' '.join(home.footer_parts)).strip()
    owner=literal_name(footer,data.get('navn',''))
    statement=None
    copyright_brand=fold(home.meta.get('og:site_name') or re.split(r'\s+[|–—]\s*|\s+-\s*|\|',home.title)[0])
    if owner and len(footer)<=1200 and copyright_brand in {stem,full}:
        before=footer[max(0,owner['start']-45):owner['start']]
        after=footer[owner['end']:owner['end']+35]
        copyright_role=(bool(re.search(r'©\s*(?:(?:Copyright|20[0-9]{2})\s*)?$',before,re.I))
                        or bool(re.match(r'\s*©\s*20[0-9]{2}\b',after)))
        if copyright_role:
            statement=next((b for b in self_description_blocks(home) if 45<=len(b)<=900 and re.match(
                r'^(?:vi (?:er|har|tilbyr|leverer|driver|utvikler|produserer|legger|arbeider|jobber|kan)|we (?:are|have|offer|provide|develop|speciali[sz]e|focus))\b',fold(b))),None)
    span=literal_name(home.text,data.get('navn',''))
    if statement and span:
        return {'method':'linked_first_party_legal_name','organisation_number':data.get('organisasjonsnummer'),
            'registered_name':data.get('navn'),'entry_url':home.url,'source_url':home.url,
            'self_identification':footer,'literal_spans':[span],'links':[],
            'copyright_statement':footer,'business_self_description':statement,
            'name_normalization':'casefold; ae/oe are not inferred; æ=ae, ø=o, combining accents removed; legal differentiators retained',
            'scope':'matching complete brand, full legal owner in copyright line and scoped own-business introduction; organisation number is not asserted as printed on site'}
    # A homepage may put the same full legal contact owner in its semantic
    # footer instead of a /contact route. Require an explicit contact label,
    # unchanged full legal name, complete own brand and a same-host email.
    contact_footer=bool(owner and len(footer)<=650 and copyright_brand in {stem,full}
        and re.match(r'^(?:kontakt(?: oss)?|contact(?: us)?) '+re.escape(full)+r'(?: |$)',fold(footer)))
    own_mail=next((m.group(0) for m in re.finditer(r'[a-zA-Z0-9._%+\-]+@([a-zA-Z0-9.\-]+\.[A-Za-z]{2,})',footer)
                   if m.group(1).casefold().removeprefix('www.')==(host or '').casefold().removeprefix('www.')),None)
    if contact_footer and own_mail and span:
        return {'method':'linked_first_party_legal_name','organisation_number':data.get('organisasjonsnummer'),
            'registered_name':data.get('navn'),'entry_url':home.url,'source_url':home.url,
            'self_identification':footer,'literal_spans':[span],'links':[],
            'contact_footer_statement':footer,'same_host_contact_email':own_mail,
            'name_normalization':'casefold; ae/oe are not inferred; æ=ae, ø=o, combining accents removed; legal differentiators retained',
            'scope':'complete own brand and full legal owner in explicit homepage contact footer with same-host email; org number is not asserted as printed'}
    return None


def contact_footer_business_description(data,page):
    """A supported business introduction, never a homepage news paragraph.

    Used only for the explicit full-legal-owner contact-footer proof. Metadata
    nominates a sentence; that identical sentence must be visible in the body.
    """
    import html
    value=page.meta.get('og:description')
    if not isinstance(value,str):return None
    value=re.sub(r'\s+',' ',html.unescape(value)).strip()
    sentence=re.split(r'(?<=[.!?])\s+',value,maxsplit=1)[0]
    full=fold(data.get('navn',''));stem=re.sub(r' (?:as|asa|sa|nuf|da|ans|sti)$','',full)
    normal=fold(sentence)
    if not 45<=len(sentence)<=700 or not re.match(r'^'+re.escape(stem)+r' (?:.{0,110} )?(?:er|is|are|tilbyr|offers|leverer|provides|driver|produserer|develops)\b',normal):return None
    body=re.sub(r'\s+',' ',' '.join(page.body_parts)).strip()
    if sentence not in body:return None
    return sentence
