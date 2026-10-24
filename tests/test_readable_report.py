import copy
import json
from pathlib import Path
import re
import tempfile
import unittest
from insights import synthesize
from readable_report import write_reports


def claim(field, value, state='available', ids=None):
    return {'field': field, 'value': value, 'availability': state,
            'evidence_ids': ['e1'] if ids is None else ids}


def row(org='810034882', name='Example AS'):
    return {'organisation_number': org, 'claims': [claim('legal_name', name), claim('employees', 0)],
            'evidence': [{'id': 'e1', 'source_url': 'https://example.test/source?q=1&x=2',
                          'retrieved_at': '2026-10-23T10:00:00Z', 'content_sha256': 'a' * 64,
                          'source_class': 'official_registry'}], 'changes': [], 'errors': [],
            'run': {'terminal_status': 'completed', 'completed_at': '2026-10-23T10:01:00Z'}}


class ReadableReport(unittest.TestCase):
    def test_preserves_input_order_duplicates_invalid_and_immutable_inputs(self):
        rows = [row(name='First'), row(name='Duplicate'), row('../../evil', 'Invalid'), 'not an object']
        before = copy.deepcopy(rows)
        with tempfile.TemporaryDirectory() as d:
            result = write_reports(iter(rows), Path(d) / 'reports')
            self.assertEqual(result['count'], 4)
            self.assertEqual(result['status'], 'written')
            self.assertEqual(result['state'], 'completed')
            self.assertEqual(result['files'][:4], ['00001-810034882.md', '00002-810034882.md',
                                                 '00003-invalid-org.md', '00004-invalid-org.md'])
            index = Path(result['index_path']).read_text()
            self.assertLess(index.index('First'), index.index('Duplicate'))
            self.assertIn('invalid', index)
            self.assertTrue(Path(result['html_path']).is_file())
            self.assertTrue((Path(d) / 'reports' / 'workspace.html').is_file())
            self.assertIn('Compare companies and inspect evidence', index)
            self.assertEqual(len(list((Path(d) / 'reports').glob('*.md'))), 5)
        self.assertEqual(rows, before)

    def test_existing_directory_and_symlinks_are_refused_without_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            existing = root / 'exists'; existing.mkdir(); marker = existing / 'marker'; marker.write_text('preserve')
            with self.assertRaises(FileExistsError): write_reports([row()], existing)
            link = root / 'link'; link.symlink_to(existing, target_is_directory=True)
            with self.assertRaises(ValueError): write_reports([row()], link)
            with self.assertRaises(ValueError): write_reports([row()], link / 'new')
            self.assertEqual(marker.read_text(), 'preserve')
            self.assertFalse((existing / 'new').exists())

    def test_script_markdown_filename_and_javascript_injection_are_inert(self):
        attack = '</script><script>alert(1)</script> [click](javascript:alert(1))\n# forged | cell'
        r = row('../../../outside', attack)
        r['evidence'][0].update(source_url='javascript:alert(1)', excerpt=attack, id='e1')
        r['claims'] += [claim('website.description', attack),
                        claim('website.social_links', [{'url': 'javascript:alert(1)', 'text': attack}])]
        with tempfile.TemporaryDirectory() as d:
            result = write_reports([r], Path(d) / 'reports')
            markdown = (Path(d) / 'reports' / '00001-invalid-org.md').read_text()
            page = Path(result['html_path']).read_text()
            self.assertNotIn('<script>alert', page)
            self.assertNotIn('href="javascript:', page)
            self.assertNotIn('<script>', markdown)
            self.assertNotIn('](javascript:', markdown)
            self.assertNotIn('\n# forged', markdown)
            self.assertIn('unsafe or unsupported URL', markdown)
            self.assertEqual(len(list(Path(d).iterdir())), 1)
            self.assertEqual(page.count('<script>'), 1)

    def test_safe_source_links_references_dates_hashes_and_prior_evidence(self):
        old = row(); old['evidence'][0]['id'] = 'old'; old['evidence'][0]['source_url'] = 'https://old.example.test/a(b)'
        current = row(); current['previous_snapshot'] = old
        current['claims'][0]['evidence_ids'] = ['e1', 'e1', 'missing']
        current['changes'] = [{'field': 'employees', 'old_value': 2, 'new_value': 0,
                               'old_evidence_ids': ['old'], 'new_evidence_ids': ['e1']}]
        with tempfile.TemporaryDirectory() as d:
            result = write_reports([current], Path(d) / 'reports')
            text = (Path(d) / 'reports' / result['files'][0]).read_text()
            self.assertIn('Unresolved evidence IDs: missing', text)
            self.assertIn('https://old.example.test/a%28b%29', text)
            self.assertIn('2026', text)
            self.assertIn('a' * 64, text)
            self.assertIn('Previous evidence IDs: old', text)
            self.assertIn('Factual synthesis withheld', text)
            self.assertIn('Canonical input SHA256:', text)
            self.assertNotIn('e1, e1', text)

    def test_six_states_unknown_values_and_no_inferred_absence(self):
        r = row()
        states = ['available', 'not_available', 'blocked', 'not_applicable', 'ambiguous', 'failed', 'future_state']
        r['claims'] = [claim('f' + str(i), 0 if state == 'available' else 'UNSUPPORTED_VALUE', state)
                       for i, state in enumerate(states)]
        with tempfile.TemporaryDirectory() as d:
            result = write_reports([r], Path(d) / 'reports')
            text = (Path(d) / 'reports' / result['files'][0]).read_text()
            for state in states: self.assertTrue(state in text or state.replace('_', chr(92) + '_') in text)
            self.assertNotIn('UNSUPPORTED_VALUE', text)
            self.assertIn('not zero or proof of absence', text)
            self.assertIn('Unrecognized states', text)
            self.assertIn('Value: 0', text)

    def test_does_not_resolve_evidence_from_another_organisation(self):
        r = row(); previous = row('999999999'); previous['evidence'][0]['id'] = 'foreign'
        r['previous_snapshot'] = previous
        r['claims'][0]['evidence_ids'] = ['foreign']
        with tempfile.TemporaryDirectory() as d:
            result = write_reports([r], Path(d) / 'reports')
            text = (Path(d) / 'reports' / result['files'][0]).read_text()
            self.assertIn('Unresolved evidence IDs: foreign', text)
            self.assertNotIn('### Evidence foreign', text)

    def test_website_context_contact_social_are_evidence_linked_and_attributed(self):
        claims = [claim('website.description', 'We build pumps'),
                  claim('website.contact_channels', [{'type': 'email', 'value': 'hello@example.test'}]),
                  claim('website.social_links', [{'url': 'https://example.test/social'}])]
        statements = synthesize(claims)
        self.assertEqual(len(statements), 3)
        self.assertTrue(all(s['evidence_ids'] == ['e1'] for s in statements))
        self.assertIn('company-declared', statements[0]['text'])
        self.assertIn('not tested', statements[1]['text'])
        self.assertIn('not independently verified', statements[2]['text'])
        self.assertEqual(synthesize([claim('legal_name', 'Unsupported', ids=[])])[0]['kind'], 'limitation')

    def test_unsafe_url_variants_never_become_markdown_links(self):
        urls = ['javascript:alert(1)', 'data:text/html,<script>x</script>', '//example.test',
                'https://user:password@example.test', 'https://example.test/\nattack', 'https://example.test/\\attack']
        with tempfile.TemporaryDirectory() as d:
            rows = []
            for index, url in enumerate(urls):
                r = row(); r['evidence'][0]['source_url'] = url; rows.append(r)
            result = write_reports(rows, Path(d) / 'reports')
            for filename in result['files'][:len(rows)]:
                text = (Path(d) / 'reports' / filename).read_text()
                self.assertIn('unsafe or unsupported URL', text)
                self.assertNotIn('](<javascript:', text)
                self.assertNotIn('](<data:', text)

    def test_claim_level_qualifiers_attribution_and_extra_metadata_are_visible_and_unchanged(self):
        r = row()
        r['claims'][0].update(
            qualifiers=['Company declared only', '<script>alert(1)</script>'],
            attribution={'level': 'legal entity match unconfirmed'},
            candidate_limitations=['Destination ownership not independently verified'],
            future_metadata={'review_note': 'Keep this future qualifier visible'})
        before = copy.deepcopy(r)
        with tempfile.TemporaryDirectory() as d:
            result = write_reports([r], Path(d) / 'reports')
            text = (Path(d) / 'reports' / result['files'][0]).read_text()
            self.assertIn('Additional claim metadata:', text)
            for phrase in ('qualifiers', 'attribution', 'Company declared only',
                           'legal entity match unconfirmed', 'Destination ownership not independently verified',
                           'Keep this future qualifier visible'):
                self.assertIn(phrase, text)
            self.assertNotIn('<script>', text)
            self.assertIn('&lt;script&gt;', text)
            self.assertIn('State: available', text)
            self.assertIn('Value: Example AS', text)
        self.assertEqual(r, before)

    def test_empty_input_still_writes_indexes(self):
        with tempfile.TemporaryDirectory() as d:
            result = write_reports([], Path(d) / 'empty')
            self.assertEqual(result['count'], 0)
            self.assertEqual(set(result['files']), {'index.md', 'index.html', 'workspace.html'})


if __name__ == '__main__': unittest.main()
