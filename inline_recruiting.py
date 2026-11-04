"""Literal role blocks on an already visited, legally identified own careers page.

No requests, scripts, date inference or application actions. A direct privacy
link must establish the full legal owner independently of the recruiting copy.
"""
import datetime as dt
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlunsplit


ROLE = re.compile(r'\b(?:utvikler|developers?|engineers?|ingeniør|account executives?|'
                  r'analytiker|rådgiver|konsulent|selger|salgssjef|montør|sjåfør|'
                  r'mekaniker|tekniker|servitør|kokk|sykepleier|barnehagelærer|'
                  r'designers?|prosjektleder|avdelingsleder|driftsleder)\b', re.I)
BAD = re.compile(r'åpen\s+søknad|åpne\s+søknader|spontan|open applications?|talent\s+pool|'
                 r'på vegne av|for vår kunde|for våre kunder|on behalf of|our client|'
                 r'fristen er utløpt|stillingen er (?:besatt|avsluttet)|'
                 r'positions? (?:is |are )?(?:filled|closed)', re.I)
VOID = {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}


def canonical(url):
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, p.path.rstrip('/'), p.query, ''))


class Blocks(HTMLParser):
    def __init__(self, raw):
        super().__init__(convert_charrefs=True)
        self.stack = []; self.heading = None; self.active = None; self.out = []
        self.feed(raw)
        self.finish()

    def finish(self):
        if self.active:
            self.active['body'] = ' '.join(' '.join(self.active.pop('parts')).split())
            self.out.append(self.active)
            self.active = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        context = ' '.join(attrs.get(k, '') for k in ('class','id','aria-label'))
        blocked = bool(self.stack and self.stack[-1][1]) or tag in {
            'head','nav','header','footer','aside','form','script','style','noscript','dialog'} or bool(
            re.search(r'customer|testimonial|partner|agency|site-credit|comment', context, re.I))
        if tag not in VOID:
            self.stack.append((tag, blocked))
        if re.fullmatch(r'h[2-6]', tag) and not blocked:
            level = int(tag[1])
            if self.active and level <= self.active['level']:
                self.finish()
            self.heading = {'tag':tag, 'level':level, 'parts':[]}

    def handle_data(self, text):
        if self.stack and self.stack[-1][1]:
            return
        if self.heading:
            self.heading['parts'].append(text)
        elif self.active:
            self.active['parts'].append(text)

    def handle_endtag(self, tag):
        if self.heading and self.heading['tag'] == tag:
            h = self.heading; self.heading = None
            title = ' '.join(' '.join(h['parts']).split())
            if 3 <= len(title) <= 160 and ROLE.search(title) and not BAD.search(title):
                self.finish()
                self.active = {'title':title, 'level':h['level'], 'parts':[]}
            elif self.active:
                self.active['parts'].append(title)
        for i in range(len(self.stack)-1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break


def candidates(pages, data):
    """Return role records and the exact existing source chain that supports them."""
    from agent import website_identity, site_operator_identity
    from attribution import legal_stem, normal
    name = data.get('navn', ''); org = str(data.get('organisasjonsnummer', ''))
    stem = legal_stem(name)
    if len(stem) < 5:
        return []
    identities = []
    for page, rsp in pages:
        if (rsp.get('status')!='available' or rsp.get('status_code')!=200
                or rsp.get('delegated_from_verified_careers') or not rsp.get('identity_verified')):
            continue
        # A full legal name next to its own ID on a linked legal page. A
        # customer's/sponsor's number elsewhere cannot establish the operator.
        if not re.search(r'/(?:personvern[^/]*|privacy[^/]*|imprint|legal)(?:/|$)', urlsplit(page.url).path, re.I):
            continue
        if website_identity(org, page, data) != 'exact':
            continue
        text = normal(page.text)
        full = normal(name)
        if not re.search(r'(?<!\w)'+re.escape(full)+r'(?!\w).{0,90}?(?<!\d)'+r'\s*'.join(org)+r'(?!\d)', text):
            continue
        identities.append((page, rsp))
    out = []
    for page, rsp in pages:
        if (rsp.get('status')!='available' or rsp.get('status_code')!=200
                or not rsp.get('identity_verified') or rsp.get('delegated_from_verified_careers')):
            continue
        path = urlsplit(page.url).path
        if not re.search(r'(?:^|[/_-])(?:karriere|careers?|jobb|jobs?|stillinger|team)(?:$|[/_-])', path, re.I):
            continue
        if len(page.raw_html) > 500_000:
            continue
        body = ' '.join(page.body_parts)
        if not re.search(r'utlyste stillinger|ledige stillinger|current vacancies|current openings', body, re.I):
            continue
        if website_identity(org, page, data) == 'conflict' or site_operator_identity(org, page, data)['state'] in {'different','unresolved'}:
            continue
        linked = {canonical(x['url']) for x in page.links if not x.get('third_party_context')}
        legal = next(((pg, r) for pg, r in identities if urlsplit(pg.url).netloc == urlsplit(page.url).netloc and canonical(pg.url) in linked), None)
        if not legal:
            continue
        for block in Blocks(page.raw_html).out[:40]:
            text = block['body']; folded = normal(text)
            if not 180 <= len(text) <= 20_000 or BAD.search(text):
                continue
            if not re.search(r'(?<!\w)'+re.escape(stem)+r'(?!\w)', folded):
                continue
            if not (re.search(r'\b(?:vi (?:søker|ser etter)|we are (?:hiring|looking for)|nå søker vi)\b', text, re.I)
                    or re.search(r'\bvi i '+re.escape(stem)+r' søker\b', folded)):
                continue
            kinds = [bool(re.search(pattern, text, re.I)) for pattern in [
                r'kvalifikasjoner|erfaring|qualifications|experience',
                r'arbeidsoppgaver|viktigste oppgaver|ansvarsområde|responsibilities|your role',
                r'vi tilbyr|du får|what we offer|hva du får']]
            if sum(kinds) < 2:
                continue
            invitation = re.search(r'\bsend(?:es)?\b.{0,100}?(?:\bCV\b|søknad|application)', text, re.I)
            if not invitation:
                continue
            deadline = None
            if re.search(r'søknadsfrist|application deadline', text, re.I):
                m = re.search(r'(?:søknadsfrist|application deadline)\s*:?\s*(\d{1,2})[./](\d{1,2})[./](\d{4})(?!\d)', text, re.I)
                if not m:
                    continue
                try:
                    deadline = dt.date(int(m[3]), int(m[2]), int(m[1]))
                    if deadline < dt.date.fromisoformat(rsp['retrieved_at'][:10]):
                        continue
                except ValueError:
                    continue
            item = {'title':block['title'], 'date':None, 'url':page.url,
                'hiring_organisation':name, 'valid_through':deadline.isoformat() if deadline else None,
                'status':'published first-party vacancy invitation; application acceptance not tested',
                'publication_date_state':'not_stated', 'application_url':page.url,
                'discovery':'linked_inline_first_party_roles',
                'employer_binding':{'method':'directly linked exact legal owner and scoped own-brand role',
                    'company_identity_source':legal[0].url, 'role_source':page.url,
                    'target_organisation_number':org, 'legal_name':name,
                    'literal_heading':block['title'], 'literal_invitation':invitation[0],
                    'deadline_basis':'explicit role-block deadline' if deadline else 'not stated; not inferred'}}
            out.append({'item':item, 'response':rsp, 'identity_response':legal[1]})
    # Repeated/legacy own-site role copies are one role, not extra employers.
    unique = {}
    for record in out:
        unique.setdefault(role_key(record['item']), record)
    return list(unique.values())


def role_key(item):
    from attribution import normal
    title = re.sub(r'\b(executive|developer|engineer|designer)s\b', r'\1', normal(item.get('title','')))
    return (urlsplit(item.get('url','')).netloc.casefold().removeprefix('www.'), title)
