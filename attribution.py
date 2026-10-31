"""Conservative legal-entity attribution. No registry contact claims or paid APIs."""
import re
from urllib.parse import urljoin, urlsplit, urlunsplit


def normal(value):
    return re.sub(r'[^\w]+', ' ', str(value).casefold()).strip()


def legal_stem(value):
    return re.sub(r'\s+(?:as|asa|sti|nuf)$', '', normal(value))


def mentions(value, name):
    stem = legal_stem(name)
    return bool(len(stem) >= 3 and re.search(r'(?<!\w)' + re.escape(stem) + r'(?!\w)', normal(value)))


def objects(value):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from objects(item)
    elif isinstance(value, list):
        for item in value:
            yield from objects(item)


def types(obj):
    t = obj.get('@type', [])
    return set(v for v in (t if isinstance(t, list) else [t]) if isinstance(v, str))


def own_organization(obj, data):
    """Only this node's identifiers, never a parent's/child's nested identifier."""
    identifiers = [obj.get('taxID'), obj.get('vatID')]
    props = obj.get('identifier', [])
    for prop in props if isinstance(props, list) else [props]:
        if isinstance(prop, dict) and normal(prop.get('propertyID', '')).replace(' ', '') in {
                'organisasjonsnummer', 'organisasjonsnr', 'orgnr', 'noorgnr',
                'organizationnumber', 'organisationnumber'}:
            identifiers.append(prop.get('value'))
    numbers = set()
    for value in identifiers:
        if not isinstance(value, (str, int)):
            continue
        match = re.fullmatch(r'(?:NO\s*)?([0-9]{3}[.\s]?[0-9]{3}[.\s]?[0-9]{3})(?:\s*MVA)?', str(value).strip(), re.I)
        if match:
            numbers.add(re.sub(r'\D', '', match[1]))
    return bool(numbers == {str(data.get('organisasjonsnummer'))})


def group_site_reason(page, data):
    """A subsidiary footer is not proof that a differently branded group is its site.

    Applied to the entry page only; a stray group link or article is insufficient.
    An explicit scoped WebSite operator is handled separately by the caller.
    """
    description = page.description
    collective = re.search(r'\b(?:the|our|entire|whole)\s+group\b|\b(?:konsernet|konsernets|hele gruppen|vårt konsern)\b|\b(?:group|gruppen)\s+(?:consists|comprises|includes|employs)\b', description, re.I)
    brand = page.meta.get('og:site_name') or (page.content_headings[0] if page.content_headings else page.title)
    if collective and brand.strip() and not mentions(brand, data.get('navn', '')):
        return 'entry page explicitly describes a group under another brand; a subsidiary footer does not establish its own site'
    return None


def canonical_profile(url):
    try:
        p = urlsplit(url)
        if p.scheme not in {'https', 'http'} or p.username or p.password or p.port not in (None, 80, 443):
            return None
        host = (p.hostname or '').casefold().removeprefix('www.')
        if host not in {'linkedin.com', 'facebook.com', 'youtube.com', 'instagram.com', 'twitter.com', 'x.com', 'vimeo.com', 'tiktok.com'}:
            return None
        path = p.path.rstrip('/')
        if not path or re.search(r'/(?:share|sharer|shareArticle|sharing|intent|plugins|widgets|login|watch|home|search)(?:[/.]|$)', path, re.I):
            return None
        if host == 'linkedin.com' and not re.fullmatch(r'/company/[^/]+', path):
            return None
        if host == 'instagram.com' and not re.fullmatch(r'/(?!p$|reels?$|stories$|explore$)[^/]+', path, re.I):
            return None
        if host in {'x.com', 'twitter.com'} and not re.fullmatch(r'/[^/]+', path):
            return None
        if host == 'facebook.com' and (re.search(r'/(?:posts|videos|photos|events|reel|story.php|photo.php)(?:/|$)', path) or
                                      (p.query and not (path == '/profile.php' and re.fullmatch(r'id=\d+', p.query)))):
            return None
        if host in {'youtube.com', 'tiktok.com'} and not re.fullmatch(r'/(?:@[^/]+|(?:channel|c|user)/[^/]+)', path):
            return None
        return urlunsplit(('https', host, path, p.query if path == '/profile.php' else '', ''))
    except ValueError:
        return None


