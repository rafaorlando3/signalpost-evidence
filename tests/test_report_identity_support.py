"""Workspace identity rendering accepts every collector proof shape (P2-3).

The collector stores different `identity_support` shapes per verification
method. Site-operator proofs have no `literal_spans`; business-address proofs
keep them under `address_source`. The review workspace must render each one
honestly, escape it, and never abort the whole company page.
"""
import json
import shutil
import subprocess
import unittest

from report import TEMPLATE, build

OPERATOR = {
    'state': 'target',
    'reason': 'current WebSite explicitly declares the requested organisation as operator',
    'operators': [{'relationship': 'publisher', 'website_url': 'https://example.no/',
                   'website_script_index': 0, 'website_json_pointer': '/@graph/0',
                   'operator_script_index': 0, 'operator_json_pointer': '/@graph/1',
                   'organisation_numbers': ['123456785'], 'legal_name': 'Example <b>AS</b>',
                   'source_url': 'https://example.no/'}]}
UNRESOLVED_OPERATOR = {'state': 'unresolved',
                       'reason': 'operator assertion limit exceeded; own-entity attribution unresolved',
                       'operators': []}
CONTACT_MAP = {
    'method': 'registered_domain_exact_legal_contact_map', 'registered_name': 'Example Works AS',
    'organisation_number': '123456785', 'entry_url': 'https://example.no/',
    'source_url': 'https://example.no/kontakt', 'declared_registry_url': 'www.example.no',
    'marker': {'container': 'script', 'script_index': 0, 'json_pointer': '/markers/0'},
    'address_kind': 'forretningsadresse', 'registered_street': 'Storgata 1', 'registered_postcode': '0150',
    'literal_spans': [{'start': 0, 'end': 16, 'text': 'Example Works AS'},
                      {'start': 18, 'end': 28, 'text': 'Storgata 1'},
                      {'start': 30, 'end': 34, 'text': '0150'}],
    'links': [], 'scope': 'one exact legally named contact-map record'}
BUSINESS = {
    'method': 'linked_business_self_description_and_registered_address',
    'registered_name': 'Example Works AS', 'organisation_number': '123456785',
    'entry_url': 'https://example.no/',
    'legal_name_source': {'source_url': 'https://example.no/om-oss', 'self_description': 'Example Works AS er ...'},
    'address_source': {'source_url': 'https://example.no/kontakt', 'address_kind': 'forretningsadresse',
                       'registered_street': 'Storgata 1', 'registered_postcode': '0150',
                       'literal_spans': [{'start': 5, 'end': 15, 'text': 'Storgata 1'},
                                         {'start': 17, 'end': 21, 'text': '0150'}],
                       'links': []},
    'scope': 'first-party legal self-description plus exact registered address'}
CORROBORATION = {
    'registered_name': 'Example Works AS', 'registered_website': 'www.example.no',
    'observed_entry_url': 'https://www.example.no/', 'address_kind': 'forretningsadresse',
    'literal_spans': [{'start': 0, 'end': 13, 'text': 'Example Works'}]}
MALFORMED = [None, 'Example Works', {'text': 'not a list'}, 42,
             [None, 'loose text', {'text': 5}, {'text': ''}, {'start': 1}]]


def row(support, org='123456785', url='https://example.no/'):
    return {'organisation_number': org,
            'claims': [{'field': 'legal_name', 'availability': 'available', 'value': 'Example Works AS',
                        'evidence_ids': []},
                       {'field': 'website.verified_url', 'availability': 'available', 'value': url,
                        'evidence_ids': [], 'source_pointer': 'explicit_site_operator',
                        'identity_support': support}],
            'changes': [], 'evidence': [], 'synthesis': [], 'errors': [],
            'run': {'terminal_status': 'completed', 'completed_at': '2026-11-09T00:00:00Z'},
            'operations': {'requests': 3, 'cache_hits': 0, 'third_party_cost_usd': 0}}


class TemplateShape(unittest.TestCase):
    """Static checks; no browser, Node or network needed."""

    def test_render_uses_guarded_helper_instead_of_direct_span_access(self):
        self.assertNotIn('identity_support.literal_spans.map', TEMPLATE)
        self.assertIn('${identityDetails(c.identity_support)}', TEMPLATE)
        start = TEMPLATE.index('/* identity-support helpers')
        end = TEMPLATE.index('/* end identity-support helpers */')
        outside = TEMPLATE[:start] + TEMPLATE[end:]
        self.assertNotIn('literal_spans', outside)

    def test_operator_payload_is_still_embedded_as_inert_json(self):
        hostile = dict(OPERATOR, reason='</script><script>alert(1)</script>')
        html = build([row(hostile)])
        payload = html.split('<script id="data" type="application/json">', 1)[1].split('</script>', 1)[0]
        self.assertNotIn('</script><script>alert(1)', payload)
        self.assertEqual(json.loads(payload)[0]['claims'][1]['identity_support']['reason'],
                         '</script><script>alert(1)</script>')


HELPERS = r"""
const assert=require('node:assert/strict'),vm=require('node:vm');
const input=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
const ctx={};vm.createContext(ctx);
vm.runInContext(input.helpers+';globalThis.identityDetails=identityDetails;',ctx);
const f=ctx.identityDetails;
"""

