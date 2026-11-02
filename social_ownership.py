"""Recover company-declared social profiles using scoped primary-source evidence.

A profile name or footer link alone is insufficient. A scoped company follow
statement/social control plus exact legal/trade-name identity is required. This
is an ownership declaration by the identity-checked company, not independent
verification of access to the social account. Contradictory Person/other-company
sameAs assertions veto these fallbacks.
"""
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, unquote
import re
import unicodedata
import datetime as dt
from attribution import canonical_profile, normal, objects, own_organization, types, ORGANIZATION_TYPES, organization_numbers

VOID={'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}
EXCLUDED=re.compile(r'sponsor|partner|customer|testimonial|author|agency|webdesign|site.credit|powered.by|theme.credit|shar(?:e|ing)',re.I)
SOCIAL=re.compile(r'\b(?:social|socials|sosial|sosiale|follow|følg)\b',re.I)
FOLLOW=re.compile(r'\b(?:follow\s+(?:us|our)|følg(?:e)?\s+(?:oss|våre)|følg\s+gjerne\s+.{0,35}\bvåre|suivez.nous)\b',re.I)
POSSESSIVE_PROFILE=re.compile(r'\b(?:vår(?:e)?\s+(?:facebook|instagram|linkedin|youtube|tiktok)\s+(?:side|profil|konto|kanal)|our\s+(?:facebook|instagram|linkedin|youtube|tiktok)\s+(?:page|profile|account|channel))\b',re.I)


def folded(value):
    value=str(value).casefold().translate(str.maketrans({'ø':'o','æ':'ae','ł':'l'}))
    return ''.join(c for c in unicodedata.normalize('NFKD',value) if not unicodedata.combining(c))


def identifier(value):
    return re.sub(r'[^a-z0-9]','',folded(value))


def legal_words(value):
    words=normal(folded(value)).split()
    while words and words[0] in {'as','asa','nuf'}:words.pop(0)
    while words and words[-1] in {'as','asa','nuf','sti'}:words.pop()
    return ' '.join(words)


def registered_historical_names(data):
    """Dated names on the current entity record, never another org's alias."""
    org=str(data.get('organisasjonsnummer',''))
    records=data.get('historiskeNavn')
    if not re.fullmatch(r'[0-9]{9}',org) or not isinstance(records,list):return []
    result=[]
    for item in records[:30]:
        if not isinstance(item,dict) or str(item.get('organisasjonsnummer',org))!=org:continue
        name=item.get('navn');start=item.get('fraDato');end=item.get('tilDato')
        if not isinstance(name,str) or not isinstance(start,str) or not isinstance(end,str):continue
        try:
            if dt.date.fromisoformat(start[:10])>dt.date.fromisoformat(end[:10]):continue
        except ValueError:continue
        if len(identifier(name))>=5:
            result.append({'name':name,'valid_from':start,'valid_until':end,
                           'organisation_number':org,'registry_field':'historiskeNavn'})
    return result


def company_labels(data,page):
    name=data.get('navn','');legal=legal_words(name)
    labels={identifier(name):('exact_legal_name',name),identifier(legal):('exact_legal_name',name)}
    # Keep the entire former legal name, including regional/form qualifiers.
    # It is a discovery/matching label only when the current site declares it.
    for historical in registered_historical_names(data):
        labels.setdefault(identifier(historical['name']),('exact_registered_historical_name',historical['name']))
    # A trade-name must include the entire legal stem, on the already verified
    # homepage. Never drop a regional/legal differentiator to match a group.
    fragments=[page.meta.get('og:site_name','')]
    fragments+=re.split(r'\s+[|–—]\s*|\s+-\s+|\|',page.title)
    for fragment in fragments:
        clean=normal(folded(fragment));words=clean.split()
        if (legal and len(legal)>=5 and len(words)<=6 and
                re.search(r'(?<!\w)'+re.escape(legal)+r'(?!\w)',clean) and
                not re.search(r'\b(group|gruppen|konsern|konsernet|holding|holdings)\b',clean) and
                '.' not in fragment and '/' not in fragment):
            labels[identifier(fragment)]=('explicit_site_trade_name',fragment)
    registered=data.get('hjemmeside')
    if isinstance(registered,str):
        try:
            host=(urlsplit(registered if '://' in registered else 'https://'+registered).hostname or '').removeprefix('www.')
            current=(urlsplit(page.url).hostname or '').removeprefix('www.')
            if host==current:
                labels[identifier(host)]=('exact_registered_entity_domain',host)
        except ValueError:pass
    return {key:value for key,value in labels.items() if len(key)>=5}


def profile_identifier(profile):
    p=urlsplit(profile);parts=[unquote(s) for s in p.path.split('/') if s]
    host=p.hostname
    if host=='facebook.com' and len(parts)==3 and parts[0]=='pages':value=parts[1]
    elif host=='linkedin.com' and len(parts)==2 and parts[0]=='company':value=parts[1]
    elif host=='youtube.com' and len(parts)==2 and parts[0] in {'user','c'}:value=parts[1]
    elif len(parts)==1 and parts[0]!='profile.php':value=parts[0].lstrip('@')
    else:return None
    if host=='facebook.com':value=re.sub(r'-\d{8,}$','',value)
    return identifier(value)


class Controls(HTMLParser):
    def __init__(self,text,url):
        super().__init__(convert_charrefs=True);self.url=url;self.stack=[];self.links=[];self.anchor=None;self.skip=0
        self.feed(text)

    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs);context=' '.join((attrs.get(k) or '') for k in ('class','id','aria-label','title','itemprop','rel'))
        from site_discovery import scoped_context
        context=scoped_context(tag,context)
        comment_block=tag in {'article','div','section','ol','ul','li'} and any(re.fullmatch(r'(?:comments?(?:[-_][\w]+)?|wp-block-post-comments(?:[-_][\w]+)?)',token,re.I) for token in ((attrs.get('class') or '')+' '+(attrs.get('id') or '')).split())
        excluded=(any(n['excluded'] for n in self.stack) or bool(EXCLUDED.search(context)) or comment_block)
        semantic_context=re.sub(r'(?<=[a-z])(?=[A-Z])',' ',context).replace('_',' ')
        node={'tag':tag,'context':normal(semantic_context),'excluded':excluded,'text':'','links':[]}
        if tag not in VOID:self.stack.append(node)
        if tag in {'script','style','noscript'}:self.skip+=1
        if tag=='a' and attrs.get('href') and not self.skip:
            try:destination=urljoin(self.url,attrs['href'])
            except ValueError:self.anchor=None;return
            profile=canonical_profile(destination)
            self.anchor={'profile':profile,'href':destination,
                         'excluded':excluded,'label':attrs.get('aria-label') or attrs.get('title') or '',
                         'rel':(attrs.get('rel') or '').split(),'scopes':self.stack[-7:],
                         'chrome':any(n['tag'] in {'header','nav','footer'} for n in self.stack)}
            if profile:
                self.links.append(self.anchor)
                for ancestor in self.stack[-7:]:ancestor['links'].append(self.anchor)
        if tag=='div' and 'fb-page' in (attrs.get('class') or '').split() and attrs.get('data-href'):
            try:destination=urljoin(self.url,attrs['data-href'])
            except ValueError:destination=''
            profile=canonical_profile(destination)
            if profile:self.links.append({'profile':profile,'href':destination,'excluded':excluded,'label':'Facebook page widget','rel':[],'scopes':self.stack[-7:],'chrome':False,'widget':True})
        if tag=='img' and self.anchor:
            self.anchor['label']+=' '+(attrs.get('alt') or '')
            if EXCLUDED.search(attrs.get('alt') or ''):self.anchor['excluded']=True

    def handle_endtag(self,tag):
        if tag in {'script','style','noscript'}:self.skip=max(0,self.skip-1)
        if tag=='a':self.anchor=None
        for i in range(len(self.stack)-1,-1,-1):
            if self.stack[i]['tag']==tag:
                del self.stack[i:];break

    def handle_data(self,value):
        if self.skip:return
        if self.anchor:self.anchor['label']+=' '+value
        for node in self.stack[-7:]:
            if len(node['text'])<1600:node['text']+=' '+value[:1600-len(node['text'])]


