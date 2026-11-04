"""Literal publication dates in narrowly scoped CMS metadata blocks.

No URL-date, copyright, event, lastmod or modification inference. All output
keeps the actual labelled source text and selector for evidence review.
"""
import datetime as dt
import re
from html.parser import HTMLParser

VOID={'meta','link','img','br','input','hr','source','wbr','area','base','col','embed','param','track'}
MONTHS={name:index for index,names in enumerate([
    ('january','januar'),('february','februar'),('march','mars'),('april',),('may','mai'),('june','juni'),
    ('july','juli'),('august',),('september',),('october','oktober'),('november',),('december','desember')],1) for name in names}


def literal_date(text):
    text=re.sub(r'\s+',' ',text).strip()
    m=re.fullmatch(r'(?:Published on\s+)?([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?[,]?\s+(\d{4})',text,re.I)
    if m:parts=(int(m[3]),MONTHS.get(m[1].casefold(),0),int(m[2]))
    else:
        m=re.fullmatch(r'(\d{1,2})\.?\s+([A-Za-z]+)\s+(\d{4})',text,re.I)
        if m:parts=(int(m[3]),MONTHS.get(m[2].casefold(),0),int(m[1]))
        else:
            m=re.fullmatch(r'(\d{1,2})([/.])(\d{1,2})\2(\d{4})',text)
            if not m:return None
            parts=(int(m[4]),int(m[3]),int(m[1]))
    try:return dt.date(*parts).isoformat()
    except ValueError:return None


class Markup(HTMLParser):
    def __init__(self,text):
        super().__init__(convert_charrefs=True);self.stack=[];self.blocks=[];self.skip=0;self.heading_seen=False
        self.feed(text)

    def handle_starttag(self,tag,attrs):
        a=dict(attrs);classes=set((a.get('class') or '').split());tokens=classes|set((a.get('id') or '').split())
        excluded=tag in {'head','nav','footer','aside','form','dialog'} or any(n['excluded'] for n in self.stack)
        excluded=excluded or any(re.search(r'^(?:comments?|news-preview|related-posts|post-preview)(?:[-_]|$)',token,re.I) for token in tokens)
        kind=None
        if not excluded:
            if tag=='span' and {'meta-date','date','published'}<=classes and not classes&{'updated','modified','rich-snippet-hidden'}:kind='span.meta-date.date.published'
            elif tag=='div' and 'publish-date--article' in classes:kind='div.publish-date--article; Published on'
            elif tag=='p' and 'postInfoText' in classes:kind='p.postInfoText'
            elif tag=='span' and 'meta-text' in classes and any('post-date' in n['classes'] for n in self.stack):kind='li.post-date span.meta-text'
            elif (tag=='div' and 'tag-date-container' in classes and not self.heading_seen
                  and any(n['tag']=='main' for n in self.stack)):
                kind='main div.tag-date-container before article heading'
        if tag=='h1' and not excluded:self.heading_seen=True
        node={'tag':tag,'classes':classes,'excluded':excluded,'text':'','kind':kind}
        if tag not in VOID:self.stack.append(node)
        if kind:self.blocks.append(node)
        if tag in {'script','style','noscript'}:self.skip+=1

    def handle_endtag(self,tag):
        if tag in {'script','style','noscript'}:self.skip=max(0,self.skip-1)
        for i in range(len(self.stack)-1,-1,-1):
            if self.stack[i]['tag']==tag:self.stack=self.stack[:i];break

    def handle_data(self,value):
        if self.skip:return
        for node in self.stack:
            if node['kind'] and len(node['text'])<200:node['text']+=value


def publication_block(page):
    # The main Page parser has already decoded class attributes. Avoid a
    # second full HTML parse when none of our exact CMS selectors can match.
    # The source guard also prevents stale memoization if raw_html changes.
    cached=getattr(page,'_publication_block_cache',None)
    if cached is not None and cached[0] is page.raw_html:return cached[1]
    if (getattr(page,'publication_marker_source',None) is page.raw_html and
            getattr(page,'publication_marker',None) is False):
        page._publication_block_cache=(page.raw_html,None)
        return None
    blocks=[]
    for node in Markup(page.raw_html).blocks:
        if node['kind'].startswith('main div.tag-date-container'):
            from urllib.parse import urlsplit
            path=urlsplit(page.url).path
            if (len(page.semantic_headings or page.main_headings or page.content_headings)!=1
                    or not re.search(r'/(?:news|nyheter|blogs?|articles?|aktuelt)/[^/]+',path,re.I)):
                continue
        text=re.sub(r'\s+',' ',node['text']).strip()
        if node['kind'].startswith('div.publish-date') and not re.match(r'^Published on\s+',text,re.I):continue
        value=literal_date(text)
        if value:blocks.append({'date':value,'literal':text,'selector':node['kind']})
    dates={b['date'] for b in blocks}
    result=blocks[0] if len(dates)==1 else None
    page._publication_block_cache=(page.raw_html,result)
    return result
