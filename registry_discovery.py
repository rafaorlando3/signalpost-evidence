"""Alternative URL leads from official entity records. Leads are not identity proof."""
from urllib.parse import urlsplit, urlunsplit

FREE_EMAIL = {'gmail.com', 'hotmail.com', 'outlook.com', 'yahoo.com', 'online.no',
              'icloud.com', 'live.no', 'live.com', 'msn.com', 'proton.me', 'protonmail.com'}


def web_url(value):
    if not isinstance(value, str) or not value.strip(): return None
    value = value.strip()
    try:
        p = urlsplit(value if '://' in value else 'https://' + value)
        if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password or p.port not in (None, 80, 443):
            return None
        return urlunsplit((p.scheme, p.netloc, p.path, p.query, ''))
    except ValueError:
        return None


def host_key(url):
    return (urlsplit(url).hostname or '').casefold().removeprefix('www.')


def registry_candidates(org, data, units):
    leads = []
    if data.get('hjemmeside'):
        leads.append((data['hjemmeside'], 'entity_website'))
    unit_sites = {u['hjemmeside'] for u in units if u.get('overordnetEnhet') == org
                  and isinstance(u.get('hjemmeside'), str) and u['hjemmeside']}
    if len(unit_sites) == 1:
        leads.append((next(iter(unit_sites)), 'unique_workplace_website'))
    email = data.get('epostadresse') or ''
    if isinstance(email, str) and '@' in email:
        domain = email.rsplit('@', 1)[1].strip().casefold()
        if domain not in FREE_EMAIL:
            leads.append((domain, 'email_domain'))
    seen = set(); result = []
    for value, origin in leads:
        url = web_url(value)
        if not url or host_key(url) in seen: continue
        seen.add(host_key(url))
        result.append({'url': url, 'origin': origin})
    return result


def name_domain_candidates(data):
    """At most two heuristic URL leads; never website ownership evidence.

    Used only after official links/search did not establish a site. Norwegian
    commercial name transliterations are generic, never company allowlists.
    """
    import re,unicodedata
    name=str(data.get('navn') or '').casefold().translate(str.maketrans({'ø':'o','æ':'ae','å':'a'}))
    name=''.join(c for c in unicodedata.normalize('NFKD',name) if not unicodedata.combining(c))
    words=re.findall(r'[a-z0-9]+',name)
    while words and words[-1] in {'as','asa','nuf','enk','ans','da','sa','ba','brl','sti','co'}:words.pop()
    if not words or len(words)>5 or any(w in {'holding','holdings','invest','eiendom','borettslag','sameiet','sameie','boligsameie'} for w in words):return []
    compact=''.join(words)
    if not 6<=len(compact)<=55 or compact.isdigit():return []
    # Dotted initials are commonly one component in a branded domain (A.B.
    # Example -> ab-example), not a separate hyphen between every letter.
    grouped=list(words)
    initials=[]
    while grouped and len(grouped[0])==1:initials.append(grouped.pop(0))
    if len(initials)>=2:grouped=[''.join(initials),*grouped]
    else:grouped=words
    hosts=[compact+'.no',('-'.join(grouped)+'.no') if len(grouped)>1 else compact+'.com']
    return list(dict.fromkeys('https://'+h+'/' for h in hosts))[:2]


def industry_city_candidates(data):
    """Two untrusted category/locality URL leads, never ownership evidence.

    Marketing slugs use a generic Norwegian service category and the official
    municipality. No company, organisation number or city-specific host list.
    """
    import re,unicodedata
    # NACE49.420 is moving services. The public-facing service-category name
    # is not necessarily the company's legal name, so legal identity is still
    # established independently after the page is fetched.
    service={'49.420':'flyttebyra'}.get((data.get('naeringskode1') or {}).get('kode'))
    city=(data.get('forretningsadresse') or {}).get('kommune')
    if not service or not isinstance(city,str):return []
    city=city.casefold().translate(str.maketrans({'ø':'o','æ':'ae','å':'a'}))
    city=''.join(c for c in unicodedata.normalize('NFKD',city) if not unicodedata.combining(c))
    city=re.sub(r'[^a-z0-9]+','-',city).strip('-')
    if not 2<=len(city)<=45:return []
    return ['https://'+service+'-'+city+'.no/','https://'+service+city.replace('-','')+'.no/']
