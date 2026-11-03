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
    return None
