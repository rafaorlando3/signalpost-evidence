"""Legal contact-map identity from an explicitly embedded public CMS JSON literal.

No JavaScript execution, guessed endpoint, geocoding or identity inherited from
another marker. A registered host plus full own legal brand, exact marker name,
street and postcode must agree. Callers retain normal operator-conflict vetos.
"""
import json,re
from html.parser import HTMLParser
from urllib.parse import urlsplit
from business_identity import canonical,street_span,literal_span
from legal_name_identity import fold,literal_name


def contact_map_records(page):
    class Parts(HTMLParser):
        def __init__(self):super().__init__(convert_charrefs=True);self.ids=set();self.scripts=[];self.script=None
        def handle_starttag(self,tag,attrs):
            a=dict(attrs)
            if tag=='div' and a.get('id'):self.ids.add(a['id'])
            if tag=='script':self.script=[] if a.get('type','').casefold() in {'','text/javascript','application/javascript'} and not a.get('src') else None
        def handle_data(self,value):
            if self.script is not None:self.script.append(value)
        def handle_endtag(self,tag):
            if tag=='script' and self.script is not None:self.scripts.append(''.join(self.script));self.script=None
    p=Parts();p.feed(page.raw_html);out=[]
    pattern=r"new\s+edMap_\d+\(\s*\$\(\s*(['\"])#([A-Za-z0-9_-]{1,100})\1\s*\)\s*\[0\]\s*,\s*(\{)"
    for script_index,script in enumerate(p.scripts[:50]):
        if len(script)>2_000_000:continue
        for match in list(re.finditer(pattern,script))[:5]:
            if match[2] not in p.ids:continue
            try:obj,used=json.JSONDecoder().raw_decode(script[match.start(3):])
            except (ValueError,RecursionError):continue
            if not re.match(r'\s*\)\s*\)',script[match.start(3)+used:]):continue
            if not isinstance(obj,dict) or not isinstance(obj.get('options'),dict) or not isinstance(obj.get('markers'),list):continue
            for index,marker in enumerate(obj['markers'][:100]):
                if not isinstance(marker,dict) or not isinstance(marker.get('title'),str) or not isinstance(marker.get('html'),str):continue
                if not 1<=len(marker['title'])<=200 or len(marker['html'])>4000:continue
                # Parse only the map's literal display HTML, never arbitrary JS.
                from agent import Page
                snippet=Page(marker['html'],page.url)
                if not snippet.text or snippet.ld:continue
                out.append({'title':marker['title'],'text':snippet.text,'source_url':page.url,
                    'map_container_id':match[2],'script_index':script_index,
                    'json_pointer':'/markers/'+str(index),'literal_html':marker['html']})
    return out[:100]


def contact_map_identity(data,pages,compatible):
    if not pages or not compatible:return None
    home=pages[0][0];entry=canonical(home.url)
    declared=data.get('hjemmeside');declared=canonical(declared if isinstance(declared,str) and '://' in declared else 'https://'+declared) if isinstance(declared,str) and declared else None
    if not entry or not declared or urlsplit(entry).path not in ('','/home','/hjem','/index.html','/index.php'):return None
    host=(urlsplit(entry).hostname or '').removeprefix('www.')
    if host!=(urlsplit(declared).hostname or '').removeprefix('www.'):return None
    full=fold(data.get('navn',''))
    if len(full)<8 or not any(literal_name(v,data.get('navn','')) for v in [home.title,home.meta.get('og:site_name',''),*home.content_headings]):return None
    if any(not compatible(pg) for pg,_ in pages):return None
    eligible={canonical(pg.url):(pg,rsp) for pg,rsp in pages if canonical(pg.url) and (urlsplit(pg.url).hostname or '').removeprefix('www.')==host}
    reachable={entry:[]}
    for _ in range(2):
        for key,links in list(reachable.items()):
            if key not in eligible:continue
            for link in eligible[key][0].links:
                target=canonical(link['url'])
                if not link.get('third_party_context') and target in eligible and target not in reachable:
                    reachable[target]=links+[{'source_url':key,'target_url':target}]
    for key,(pg,rsp) in eligible.items():
        if key not in reachable or not re.search(r'/(?:contact[^/]*|kontakt[^/]*)(?:/|$)',urlsplit(key).path,re.I):continue
        for marker in contact_map_records(pg):
            if fold(marker['title'])!=full:continue
            from agent import Page,website_identity,site_operator_identity
            snippet=Page(marker['literal_html'],pg.url)
            if website_identity(str(data.get('organisasjonsnummer','')),snippet,data)=='conflict':continue
            if site_operator_identity(str(data.get('organisasjonsnummer','')),snippet,data).get('state') in {'different','unresolved'}:continue
            owner=literal_span(marker['text'],data.get('navn',''))
            if not owner or owner['start']!=0:continue
            for kind in ('forretningsadresse','postadresse'):
                address=data.get(kind) or {};postcode=address.get('postnummer')
                for street in address.get('adresse') or []:
                    st=street_span(marker['text'],street)
                    if not st or not postcode or st['start']<owner['end']:continue
                    if not re.fullmatch(r'\W*',marker['text'][owner['end']:st['start']]):continue
                    local=marker['text'][st['end']:st['end']+70]
                    postal=re.search(r'(?<!\d)'+re.escape(str(postcode))+r'(?!\d)',local)
                    if not postal:continue
                    return {'method':'registered_domain_exact_legal_contact_map',
                        'registered_name':data.get('navn'),'organisation_number':data.get('organisasjonsnummer'),
                        'entry_url':home.url,'source_url':pg.url,'declared_registry_url':declared,
                        'marker':marker,'address_kind':kind,'registered_street':street,'registered_postcode':postcode,
                        'literal_spans':[owner,st,{'start':st['end']+postal.start(),'end':st['end']+postal.end(),'text':postal[0]}],
                        'links':reachable[key],
                        'scope':'one exact legally named contact-map record on registered, fully branded own site; other map entities never inherited; declared JSON display data, not rendered-page verification'}
    return None
