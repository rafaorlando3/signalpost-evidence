"""Synthetic/offline checks for the v0.7 plain-list wrapper."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cli
import test_pipeline

ORG = '810034882'


class ListCli(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.cache = self.root / 'cache'
        self.output = self.root / 'results.jsonl'

    def call(self, extra, output=None):
        path = output or self.output
        with contextlib.redirect_stderr(io.StringIO()) as error:
            code = cli.main([*extra, '--cache', str(self.cache), '--output', str(path)])
        rows = ([json.loads(line) for line in path.read_text().splitlines()]
                if code in (0, 2, 130) and path.is_file() and not path.is_symlink() else [])
        return code, rows, error.getvalue()

    def fixture(self):
        self.cache.mkdir(exist_ok=True)
        test_pipeline.Pipeline().fixture(str(self.cache))

    def complete(self, states=('available',)):
        row = cli.failed(ORG, 'fixture')
        row['run']['terminal_status'] = 'completed'
        row['errors'] = []
        row['evidence'] = [{'id': 'e', 'source_url': 'https://example.test/',
                            'retrieved_at': '2026-10-23T00:00:00+00:00',
                            'content_sha256': 'a' * 64}]
        row['claims'] = [{'field': 'field_' + str(index), 'value': 'literal' if state == 'available' else None,
                          'availability': state, 'evidence_ids': ['e']}
                         for index, state in enumerate(states)]
        return row

    def test_default_live_command_is_free_fresh_bounded_and_deduplicated(self):
        def supervisor(command, staged, rows, timeout, log, previous, paid_search):
            self.assertEqual([row['organisation_number'] for row in rows], [ORG])
            self.assertIn('--fresh', command)
            self.assertNotIn('--replay', command)
            self.assertEqual(command[command.index('--search') + 1], 'none')
            self.assertEqual(timeout, 2400)
            self.assertFalse(paid_search)
            return [self.complete()], {'collector_exit': 0}
        with patch('cli.collect', side_effect=supervisor):
            code, rows, error = self.call(['--orgs', ORG, ORG])
        self.assertEqual(code, 0, error)
        self.assertEqual(len(rows), 2)
        self.assertTrue(rows[1]['_cli']['observation_reused'])
        self.assertEqual(rows[1]['_cli']['observation_input_index'], 1)
        summary = json.loads(self.output.with_suffix('.summary.json').read_text())
        self.assertEqual(summary['unique_valid_companies'], 1)
        self.assertEqual(summary['request_budget_total'], 20)
        self.assertTrue(self.cache.is_dir())

    def test_invalid_ascii_checksum_unicode_blank_each_get_failure(self):
        source = self.root / 'input.txt'
        source.write_text('bad\n\n810034883\n８１００３４８８２\n')
        with patch('cli.collect', side_effect=AssertionError('no valid inputs')):
            code, rows, _ = self.call(['--org-list', str(source)])
        self.assertEqual(code, 2)
        self.assertEqual(len(rows), 4)
        self.assertEqual([row['_cli']['source_line'] for row in rows], [1, 2, 3, 4])
        self.assertTrue(all(row['run']['terminal_status'] == 'failed' and not row['claims']
                            for row in rows))

    def test_real_replay_duplicates_whitespace_and_zero_requests(self):
        self.fixture()
        with patch('socket.getaddrinfo', side_effect=AssertionError('network forbidden')):
            code, rows, error = self.call(['--replay', '--orgs', ORG, ' ' + ORG + ' '])
        self.assertEqual(code, 0, error)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]['_cli']['duplicate_of'], 1)
        self.assertEqual(rows[1]['_cli']['raw_input'], ' ' + ORG + ' ')
        self.assertTrue(all(row['operations']['requests'] == 0 for row in rows))
        self.assertEqual(next(claim['value'] for claim in rows[0]['claims']
                              if claim['field'] == 'legal_name'), 'Fixture AS')
        self.assertEqual(rows[0]['source_snapshots'], rows[1]['source_snapshots'])

    def test_mixed_invalid_valid_order(self):
        self.fixture()
        code, rows, error = self.call(['--replay', '--orgs', 'bad', ORG, 'bad'])
        self.assertEqual(code, 2, error)
        self.assertEqual([row['organisation_number'] for row in rows], ['bad', ORG, 'bad'])
        self.assertEqual(rows[2]['_cli']['duplicate_of'], 1)
        self.assertTrue(rows[1]['_cli']['input_valid'])

    def test_six_availability_states_are_preserved_separately_from_run(self):
        states = sorted(cli.STATES)
        with patch('cli.execute', return_value=([self.complete(states)], {'collector_exit': 0})):
            code, rows, _ = self.call(['--orgs', ORG])
        self.assertEqual(code, 0)
        self.assertEqual(rows[0]['run']['terminal_status'], 'completed')
        self.assertEqual(rows[0]['_cli']['claim_status_counts'], {state: 1 for state in states})
        self.assertEqual([claim['availability'] for claim in rows[0]['claims']], states)

    def test_completed_collector_without_available_claim_is_explicit(self):
        with patch('cli.execute', return_value=([self.complete(['blocked', 'failed'])],
                                                {'collector_exit': 0})):
            code, rows, _ = self.call(['--orgs', ORG])
        self.assertEqual(code, 2)
        self.assertEqual(rows[0]['run']['terminal_status'], 'completed')
        self.assertEqual(rows[0]['_cli']['outcome'], 'completed_without_available_claims')
        self.assertEqual(rows[0]['_cli']['claim_status_counts']['available'], 0)

    def test_replay_cache_miss_never_becomes_evidence(self):
        self.cache.mkdir()
        code, rows, error = self.call(['--replay', '--orgs', ORG])
        self.assertEqual(code, 2, error)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['operations']['requests'], 0)
        self.assertTrue(all(claim['availability'] != 'available' for claim in rows[0]['claims']))

    def test_missing_replay_cache_is_configuration_error(self):
        with patch('cli.execute', side_effect=AssertionError('no execution')):
            code, _, _ = self.call(['--replay', '--orgs', ORG])
        self.assertEqual(code, 1)
        self.assertFalse(self.output.exists())

    def test_previous_replay_preserves_history_and_idempotence(self):
        self.fixture()
        code, first, error = self.call(['--replay', '--orgs', ORG])
        self.assertEqual(code, 0, error)
        second_path = self.root / 'second.jsonl'
        code, second, error = self.call(['--replay', '--previous', str(self.output),
                                         '--orgs', ORG], second_path)
        self.assertEqual(code, 0, error)
        self.assertEqual(second[0]['previous_snapshot'], first[0])
        self.assertEqual(second[0]['changes'], [])
        self.assertEqual(second[0]['operations']['requests'], 0)

    def test_snapshot_and_previous_flags_reach_supervisor(self):
        snapshot = self.root / 'snapshot.jsonl'
        snapshot.write_text('')
        previous_path = self.root / 'previous.jsonl'
        prior = self.complete()
        previous_path.write_text('\n' + json.dumps(prior) + '\n\n')
        def supervisor(command, staged, rows, timeout, log, previous, paid_search):
            self.assertEqual(command[command.index('--registry-snapshot') + 1], str(snapshot))
            normalized_prior = Path(command[command.index('--previous') + 1])
            self.assertEqual([json.loads(line) for line in normalized_prior.read_text().splitlines()], [prior])
            self.assertEqual(previous, {ORG: prior})
            return [self.complete()], {'collector_exit': 0}
        with patch('cli.collect', side_effect=supervisor):
            code, _, error = self.call(['--orgs', ORG, '--registry-snapshot', str(snapshot),
                                        '--previous', str(previous_path)])
        self.assertEqual(code, 0, error)

    def test_invalid_previous_rejected_before_collection(self):
        previous_path = self.root / 'previous.jsonl'
        previous_path.write_text('{bad}\n')
        with patch('cli.execute', side_effect=AssertionError('no execution')):
            code, _, error = self.call(['--orgs', ORG, '--previous', str(previous_path)])
        self.assertEqual(code, 1)
        self.assertIn('invalid previous JSON at line 1', error)
        self.assertFalse(self.output.exists())

    def test_existing_output_or_summary_is_never_overwritten(self):
        for path in (self.output, self.output.with_suffix('.summary.json')):
            with self.subTest(path=path):
                path.write_text('sentinel')
                with patch('cli.execute', side_effect=AssertionError('no execution')):
                    code, _, _ = self.call(['--orgs', ORG])
                self.assertEqual(code, 1)
                self.assertEqual(path.read_text(), 'sentinel')
                path.unlink()

    def test_existing_and_dangling_symlinks_refused(self):
        for exists in (False, True):
            with self.subTest(existing_target=exists):
                victim = self.root / ('victim' + str(exists))
                if exists:
                    victim.write_text('sentinel')
                self.output.symlink_to(victim)
                with patch('cli.execute', side_effect=AssertionError('no execution')):
                    code, _, _ = self.call(['--orgs', ORG])
                self.assertEqual(code, 1)
                self.assertEqual(victim.read_text() if exists else victim.exists(),
                                 'sentinel' if exists else False)
                self.output.unlink()

    def test_collector_exception_emits_every_line_without_exception_detail(self):
        with patch('cli.execute', side_effect=RuntimeError('sensitive upstream detail')):
            code, rows, error = self.call(['--orgs', ORG, 'bad', ORG])
        self.assertEqual(code, 2)
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(row['run']['terminal_status'] == 'failed' for row in rows))
        self.assertNotIn('sensitive upstream detail', self.output.read_text() + error)
        summary = json.loads(self.output.with_suffix('.summary.json').read_text())
        self.assertEqual(summary['requests'], 20)
        self.assertTrue(summary['requests_include_upper_bounds'])

    def test_wrong_company_and_exceeded_budget_are_terminal_failures(self):
        for field, value in (('organisation_number', '999999999'), ('requests', 21)):
            row = self.complete()
            if field == 'requests':
                row['operations']['requests'] = value
            else:
                row[field] = value
            with self.subTest(field=field):
                output = self.root / (field + '.jsonl')
                with patch('cli.execute', return_value=([row], {'collector_exit': 0})):
                    code, rows, _ = self.call(['--orgs', ORG], output)
                self.assertEqual(code, 2)
                self.assertEqual(rows[0]['organisation_number'], ORG)
                self.assertEqual(rows[0]['run']['terminal_status'], 'failed')
                self.assertEqual(rows[0]['operations']['requests'], 20)

    def test_partial_or_timeout_guard_preserves_matching_prefix(self):
        first = self.complete()
        second_org = '974761076'
        second = cli.failed(second_org, 'collector wall-clock deadline exceeded', interrupted=True)
        with patch('cli.execute', return_value=([first, second],
             {'collector_exit': -9, 'wall_clock_timeout': True, 'synthesized_failures': 1})):
            code, rows, _ = self.call(['--orgs', ORG, second_org])
        self.assertEqual(code, 2)
        self.assertEqual(rows[0]['claims'], first['claims'])
        self.assertEqual(rows[1]['run']['terminal_status'], 'failed')

    def test_bad_output_count_emits_all_entries(self):
        with patch('cli.execute', return_value=([], {'collector_exit': 0})):
            code, rows, _ = self.call(['--orgs', ORG, ORG])
        self.assertEqual(code, 2)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row['run']['terminal_status'] == 'failed' for row in rows))

    def test_cancellation_leaves_explicit_results(self):
        with patch('cli.execute', side_effect=KeyboardInterrupt):
            code, rows, _ = self.call(['--orgs', ORG, 'bad'])
        self.assertEqual(code, 130)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row['run']['terminal_status'] == 'failed' for row in rows))

    def test_non_finite_or_out_of_range_timeout_and_workers_refused(self):
        for flags in (['--timeout-seconds', 'nan'], ['--timeout-seconds', 'inf'],
                      ['--timeout-seconds', '0'], ['--timeout-seconds', '2601'],
                      ['--workers', '0'], ['--workers', '9']):
            with self.subTest(flags=flags), patch('cli.execute', side_effect=AssertionError('no execution')):
                code, _, _ = self.call(['--orgs', ORG, *flags])
            self.assertEqual(code, 1)
            self.assertFalse(self.output.exists())

    def test_empty_or_invalid_utf8_file_is_configuration_error(self):
        source = self.root / 'input.txt'
        for data in (b'', b'\xff'):
            with self.subTest(data=data):
                source.write_bytes(data)
                code, _, _ = self.call(['--org-list', str(source)])
                self.assertEqual(code, 1)
                self.assertFalse(self.output.exists())

    def test_controls_and_unicode_separators_do_not_create_extra_lines(self):
        for control in ('\v', '\f', '\x85', '\u2028', '\u2029'):
            with self.subTest(control=ord(control)):
                source = self.root / 'input.txt'
                raw = ORG + control + 'bad'
                source.write_text(raw + '\n')
                output = self.root / ('control-' + str(ord(control)) + '.jsonl')
                code, rows, _ = self.call(['--org-list', str(source)], output)
                self.assertEqual(code, 2)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]['_cli']['raw_input'], raw)
                self.assertEqual(len(output.read_text().splitlines()), 1)

    def test_bom_crlf_and_trailing_delimiter_preserve_row_count(self):
        source = self.root / 'input.txt'
        source.write_bytes(b'\xef\xbb\xbfbad\r\n\r\n')
        code, rows, _ = self.call(['--org-list', str(source)])
        self.assertEqual(code, 2)
        self.assertEqual([row['_cli']['raw_input'] for row in rows], ['bad', ''])
        self.assertEqual([row['_cli']['source_line'] for row in rows], [1, 2])

    def test_custom_summary_and_nested_output_directory(self):
        path = self.root / 'runs' / 'result.jsonl'
        summary = self.root / 'reports' / 'summary.json'
        with patch('cli.execute', return_value=([self.complete()], {'collector_exit': 0})):
            code, rows, error = self.call(['--orgs', ORG, '--summary', str(summary)], path)
        self.assertEqual(code, 0, error)
        import hashlib
        report = json.loads(summary.read_text())
        self.assertEqual(report['output_sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(report['inputs'], report['outputs'])
        self.assertEqual(len(rows), 1)


if __name__ == '__main__':
    unittest.main()
