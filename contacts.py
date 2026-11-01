"""Literal contact links from identity-verified company pages; never guessed."""
import re
import unicodedata
from urllib.parse import unquote, urlsplit

CONTACT_LIMIT = 60

def contact_key(item):
    """One channel across pages and formatting; preserve distinct extensions."""
    value=item['value'].strip().casefold()
    if item['type']=='phone':
        base,_,extension=value.partition(';ext=')
        value=re.sub(r'\D','',base)
        if value.startswith('00'):value=value[2:]
        if len(value)==8:value='47'+value
        if extension:value+=';ext='+extension
    return item['type'],value

def contact_links(page):
    found=[];seen=set()
    for link in page.links:
        if link.get('third_party_context'):continue
        p=urlsplit(link['url']);scheme=p.scheme.casefold()
        if scheme not in {'mailto','tel'}:continue
        value=unquote(p.path).strip()
        if any(ord(c)<32 for c in value):continue
        if scheme=='mailto':
            if not re.fullmatch(r'[A-Za-z0-9.!#$%&\'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,}',value):continue
            kind='email'
        else:
            if not re.fullmatch(r'\+?[0-9 () .-]{7,25}(?:;ext=[0-9]{1,8})?',value):continue
            digits=re.sub(r'\D','',value.split(';')[0])
            if not 7<=len(digits)<=15:continue
            kind='phone'
        key=(kind,value)
        if key in seen:continue
        seen.add(key)
        found.append({'type':kind,'value':value,'label':re.sub(r'\s+',' ',link['text']).strip()[:160],
                      'source_url':page.url,'source_href':link['url']})
    return found[:CONTACT_LIMIT]


def _normal(value):
    return re.sub(r'[^\w]+',' ',str(value).casefold()).strip()


def _contact_scopes(page,include_text=False,include_blocks=False):
    from html.parser import HTMLParser
    from urllib.parse import urljoin
    location_page=bool(re.search(r'/(?:utsalg(?:ene)?|avdelinger?|locations?|offices?)(?:/|$)',urlsplit(page.url).path,re.I))
    class Blocks(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True);self.stack=[];self.links={};self.skip=0;self.section=None;self.sections=[];self.footers=[];self.blocks=[];self.node_count=0
        def handle_starttag(self,t,attrs):
            a=dict(attrs)
            context=' '.join(str(a.get(k) or '') for k in ('class','id','role','aria-label'))
            excluded=any(n.get('excluded') for n in self.stack) or bool(re.search(r'sponsor|partner|customer|author|agency|webdesign|site.credit|powered.by',context,re.I))
            if t in {'h1','h2','h3','h4','h5','h6'}:
                self.section={'tag':'heading_section','text':'','excluded':excluded};self.sections.append(self.section)
            if t not in {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}:
                inside_article=any(n['tag']=='article' for n in self.stack)
                self.node_count+=1
                self.stack.append({'tag':t,'text':'','excluded':excluded,'in_form':t=='form' or any(n['tag']=='form' for n in self.stack),'scope_id':self.node_count,'ancestors':[n['scope_id'] for n in self.stack]})
                if t in {'p','address','article','section','div','li','td','footer'}:self.blocks.append(self.stack[-1])
                semantic=re.sub(r'(?<=[a-z])(?=[A-Z])',' ',context).replace('_',' ')
                path=urlsplit(page.url).path.casefold().rstrip('/')
                contact_page=bool(re.search(r'kontakt|contact',path))
                homepage=path in ('','/home','/hjem','/index.html','/index.php')
                global_footer=(t=='footer' or a.get('role')=='contentinfo' or bool(re.search(r'\bfooter\b',semantic,re.I))) and not inside_article
                contact_component=bool(re.search(r'\bcontact(?:s|info|information)?\b|\bkontakt(?:informasjon)?\b',semantic,re.I)) and (contact_page or homepage and not inside_article)
                if global_footer or contact_component:self.footers.append(self.stack[-1])
            if t in {'script','style','noscript'}:self.skip+=1
            if t=='a' and a.get('href'):
                try:u=urljoin(page.url,a['href'])
                except ValueError:return
                self.links.setdefault(u,[]).append(list(self.stack[-9:])+([self.section] if self.section else []))
                if urlsplit(u).scheme.casefold() in {'mailto','tel'}:
                    for node in self.stack[-9:]:
                        node.setdefault('contact_hrefs',[]).append(u)
                        node.setdefault('contact_offsets',[]).append((u,len(node['text'])))
        def handle_data(self,v):
            if self.skip or any(n.get('excluded') for n in self.stack):return
            if self.section and len(self.section['text'])<2500:self.section['text']+=v+'\n'
            for n in self.stack[-9:]:
                if len(n['text'])<2500:n['text']+=v+'\n'
        def handle_endtag(self,t):
            if t in {'script','style','noscript'}:self.skip=max(0,self.skip-1)
            for i in range(len(self.stack)-1,-1,-1):
                if self.stack[i]['tag']==t:del self.stack[i:];break
    parser=getattr(page,'_parsed_contact_blocks',None)
    if parser is None:
        parser=Blocks();parser.feed(getattr(page,'raw_html',''));page._parsed_contact_blocks=parser
    if include_blocks:return parser.links,parser.blocks
    if include_text:
        return parser.links,[n for n in parser.footers if not n.get('excluded')]+[{**n,'location_section':location_page} for n in parser.sections if not n.get('excluded') and (location_page or re.match(r'\s*(?:kontakt|contact|contact information|kontaktinformasjon)(?:\s|$)',n['text'],re.I))]
    return parser.links


