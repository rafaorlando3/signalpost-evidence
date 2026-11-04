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
    if full==stem or len(stem)<5:return registered_email_brand_address(data,pages,compatible)
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
    # A semantic footer can identify its full legal contact owner without a
    # separate "Contact" heading. The complete brand, immediate labelled phone
    # and same-host mailbox remain required; neither a bare title nor a group
    # label is sufficient. Keep obfuscated mailbox text literal in the proof.
    from contacts import _contact_scopes
    _,scoped_nodes=_contact_scopes(home,include_text=True)
    footer=re.sub(r'\s+',' ',' '.join(n['text'] for n in scoped_nodes if n['tag']=='footer' and not n.get('excluded'))).strip()
    owner=literal_name(footer,data.get('navn',''))
    own_mail=next((m.group(0) for m in re.finditer(r'[a-zA-Z0-9._%+\-]+@([a-zA-Z0-9.\-]+\.[A-Za-z]{2,})',footer)
                   if m.group(1).casefold().removeprefix('www.')==(host or '').casefold().removeprefix('www.')),None)
    owner_phone=(re.match(r'\s+(?:tlf|tel(?:efon)?|phone)[.:]?\s*:?\s*(\+?[0-9 () .-]{7,25})',footer[owner['end']:],re.I)
                 if owner and not footer[:owner['start']].strip() else None)
    obfuscated_mail=next((m.group(0) for m in re.finditer(r'[a-zA-Z0-9._%+\-]+\s*\(at\)\s*([a-zA-Z0-9.\-]+\.[A-Za-z]{2,})',footer)
                          if m.group(1).casefold().removeprefix('www.')==(host or '').casefold().removeprefix('www.')),None)
    if (owner_phone and 8<=len(re.sub(r'\D','',owner_phone[1]))<=15 and len(footer)<=650
            and copyright_brand in {stem,full} and (own_mail or obfuscated_mail) and span):
        return {'method':'linked_first_party_legal_name','organisation_number':data.get('organisasjonsnummer'),
            'registered_name':data.get('navn'),'entry_url':home.url,'source_url':home.url,
            'self_identification':footer,'literal_spans':[span],'links':[],
            'contact_footer_statement':footer,'literal_contact_phone':owner_phone[1].strip(),
            'literal_same_host_mailbox':own_mail or obfuscated_mail,
            'name_normalization':'casefold; ae/oe are not inferred; æ=ae, ø=o, combining accents removed; legal differentiators retained',
            'scope':'semantic homepage footer starts with full legal contact owner; complete brand plus immediate labelled telephone and literal same-host mailbox; no registry contacts or printed corporate number inferred'}
    return (registered_email_brand_address(data,pages,compatible)
            or scoped_legal_contact_address(data,pages,compatible))


def registered_email_brand_address(data,pages,compatible):
    """Legal homepage brand + registry email domain + own contact address.

    The registry mailbox nominates a domain; it is not published as a contact.
    The page must independently display the full legal name in its own brand
    and the exact registered street/postcode in a labelled semantic footer.
    """
    from registry_discovery import FREE_EMAIL
    from agent import group_description
    if not pages:return None
    home=pages[0][0];entry=canonical(home.url)
    if not entry or urlsplit(entry).path not in ('','/home','/hjem','/index.html','/index.php'):return None
    full=fold(data.get('navn',''));stem=re.sub(r' (?:as|asa|sa|sti|da|ans|nuf)$','',full)
    if not 3<=len(stem)<=120 or full==stem:return None
    mailbox=data.get('epostadresse');domain=mailbox.rsplit('@',1)[1].strip().casefold() if isinstance(mailbox,str) and mailbox.count('@')==1 else ''
    host=(urlsplit(entry).hostname or '').removeprefix('www.')
    if not domain or domain in FREE_EMAIL or domain.removeprefix('www.')!=host:return None
    # Keep the entire legal name, including the suffix and locality. A brand
    # stem or mention in a customer list cannot replace these two owner labels.
    if fold(home.meta.get('og:site_name',''))!=full or not literal_name(home.title,data.get('navn','')):return None
    if any(not compatible(pg) for pg,_ in pages):return None
    if any(group_description(v) for v in [home.description,*home.paragraphs]):return None
    footer=re.sub(r'\s+',' ',' '.join(home.footer_parts)).strip()
    if not footer or len(footer)>1800 or not re.search(r'\b(?:besøksadresse|visiting address|office address|hovedkontor)\b',footer,re.I):return None
    name_span=literal_name(home.text,data.get('navn',''))
    if not name_span:return None
    # The contact address is adjacent to its owner-role label, rather than a
    # postcode elsewhere in the page or a partner's separately labelled block.
    for kind in ('forretningsadresse','postadresse'):
        a=data.get(kind) or {};street=next(iter(a.get('adresse') or []),'');postal=str(a.get('postnummer') or '')
        if not street or not re.fullmatch(r'\d{4}',postal):continue
        street_local=literal_name(footer,street)
        if not street_local:continue
        prefix=footer[max(0,street_local['start']-100):street_local['start']]
        if not re.search(r'(?:besøksadresse|visiting address|office address|hovedkontor)\s*(?::|–|-)?\s*(?:'+re.escape(data.get('navn',''))+r'\s*,?\s*)?$',prefix,re.I):continue
        tail=footer[street_local['end']:street_local['end']+35]
        if not re.match(r'\W*(?:NO\W*)?'+re.escape(postal)+r'(?!\d)',tail,re.I):continue
        street_span=literal_name(home.text,street);postal_span=literal_name(home.text,postal)
        if not street_span or not postal_span:continue
        return {'method':'linked_first_party_legal_name','organisation_number':data.get('organisasjonsnummer'),
            'registered_name':data.get('navn'),'entry_url':home.url,'source_url':home.url,
            'self_identification':home.title,'literal_spans':[name_span,street_span,postal_span],'links':[],
            'registry_email_domain_binding':domain,'contact_address_statement':footer,
            'address_kind':kind,'registered_street':street,'registered_postcode':postal,
            'name_normalization':'casefold; full legal form and locality retained; æ=ae, ø=o; combining accents removed',
            'scope':'full legal OpenGraph brand and title plus registry email domain and exact registered labelled visiting address in semantic homepage footer; registry email itself is not a website contact'}
    return None