def conflicting_profiles(pages,data):
    blocked={}
    for page,response in pages:
        for obj in objects(page.ld):
            kind=types(obj)
            values=obj.get('sameAs',[])
            if not isinstance(values,list):values=[values]
            if 'Person' in kind:
                reason='explicit Person sameAs; not a corporate account'
            elif kind & ORGANIZATION_TYPES and not own_organization(obj,data):
                # Only explicit different corporate identifiers/legal names are
                # a negative proof; an unknown publisher label is not one.
                legal=obj.get('legalName') or obj.get('name')
                foreign_id=bool(organization_numbers(obj))
                if foreign_id or (legal and legal_words(legal)!=legal_words(data.get('navn',''))):
                    reason='sameAs declared by another legal entity; shared/group account unresolved'
                else:continue
            else:continue
            for value in values:
                profile=canonical_profile(value) if isinstance(value,str) else None
                if profile:blocked[profile]=reason
    return blocked


def asserted_profiles(pages,data):
    """Return explicit site declarations only; every recovered profile has proof."""
    found={};blocked=conflicting_profiles(pages,data)
    if not pages:return found,blocked
    # Labels are bound to the entry's identity-checked business presentation,
    # never a linked agency page, article title or a search result.
    labels=company_labels(data,pages[0][0])
    for page,response in pages:
        controls=Controls(response.get('text',''),page.url)
        for link in controls.links:
            profile=link['profile'];handle=profile_identifier(profile)
            if link['excluded'] or profile in blocked or handle not in labels:continue
            basis,label=labels[handle];proof=None;excerpt=None
            historical=None
            if basis=='exact_registered_historical_name':
                historical=next((h for h in registered_historical_names(data) if h['name']==label),None)
                try:
                    if not historical or dt.date.fromisoformat(historical['valid_until'][:10])>dt.date.fromisoformat(response['retrieved_at'][:10]):continue
                except (KeyError,ValueError,TypeError):continue
            if link.get('widget') and basis=='exact_registered_entity_domain':
                proof='explicit_page_widget_and_registered_domain_profile_identifier';excerpt='div.fb-page[data-href] '+link['href']
            if 'me' in link['rel']:
                proof='rel_me_and_exact_entity_identifier';excerpt=link['label']
            for scope in link['scopes']:
                if scope['tag'] in {'a','html','head','body'} or scope['excluded']:continue
                text=re.sub(r'\s+',' ',scope['text']).strip()
                if FOLLOW.search(text):
                    proof='explicit_follow_statement_and_exact_entity_identifier';excerpt=text
                    break
                declaration=POSSESSIVE_PROFILE.search(text)
                if declaration:
                    proof='explicit_company_profile_reference_and_exact_entity_identifier'
                    excerpt=text[max(0,declaration.start()-180):declaration.end()+180]
                    break
                branded_social=(len(text)<900 and SOCIAL.search(normal(text)) and
                    bool(re.search(r'(?<!\w)'+re.escape(legal_words(data.get('navn','')))+r'(?!\w)',normal(folded(text)))))
                if SOCIAL.search(scope['context']) or re.search(r'\bso\s*me\b',scope['context']) or branded_social:
                    proof='explicit_social_control_and_exact_entity_identifier';excerpt=scope['context']+' '+text
                    break
                peers={urlsplit(peer['profile']).hostname for peer in scope['links']
                       if peer['profile'] and not peer['excluded'] and peer['profile'] not in blocked
                       and profile_identifier(peer['profile']) in labels}
                if link['chrome'] and len(peers)>=2:
                    proof='corporate_navigation_matching_profiles_on_multiple_networks';excerpt=text or scope['context']
            if proof:
                record={'response':response,'proof':{'method':proof,'legal_name':data.get('navn'),
                    'identity_basis':basis,'asserted_company_label':label,'profile_identifier':handle,
                    'source_url':page.url,'source_href':link['href'],'context_excerpt':(excerpt or link['label'])[:700],
                    'verification_scope':'explicit company declaration plus entity matching; destination access not independently verified'}}
                if historical:record['proof']['historical_name_binding']=historical
                found.setdefault(profile,[]).append(record)
    return found,blocked