def foreign_contact_bindings(pages,data):
    """Literal channels in a small, single-other-legal-entity block veto reuse.

    This also catches a foreign subsidiary's employee repeated elsewhere without
    the subsidiary name. A shared domain alone never overrides this evidence.
    """
    def namekey(value):
        value=re.sub(r'^(?:Bedrift|Company|Om|About)\s*:?\s+','',value.strip(),flags=re.I)
        value=re.sub(r'^(?:CEO|CFO|COO|CTO|EVP|Director|Officer)\b[^,\n]{0,110},\s*','',value,flags=re.I)
        return _normal(''.join(c for c in unicodedata.normalize('NFKD',value) if not unicodedata.combining(c)))
    own=namekey(data.get('navn',''));blocked={}
    legal=re.compile(r'(?:^|\n)[ \t]*(?:©\s*(?:[0-9]{4}\s*)?)?([^\n]{2,120}?\b(?:ASA|AS|AB|GmbH|Ltd\.?|Limited|LLC|Inc\.?|SIA))\s*(?=\n|$)')
    email=re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
    phone=re.compile(r'\b(?:Tel(?:efon)?|Tlf|Phone|Mobil)(?:[ \t]*:)?[ \t]*(\+?[0-9 () .-]{7,25})',re.I)
    for page,response in pages:
        _,blocks=_contact_scopes(page,include_blocks=True)
        bindings=[]
        for node in blocks:
            text=node['text']
            if node.get('excluded') or len(text)>2000:continue
            # A legal name can wrap between DOM nodes. It remains the target's
            # imprint, not a new entity named only by its last line.
            if own and re.search(r'(?im)^[ \t]*(?:©\s*(?:[0-9]{4}\s*)?)?'+r'\s+'.join(re.escape(w) for w in own.split())+r'[ \t]*(?=\n|$)',text):continue
            matches=[m for m in legal.finditer(text) if not re.search(r'(?:utviklet|laget|designet|levert)\s+av\s*$|(?:developed|designed|website|site)\s+by\s*$',text[max(0,m.start(1)-70):m.start(1)],re.I)]
            names={namekey(m.group(1)) for m in matches}
            if len(names)!=1 or own in names:continue
            if str(data.get('organisasjonsnummer','')) and re.search(r'(?<!\d)'+r'\s*'.join(data['organisasjonsnummer'])+r'(?!\d)',text):continue
            match=matches[0];name=match.group(1).strip()
            # Bind forward within the small legal contact block. A provider
            # credit after the company's contacts cannot claim those contacts.
            def nearby(position):
                return position>=match.end(1) and len(re.sub(r'\s+',' ',text[match.end(1):position]))<=350
            channels=[{'type':'email','value':m.group(0)} for m in email.finditer(text) if nearby(m.start())]
            channels += [{'type':'phone','value':m.group(1).strip().rstrip(' .-')} for m in phone.finditer(text) if nearby(m.start())]
            channels += [{'type':'email' if urlsplit(u).scheme.casefold()=='mailto' else 'phone','value':unquote(urlsplit(u).path).strip()} for u,pos in node.get('contact_offsets',[]) if nearby(pos)]
            if channels:bindings.append((node,name,channels))
        # A parent section can contain several staff cards. Bind to the
        # smallest legal contact block, never spill into a neighbouring card.
        for node,name,channels in bindings:
            if any(node['scope_id'] in other['ancestors'] and name==other_name for other,other_name,_ in bindings):continue
            for channel in channels:
                blocked.setdefault(contact_key(channel),{'reason':'same channel is explicitly published for another legal entity',
                    'other_legal_name':name,'source_url':page.url,'evidence_excerpt':node['text'].strip()[:2000]})
    return blocked