RENDER = r"""
const assert=require('node:assert/strict'),vm=require('node:vm');
const input=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
const values={q:'',filter:'all',sort:'name'};const elements={};
const element=id=>elements[id]||(elements[id]={id,value:values[id]??'',innerHTML:'',
  textContent:id==='data'?input.payload:'',disabled:false,checked:false,dataset:{},
  classList:{toggle(){},add(){},remove(){}},scrollIntoView(){}});
const ctx={document:{getElementById:element,querySelectorAll:()=>[],createElement:()=>({click(){}})},
  URL,Blob:function(){},setTimeout,JSON,console};
vm.createContext(ctx);
vm.runInContext(input.script,ctx);
const html=elements.items.innerHTML;
"""


@unittest.skipUnless(shutil.which('node'), 'Node evaluates the shipped workspace JavaScript')
class WorkspaceIdentityRendering(unittest.TestCase):
    def node(self, harness, data, assertions):
        result = subprocess.run([shutil.which('node'), '-e', harness + assertions],
                                input=json.dumps(data), text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def helpers(self):
        script = TEMPLATE.split('<script>', 1)[1]
        start = script.index('const esc=')
        end = script.index('/* end identity-support helpers */')
        return script[start:end]

    def page(self, rows):
        html = build(rows)
        payload = html.split('<script id="data" type="application/json">', 1)[1].split('</script>', 1)[0]
        script = html.split('<script>', 1)[1].rsplit('</script>', 1)[0]
        return {'payload': payload, 'script': script}

    def test_operator_proof_renders_declaration_without_spans(self):
        self.node(HELPERS, {'helpers': self.helpers(), 'operator': OPERATOR, 'unresolved': UNRESOLVED_OPERATOR}, r"""
let out=f(input.operator);
assert.match(out,/Site operator assertion: target/);
assert.match(out,/publisher: Example &lt;b&gt;AS&lt;\/b&gt; · organisation number 123456785/);
assert.doesNotMatch(out,/<b>AS/);
assert.match(out,/No literal text span is recorded/);
assert.doesNotMatch(out,/<blockquote>/);
out=f(input.unresolved);
assert.match(out,/Site operator assertion: unresolved · operator assertion limit exceeded/);
assert.doesNotMatch(out,/<ul>/);
""")

    def test_contact_map_and_business_proofs_show_all_cited_literal_text(self):
        self.node(HELPERS, {'helpers': self.helpers(), 'map': CONTACT_MAP, 'business': BUSINESS,
                            'legacy': CORROBORATION}, r"""
let out=f(input.map);
assert.equal((out.match(/<blockquote>/g)||[]).length,3);
for(const t of ['Example Works AS','Storgata 1','0150'])assert.ok(out.includes('<blockquote>'+t+'</blockquote>'),t);
assert.match(out,/Method: registered_domain_exact_legal_contact_map/);
assert.match(out,/Registered site: www\.example\.no<br>Observed destination: https:\/\/example\.no\//);
assert.match(out,/Proof page: https:\/\/example\.no\/kontakt/);
out=f(input.business);
assert.equal((out.match(/<blockquote>/g)||[]).length,2);
assert.ok(out.includes('<blockquote>Storgata 1</blockquote>')&&out.includes('<blockquote>0150</blockquote>'));
out=f(input.legacy);
assert.match(out,/Registry name: Example Works AS/);
assert.match(out,/Registered site: www\.example\.no<br>Observed destination: https:\/\/www\.example\.no\//);
assert.ok(out.includes('<blockquote>Example Works</blockquote>'));
""")

    def test_missing_or_non_array_spans_and_non_object_support_never_throw(self):
        self.node(HELPERS, {'helpers': self.helpers(), 'malformed': MALFORMED, 'base': CORROBORATION}, r"""
for(const spans of input.malformed){
  const out=f({...input.base,literal_spans:spans,address_source:{literal_spans:spans}});
  assert.match(out,/No literal text span is recorded/);assert.doesNotMatch(out,/<blockquote>/);
}
const missing={...input.base};delete missing.literal_spans;
assert.match(f(missing),/No literal text span is recorded/);
for(const v of [null,undefined,'text',7,[],[{text:'x'}]])assert.equal(f(v),'');
assert.ok(f({...input.base,address_source:'flat string'}).includes('<blockquote>Example Works</blockquote>'));
""")

    def test_span_and_operator_text_is_escaped(self):
        hostile = dict(CORROBORATION, literal_spans=[{'start': 0, 'end': 9, 'text': '<img src=x onerror=alert(1)>'}],
                       registered_name='"><script>x</script>')
        self.node(HELPERS, {'helpers': self.helpers(), 'hostile': hostile}, r"""
const out=f(input.hostile);
assert.ok(out.includes('&lt;img src=x onerror=alert(1)&gt;'));
assert.ok(out.includes('&quot;&gt;&lt;script&gt;x&lt;/script&gt;'));
assert.doesNotMatch(out,/<img|<script/);
""")

    def test_full_workspace_render_survives_every_proof_shape(self):
        shapes = [OPERATOR, UNRESOLVED_OPERATOR, CONTACT_MAP, BUSINESS, CORROBORATION, *MALFORMED[:4]]
        rows = [row(s, org=str(100000000 + i)) for i, s in enumerate(shapes)]
        self.node(RENDER, self.page(rows), r"""
assert.equal((html.match(/<article>/g)||[]).length,9);
assert.match(html,/Site operator assertion: target/);
assert.match(html,/Site operator assertion: unresolved/);
assert.ok(html.includes('<blockquote>Storgata 1</blockquote>'));
assert.doesNotMatch(html,/No companies match these filters/);
""")


if __name__ == '__main__':
    unittest.main()
