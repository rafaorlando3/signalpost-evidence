"""Literal contact links from identity-verified company pages; never guessed."""
import re
from urllib.parse import unquote, urlsplit

CONTACT_LIMIT = 40

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


def _contact_scopes(page,include_text=False):
    from html.parser import HTMLParser
    from urllib.parse import urljoin
    class Blocks(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True);self.stack=[];self.links={};self.skip=0;self.section=None;self.sections=[];self.footers=[]
        def handle_starttag(self,t,attrs):
            a=dict(attrs)
            context=' '.join(str(a.get(k) or '') for k in ('class','id','role','aria-label'))
            excluded=any(n.get('excluded') for n in self.stack) or bool(re.search(r'sponsor|partner|customer|author|agency|webdesign|site.credit|powered.by',context,re.I))
            if t in {'h1','h2','h3','h4','h5','h6'}:
                self.section={'tag':'heading_section','text':'','excluded':excluded};self.sections.append(self.section)
            if t not in {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}:
                inside_article=any(n['tag']=='article' for n in self.stack)
                self.stack.append({'tag':t,'text':'','excluded':excluded})
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
        def handle_data(self,v):
            if self.skip or any(n.get('excluded') for n in self.stack):return
            if self.section and len(self.section['text'])<2500:self.section['text']+=v+'\n'
            for n in self.stack[-9:]:
                if len(n['text'])<2500:n['text']+=v+'\n'
        def handle_endtag(self,t):
            if t in {'script','style','noscript'}:self.skip=max(0,self.skip-1)
            for i in range(len(self.stack)-1,-1,-1):
                if self.stack[i]['tag']==t:del self.stack[i:];break
    parser=Blocks();parser.feed(getattr(page,'raw_html',''))
    if include_text:
        return parser.links,[n for n in parser.footers if not n.get('excluded')]+[n for n in parser.sections if not n.get('excluded') and re.match(r'\s*(?:kontakt|contact|contact information|kontaktinformasjon)(?:\s|$)',n['text'],re.I)]
    return parser.links


def entity_contacts(page,data,units=()):
    """Do not inherit another regional company's contacts from a shared site.

    A postal block outside all registered target/subunit addresses is unresolved,
    not proof of a new office. Regional pages must match a registered locality.
    No registry email or phone is returned by this function.
    """
    candidates=contact_links(page);addresses=[data.get(k) or {} for k in ('forretningsadresse','postadresse')]
    addresses += [u.get('address') or u.get('beliggenhetsadresse') or {} for u in units if isinstance(u,dict)]
    codes={str(a['postnummer']) for a in addresses if a.get('postnummer')}
    places={_normal(a[k]) for a in addresses for k in ('kommune','poststed') if a.get(k)}
    scopes,text_scopes=_contact_scopes(page,include_text=True);out=[];held=[];literal_scopes={}
    # Exact legal-name/address imprints can be plain paragraphs in simple sites.
    full_name=_normal(data.get('navn',''))
    for index,p in enumerate(page.paragraphs):
        if full_name and _normal(p)==full_name:
            text_scopes.append({'tag':'legal_imprint','text':' '.join(page.paragraphs[index:index+5])})
    for scope in text_scopes:
        text=scope['text']
        found=[('email',m.group(0),m.group(0)) for m in re.finditer(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,}",text)]
        for match in re.finditer(r'\b(?:Tel(?:efon)?|Tlf|Phone|Mobil)\s*:?[ \t]*(\+?[0-9 () .-]{7,25})',text,re.I):
            value=match.group(1).strip().rstrip(' .-')
            if 7<=len(re.sub(r'\D','',value))<=15:found.append(('phone',value,match.group(0).strip()))
        for match in re.finditer(r'(?m)^[ \t]*(\+[0-9][0-9 () .-]{7,22})[ \t]*$',text):
            value=match.group(1).strip()
            if 8<=len(re.sub(r'\D','',value))<=15:found.append(('phone',value,value))
        for kind,value,label in found:
            item={'type':kind,'value':value,'label':label[:160],'source_url':page.url,'source_href':None,
                  'source_kind':'literal_visible_text','source_pointer':'visible company contact/footer or exact legal-imprint block'}
            candidates.append(item);literal_scopes[id(item)]=[[scope]]
    stem=re.sub(r' (as|asa|sti|nuf)$','',_normal(data.get('navn','')))
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
    for item in candidates:
        reason='regional staff page is not tied to a registered target locality' if regional else None
        observations=[]
        if not reason:
            for ancestry in literal_scopes.get(id(item),scopes.get(item['source_href'],[])):
                for node in reversed(ancestry):
                    if node['tag'] in {'a','span','strong','b','i','svg','path'}:continue
                    found=set(re.findall(r'(?<!\d)([0-9]{4})[ \t]+[A-ZÆØÅ][A-Za-zÆØÅæøåéü-]+',node['text']))
                    if found:
                        observations.append(found);break
            if codes and observations and not any(v and v<=codes for v in observations):
                reason='contact block contains a postal address outside the registered target/subunits; separate-entity ownership unresolved'
        if reason:held.append({'type':item['type'],'value':item['value'],'source_url':page.url,'reason':reason})
        else:out.append(item)
    # Formatting variants of the same phone/email are one contact fact.
    unique=[];seen=set()
    for item in out:
        v=item['value'].casefold() if item['type']=='email' else re.sub(r'\D','',item['value'])
        if item['type']=='phone' and v.startswith('00'):v=v[2:]
        if item['type']=='phone' and len(v)==8:v='47'+v
        key=(item['type'],v)
        if key not in seen:seen.add(key);unique.append(item)
    return unique[:CONTACT_LIMIT],held