def staff_contact_scopes(page):
    """Short first-party contact cards with a role and same-domain mailbox.

    These are candidates subject to the normal foreign-entity/address vetoes.
    Bare numeric IDs, bios on news pages and other-domain mailboxes are not
    sufficient evidence that an unlabelled number is a company phone.
    """
    if not re.search(r'/(?:kontakt[^/]*|contact[^/]*|ansatte|employees|staff)(?:/|$)',urlsplit(page.url).path,re.I):return []
    host=(urlsplit(page.url).hostname or '').removeprefix('www.').casefold()
    _,blocks=_contact_scopes(page,include_blocks=True);out=[]
    for node in blocks:
        text=node['text']
        if node.get('excluded') or node.get('in_form') or len(text)>650:continue
        emails=set(re.findall(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",text))
        if len(emails)!=1 or next(iter(emails)).rsplit('@',1)[-1].casefold()!=host:continue
        if not re.search(r'\b(?:daglig leder|salgsrepresentant|prosjektleder|administrasjonssjef|rådgiver|CEO|CTO|CFO|sales manager|project manager|managing director)\b',text,re.I):continue
        out.append({**node,'staff_card':True})
    return out


def entity_contacts(page,data,units=(),conflicts=None):
    """Do not inherit another regional company's contacts from a shared site.

    A postal block outside all registered target/subunit addresses is unresolved,
    not proof of a new office. Regional pages must match a registered locality.
    No registry email or phone is returned by this function.
    """
    conflicts=foreign_contact_bindings([(page,{})],data) if conflicts is None else conflicts
    candidates=contact_links(page);addresses=[data.get(k) or {} for k in ('forretningsadresse','postadresse')]
    addresses += [u.get('address') or u.get('beliggenhetsadresse') or {} for u in units if isinstance(u,dict)]
    codes={str(a['postnummer']) for a in addresses if a.get('postnummer')}
    places={_normal(a[k]) for a in addresses for k in ('kommune','poststed') if a.get(k)}
    scopes,text_scopes=_contact_scopes(page,include_text=True);out=[];held=[];literal_scopes={}
    text_scopes+=staff_contact_scopes(page)
    # Exact legal-name/address imprints can be plain paragraphs in simple sites.
    full_name=_normal(data.get('navn',''))
    for index,p in enumerate(page.paragraphs):
        if full_name and _normal(p)==full_name:
            text_scopes.append({'tag':'legal_imprint','text':' '.join(page.paragraphs[index:index+5])})
    stem=re.sub(r' (as|asa|sti|nuf)$','',_normal(data.get('navn','')))
    for scope in text_scopes:
        text=scope['text']
        if scope.get('location_section'):
            heading=_normal(text.split('\n',1)[0])
            if not (len(stem)>=4 and heading.startswith(stem+' ') and any(re.search(r'(?<!\w)'+re.escape(p)+r'(?!\w)',heading) for p in places)):continue
        found=[('email',m.group(0),m.group(0)) for m in re.finditer(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,}",text)]
        for match in re.finditer(r'\b(?:Tel(?:efon)?|Tlf|Phone|Mobil)\s*:?[ \t]*(\+?[0-9 () .-]{7,25})',text,re.I):
            value=match.group(1).strip().rstrip(' .-')
            if 7<=len(re.sub(r'\D','',value))<=15:found.append(('phone',value,match.group(0).strip()))
        for match in re.finditer(r'(?m)^[ \t]*(\+[0-9][0-9 () .-]{7,22})[ \t]*$',text):
            value=match.group(1).strip()
            if 8<=len(re.sub(r'\D','',value))<=15:found.append(('phone',value,value))
        if scope.get('staff_card'):
            # A complete, formatted Norwegian phone line in a contact card.
            # Never turn arbitrary eight-digit IDs or dates into phone facts.
            for line in text.splitlines():
                value=re.sub(r'\s+',' ',line).strip()
                if re.fullmatch(r'(?:\+47[ .-]?)?\d{2}[ .-]\d{2}[ .-]\d{2}[ .-]\d{2}',value):
                    found.append(('phone',value,value))
        for kind,value,label in found:
            item={'type':kind,'value':value,'label':label[:160],'source_url':page.url,'source_href':None,
                  'source_kind':'literal_visible_text','source_pointer':'visible company contact/footer or exact legal-imprint block'}
            candidates.append(item);literal_scopes[id(item)]=[[scope]]
    regional=False
    title=_normal(re.split(r'\s+[|–—]\s*|\|',page.title)[0])
    if len(stem)>=5 and stem in title:
        remainder=title.replace(stem,' ')
        for place in sorted(places,key=len,reverse=True):remainder=remainder.replace(place,' ')
        remainder=re.sub(r'\b(?:as|asa|ansatte|employees|team|staff|kontakt|contact|oss|about|om|us|home|hjem)\b',' ',remainder)
        # Only very short company+regional labels, never ordinary article titles.
        regional=bool(remainder.strip() and len(title.split())<=7 and
                      re.search(r'ansatte|employees|staff',title))
    regional_label=re.search(r'\b(?:ansatte|employees|staff)\s+(?:i|in|at)\s+(.+)$',title)
    if places and regional_label:
        locality=regional_label.group(1).strip()
        regional=not any(locality==place or locality.startswith(place+' ') for place in places)
    archive=bool(re.search(r'/(?:news|nyheter|aktuelt|blogg?|updates)/page/[0-9]+',urlsplit(page.url).path,re.I))
    own_host=(urlsplit(page.url).hostname or '').removeprefix('www.')
    located_keys=set()
    for item in candidates:
        reason='regional staff page is not tied to a registered target locality' if regional else None
        conflict=conflicts.get(contact_key(item))
        # A short staff/contact card can repeat a foreign entity's email with a
        # locally formatted phone number. Do not guess a country calling code.
        if not conflict:
            for ancestry in literal_scopes.get(id(item),scopes.get(item.get('source_href'),[])):
                for node in reversed(ancestry):
                    if node['tag'] not in {'p','address','article','section','div','li','td'} or len(node['text'])>800:continue
                    emails=re.findall(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",node['text'])
                    emails += [unquote(urlsplit(u).path).strip() for u in node.get('contact_hrefs',[]) if urlsplit(u).scheme.casefold()=='mailto']
                    if len(set(emails))>2:continue
                    conflict=next((conflicts[('email',e.casefold())] for e in emails if ('email',e.casefold()) in conflicts),None)
                    # Stop at the closest contact-bearing card. A higher
                    # container containing another employee is not its owner.
                    if emails:break
                if conflict:break
        if conflict:reason=conflict['reason']
        if archive and item['type']=='email' and item['value'].rsplit('@',1)[-1].casefold()!=own_host.casefold():
            reason='news archive mentions another-domain contact; own-company contact role not established'
        observations=[];postal_nodes=[]
        if not reason:
            for ancestry in literal_scopes.get(id(item),scopes.get(item['source_href'],[])):
                for node in reversed(ancestry):
                    if node['tag'] in {'a','span','strong','b','i','svg','path'}:continue
                    found=set(re.findall(r'(?<!\d)([0-9]{4})[ \t]+[A-ZÆØÅ][A-Za-zÆØÅæøåéü-]+',node['text']))
                    if found:
                        observations.append(found);postal_nodes.append(node);break
            if codes and observations and not any(v and v<=codes for v in observations):
                domain=(item['value'].rsplit('@',1)[-1].casefold() if item['type']=='email' else '')
                same_business_domain=domain and domain.removeprefix('www.').split('.')[0]==own_host.casefold().split('.')[0]
                own_imprint=any(n['tag']!='heading_section' and full_name and re.search(r'(?<!\w)'+re.escape(full_name)+r'(?!\w)',_normal(n['text'])) for n in postal_nodes)
                if not (same_business_domain and own_imprint):
                    reason='contact block contains a postal address outside the registered target/subunits; separate-entity ownership unresolved'
            elif codes and observations:located_keys.add(contact_key(item))
        if reason:
            record={'type':item['type'],'value':item['value'],'source_url':page.url,'reason':reason}
            if conflict:record['conflicting_entity_binding']=conflict
            held.append(record)
        else:out.append(item)
    # An unscoped text copy cannot bypass a scoped conflicting address. Keep
    # shared channels only when another block explicitly matches a target unit.
    # A changed office address alone does not prove that a company's own-domain
    # mailbox or switchboard belongs to someone else. Cross-scope propagation
    # requires a different business domain as well as the conflicting address.
    def different_domain(item):
        if item['type']!='email':return False
        domain=item['value'].rsplit('@',1)[-1].casefold().removeprefix('www.')
        current=own_host.casefold()
        return domain!=current and domain.split('.')[0]!=current.split('.')[0]
    address_conflicts={contact_key(h):h for h in held if h['reason'].startswith('contact block contains a postal address') and different_domain(h)}
    filtered=[]
    for item in out:
        key=contact_key(item)
        if key in address_conflicts and key not in located_keys:
            held.append({'type':item['type'],'value':item['value'],'source_url':page.url,
                         'reason':'unscoped copy cannot override a conflicting contact-block address'})
        else:filtered.append(item)
    out=filtered
    # Formatting variants of the same phone/email are one contact fact.
    unique=[];seen=set()
    for item in out:
        key=contact_key(item)
        if key not in seen:seen.add(key);unique.append(item)
    return unique[:CONTACT_LIMIT],held


def collect_entity_contacts(pages,data,units=()):
    """Cross-page veto, normalized uniqueness, and retained literal variants."""
    conflicts=foreign_contact_bindings(pages,data)
    channels=[];by_key={};held=[];sources=[]
    for page,response in pages:
        items,limits=entity_contacts(page,data,units,conflicts=conflicts)
        held.extend(limits)
        used=False
        for item in items:
            key=contact_key(item)
            if key in by_key:
                first=by_key[key]
                if item!=first and item not in first.get('additional_source_variants',[]):
                    first.setdefault('additional_source_variants',[]).append(dict(item))
                used=True
            elif len(channels)<CONTACT_LIMIT:
                item=dict(item);channels.append(item);by_key[key]=item;used=True
        # Contradictory source evidence is part of the abstention audit too.
        if used or any(b['source_url']==page.url for b in conflicts.values()):sources.append(response)
    unique_limits={}
    for limit in held:
        key=(*contact_key(limit),limit['source_url'],limit['reason'])
        unique_limits.setdefault(key,limit)
    held=sorted(unique_limits.values(),key=lambda h:0 if h.get('conflicting_entity_binding') else 1)
    return channels,held,sources
