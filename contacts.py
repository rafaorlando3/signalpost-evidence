"""Literal contact links from identity-verified company pages; never guessed."""
import re
from urllib.parse import unquote, urlsplit


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
    return found[:10]
