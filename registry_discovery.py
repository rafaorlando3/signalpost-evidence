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