def scoped_legal_contact_address(data,pages,compatible):
    """Full legal contact owner and street, with a separately qualified postcode.

    A company can print a wrong/stale postcode without losing its explicitly
    stated legal identity. Never turn that discrepancy into address verification.
    """
    from contacts import _contact_scopes
    from agent import group_description
    if not pages:return None
    home=pages[0][0];entry=canonical(home.url)
    if not entry or urlsplit(entry).path not in ('','/home','/hjem','/index.html','/index.php'):return None
    full=fold(data.get('navn',''));stem=re.sub(r' (?:as|asa|sa|sti|da|ans|nuf)$','',full)
    if len(stem)<6 or full==stem:return None
    brand=fold(home.meta.get('og:site_name') or re.split(r'\s+[|–—]\s*|\s+-\s*|\|',home.title)[0])
    if brand not in {full,stem} or any(not compatible(pg) for pg,_ in pages):return None
    if any(group_description(v) for v in [home.description,*home.paragraphs]):return None
    host=(urlsplit(entry).hostname or '').removeprefix('www.')
    _,blocks=_contact_scopes(home,include_blocks=True)
    own_visible_blocks=set(self_description_blocks(home))
    for node in sorted(blocks,key=lambda n:len(n['text'])):
        if node['tag'] not in {'section','div','address'} or node.get('excluded') or node.get('in_form'):continue
        block=re.sub(r'\s+',' ',node['text']).strip()
        if not 40<=len(block)<=1600 or block not in own_visible_blocks:continue
        owner=literal_name(block,data.get('navn',''))
        if not owner or owner['start']>90:continue
        prefix=fold(block[:owner['start']])
        if prefix and not re.fullmatch(r'(?:kontakt(?: oss)?|contact(?: us)?)(?: for et tilbud| for a quote)?',prefix):continue
        if re.search(r'ekstern aktør|our partners|våre partnere|forhandlere|distributors',block,re.I):continue
        email=next((m.group(0) for m in re.finditer(r'[A-Za-z0-9._%+\-]+@([A-Za-z0-9.\-]+\.[A-Za-z]{2,})',block)
                    if m[1].casefold().removeprefix('www.')==host),None)
        phone=re.search(r'\b(?:tlf|telefon|phone|tel)\s*:?\s*(\+?[0-9 ().-]{7,25})',block,re.I)
        if not email or not phone or not 8<=len(re.sub(r'\D','',phone[1]))<=15:continue
        for kind in ('forretningsadresse','postadresse'):
            address=data.get(kind) or {}
            for street in address.get('adresse') or []:
                local=literal_name(block,street)
                if not local or not owner['end']<=local['start']<=owner['end']+6:continue
                if not re.fullmatch(r'\W*',block[owner['end']:local['start']]):continue
                postal=re.match(r'\W*(\d{4})(?!\d)',block[local['end']:])
                if not postal:continue
                name_span=literal_name(home.text,data.get('navn',''));street_span=literal_name(home.text,street)
                if not name_span or not street_span:continue
                registered_postal=address.get('postnummer');published_postal=postal[1]
                return {'method':'linked_first_party_legal_name','organisation_number':data.get('organisasjonsnummer'),
                    'registered_name':data.get('navn'),'entry_url':home.url,'source_url':home.url,
                    'self_identification':block,'literal_spans':[name_span,street_span],'links':[],
                    'scoped_legal_contact_statement':block,'registered_street':street,'address_kind':kind,
                    'published_postcode':published_postal,'registered_postcode':registered_postal,
                    'postcode_state':'matches_registry' if published_postal==registered_postal else 'conflicts_with_registry; address not verified',
                    'name_normalization':'casefold; full legal form and locality retained; æ=ae, ø=o; combining accents removed',
                    'scope':'complete own homepage brand; explicit full legal contact owner immediately followed by registered street; scoped literal same-host email and labelled phone; postcode kept as a separate qualified observation'}
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
