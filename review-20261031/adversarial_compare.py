"""Compare both engines on identical synthetic source pages, not official score."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parent
ORG='810034882';HOME='https://example.test/'
identity='<footer>Example AS Org nr '+ORG+'</footer>'
news='<article><h1>Example AS opens a factory</h1><p>Example AS opened its new factory today to provide expanded facilities to customers and employees throughout Norway.</p><time itemprop="datePublished" datetime="2026-09-01">Published</time></article>'
cases=[
 {'id':'parent_site_subsidiary_footer','pages':{HOME:'<title>North Group</title><h1>North Group</h1><meta name="description" content="Our group employs 500 people in ten companies.">'+identity+'<a href="https://facebook.com/parent">Facebook</a>'},'expected':{'website.verified_url':False,'website.social_links':False}},
 {'id':'parent_declared_operator','pages':{HOME:identity+'<script type="application/ld+json">'+json.dumps({'@type':'WebSite','url':HOME,'operator':{'@type':'Organization','taxID':'974761076','legalName':'Parent AS'}})+'</script>'},'expected':{'website.verified_url':False}},
 {'id':'agency_footer','pages':{HOME:identity+'<footer><a href="https://facebook.com/wix">Facebook</a></footer>','https://facebook.com/wix':'<title>Wix</title><p>Create a website</p>'},'expected':{'website.social_links':False}},
 {'id':'personal_profile','pages':{HOME:identity+'<a href="https://linkedin.com/in/person">LinkedIn</a>'},'expected':{'website.social_links':False}},
 {'id':'menu_dated_heading','pages':{HOME:identity+'<a href="/news/menu">News</a>',HOME+'news/menu':'<nav><h1>Latest news</h1><time itemprop="datePublished" datetime="2026-09-01">Published</time></nav>'},'expected':{'website.activity':False}},
 {'id':'product_disguised_as_post','pages':{HOME:identity+'<a href="/news/tool">Tool</a>',HOME+'news/tool':'<h1>Example AS tool</h1><p>'+('Useful product information. '*6)+'</p><script type="application/ld+json">'+json.dumps([{'@type':'Product','name':'Tool'},{'@type':'NewsArticle','headline':'Example AS tool','datePublished':'2026-09-01','url':HOME+'news/tool'}])+'</script>'},'expected':{'website.activity':False}},
 {'id':'modified_only','pages':{HOME:identity+'<a href="/news/changed">News</a>',HOME+'news/changed':'<h1>Example AS update</h1><p>'+('Details about Example AS. '*6)+'</p><script type="application/ld+json">{"@type":"Article","headline":"Example AS update","dateModified":"2026-09-01"}</script>'},'expected':{'website.activity':False}},
 {'id':'other_company_post','pages':{HOME:identity+'<a href="/news/other">News</a>',HOME+'news/other':'<title>Example AS | News</title><article><h1>Other AS expands</h1><p>Other AS opened a new factory today to supply its customers with industrial equipment throughout Norway.</p><time itemprop="datePublished" datetime="2026-09-01">Published</time></article>'+identity},'expected':{'website.activity':False}},
 {'id':'real_target_post','pages':{HOME:identity+'<a href="/news/factory">News</a>',HOME+'news/factory':news},'expected':{'website.activity':True,'website.verified_url':True}},
 {'id':'own_entity_sameAs','pages':{HOME:identity+'<a href="https://facebook.com/example">Facebook</a><script type="application/ld+json">'+json.dumps({'@type':'Organization','taxID':ORG,'sameAs':'https://facebook.com/example'})+'</script>'},'expected':{'website.social_links':True,'website.verified_url':True}},
]
RUNNER=r'''
import sys,json,tempfile,hashlib
from unittest.mock import patch
sys.path.insert(0,sys.argv[1]);import agent
cases=json.load(sys.stdin);out=[]
for case in cases:
 with tempfile.TemporaryDirectory() as d:
  f=agent.Fetcher(d,replay=True)
  def get(url,**kwargs):
   f.requests+=1
   rsp={'url':url,'requested_url':url,'status':'available','status_code':200,'retrieved_at':'2026-10-31T12:00:00Z'}
   if url=='https://data.brreg.no/enhetsregisteret/api/enheter/810034882':rsp['json']={'organisasjonsnummer':'810034882','navn':'Example AS','hjemmeside':'https://example.test/','antallAnsatte':3}
   elif url.endswith('/roller'):rsp['json']={'rollegrupper':[]}
   elif '/regnskapsregisteret/' in url:rsp['json']=[]
   elif '/underenheter?' in url:rsp['json']={'page':{'totalPages':0}}
   elif url not in case['pages']:rsp.update(status='not_available',status_code=404)
   rsp['text']=case['pages'].get(url,json.dumps(rsp.get('json',{})))
   rsp['content_sha256']=hashlib.sha256(rsp['text'].encode()).hexdigest()
   return rsp
  with patch.object(f,'get',side_effect=get):row=agent.research({'organisation_number':'810034882'},f)
  published={c['field']:bool(c['availability']=='available' and c['value']) for c in row['claims']}
  out.append({'id':case['id'],'expected':case['expected'],'published':{k:published.get(k,False) for k in case['expected']}})
print(json.dumps(out))
'''
if __name__=='__main__':
 results={}
 for name,path in [('baseline',sys.argv[1]),('candidate',sys.argv[2])]:
  proc=subprocess.run([sys.executable,'-c',RUNNER,path],input=json.dumps(cases),capture_output=True,text=True,check=True)
  rows=json.loads(proc.stdout)
  results[name]={'cases':rows,'false_publications':sum(v and not r['expected'][k] for r in rows for k,v in r['published'].items()),'missed_positives':sum(not v and r['expected'][k] for r in rows for k,v in r['published'].items())}
 results['scope']='10 synthetic adversarial cases; regression evidence only, no real-world precision estimate or official score'
 (ROOT/'adversarial-results.json').write_text(json.dumps(results,indent=2))
 print(json.dumps({k:{m:v for m,v in d.items() if m!='cases'} if isinstance(d,dict) else d for k,d in results.items()},indent=2))