def same_public_host(left, right):
    try:
        p,q=urlsplit(left),urlsplit(right)
        return (p.scheme in {'http','https'} and q.scheme in {'http','https'}
                and not p.username and not p.password and p.port in (None,80,443)
                and bool(p.hostname) and p.hostname.casefold().removeprefix('www.')==
                    (q.hostname or '').casefold().removeprefix('www.'))
    except (ValueError,TypeError):
        return False


def declared_profiles(pages, data):
    """sameAs must be asserted directly by the exact legal entity, not any org."""
    found = {}
    for page, response in pages:
        for obj in objects(page.ld):
            if not types(obj) & {'Organization', 'Corporation', 'LocalBusiness'}:
                continue
            # On an already identity-checked site, an exact legal name plus
            # its own site URL is also a scoped ownership declaration.
            node_url=obj.get('url')
            named_site=(legal_stem(obj.get('legalName') or obj.get('name',''))==legal_stem(data.get('navn',''))
                        and bool(legal_stem(data.get('navn','')))
                        and isinstance(node_url,str) and same_public_host(node_url,page.url))
            if not own_organization(obj, data) and not named_site:
                continue
            values = obj.get('sameAs', [])
            for url in values if isinstance(values, list) else [values]:
                profile = canonical_profile(url) if isinstance(url, str) else None
                if profile:
                    found.setdefault(profile, []).append(response)
    return found


def profile_identity(page, data, site_url):
    """Public destination must identify the legal target and backlink to its site.

    A name or handle alone never suffices. Blocked destinations stay unresolved.
    """
    for obj in objects(page.ld):
        if (types(obj) & {'Organization', 'Corporation', 'LocalBusiness'} and own_organization(obj, data)
                and isinstance(obj.get('url'),str) and canonical_profile(obj['url'])==canonical_profile(page.url)):
            return 'destination_exact_organisation_number'
    title = page.meta.get('og:title') or page.title
    if not mentions(title, data.get('navn', '')):
        return None
    target = (urlsplit(site_url).hostname or '').casefold().removeprefix('www.')
    for link in page.links:
        try:
            parsed = urlsplit(link['url'])
            if parsed.scheme in {'https', 'http'} and not parsed.username and not parsed.password and (parsed.hostname or '').casefold().removeprefix('www.') == target:
                return 'destination_name_and_verified_site_backlink'
        except ValueError:
            pass
    return None


def article_attribution(obj, page, data):
    """Real post content must concern the target, not just inherit a footer."""
    for key in ('about', 'mainEntity'):
        values = obj.get(key, [])
        for value in values if isinstance(values, list) else [values]:
            if isinstance(value, dict) and own_organization(value, data):
                return 'article_subject_exact_organisation_number'
    content = ' '.join(str(obj.get(k) or '') for k in ('headline', 'title', 'articleBody', 'description'))
    content += ' ' + ' '.join(page.article_parts)
    # Navigation/footer and the site's generic description are deliberately absent.
    if mentions(content, data.get('navn', '')):
        return 'target_name_in_post_content'
    # A real first-person announcement can omit the legal name. Resolve its
    # publisher to the exact named legal entity on the identity-checked site,
    # then require an actual announcement in the article body. A publisher
    # alone, generic industry prose, or an explicit other subject is not enough.
    if not obj.get('about'):
        publisher=obj.get('publisher')
        reference=publisher.get('@id') if isinstance(publisher,dict) else publisher
        publishers=[publisher] if isinstance(publisher,dict) else []
        if isinstance(reference,str):
            publishers += [node for node in objects(page.ld)
                           if isinstance(node.get('@id'),str)
                           and urljoin(page.url,node['@id'])==urljoin(page.url,reference)]
        exact_publisher=any(isinstance(node,dict) and
            (own_organization(node,data) or
             (legal_stem(node.get('legalName') or node.get('name',''))==legal_stem(data.get('navn',''))
              and isinstance(node.get('url'),str) and same_public_host(node['url'],page.url)))
            for node in publishers)
        announcement=re.search(r'\b(?:we\s+(?:(?:have\s+)?(?:opened|launched|expanded|acquired|introduced)|now\s+offer)|'
                               r'vi\s+(?:har\s+(?:åpnet|lansert|utvidet)|tilbyr\s+(?:nå|no)|lanserer|åpner))\b',content,re.I)
        if exact_publisher and announcement:
            return 'exact_entity_publisher_and_first_person_announcement'
    return None
