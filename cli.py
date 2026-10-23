"""Run v0.7 company research from a plain organisation-number list (LIVE by default)."""
import argparse
import collections
import copy
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile

from agent import STATES, valid_org
from evaluator import collect
from validate import validate

SCHEMA = 'signalpost-list-cli/2'
FORMAT = 'legacy-evidence-envelope/0.7'
MAX_INPUT_BYTES = 4_000_000
MAX_ENTRIES = 10_000


def failed(org, reason, previous=None, interrupted=False):
    """A local terminal failure publishes no claims."""
    return {
        'organisation_number': org, 'claims': [], 'evidence': [], 'changes': [],
        'errors': [{'reason': reason}], 'source_snapshots': [],
        'previous_snapshot': previous,
        'refresh': {'mode': 'cli_failed', 'changed_fields': [], 'cache_declared': True},
        'synthesis': [],
        'run': {'terminal_status': 'failed',
                'completed_at': dt.datetime.now(dt.timezone.utc).isoformat()},
        'operations': {'requests': 20 if interrupted else 0,
                       'requests_are_upper_bound': interrupted,
                       'cache_hits': 0, 'third_party_cost_usd': 0},
    }


def input_items(args):
    if args.orgs is not None:
        raw, origin = args.orgs, 'argv'
    else:
        with args.org_list.open('rb') as source:
            data = source.read(MAX_INPUT_BYTES + 1)
        if len(data) > MAX_INPUT_BYTES:
            raise ValueError('input exceeds 4 MB budget')
        text = data.decode('utf-8-sig')
        raw, origin = (text.split('\n') if text else []), 'file'
        # Only LF/CRLF delimit physical lines. Other controls remain input data.
        for index in range(max(0, len(raw) - 1)):
            if raw[index].endswith('\r'):
                raw[index] = raw[index][:-1]
        if raw and raw[-1] == '':
            raw.pop()
    if not raw or len(raw) > MAX_ENTRIES:
        raise ValueError('expected 1..10000 input entries')
    items, seen = [], {}
    for index, value in enumerate(raw, 1):
        org = value.strip(' \t')
        duplicate = seen.get(org)
        seen.setdefault(org, index)
        items.append({
            'org': org, 'raw': value, 'index': index, 'duplicate': duplicate,
            'valid': bool(re.fullmatch(r'[0-9]{9}', org)) and valid_org(org),
        })
    return items, origin


def previous_rows(path):
    if path is None:
        return {}
    rows = []
    with path.open(encoding='utf-8-sig') as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError:
                raise ValueError('invalid previous JSON at line ' + str(line_number)) from None
            if not isinstance(row, dict) or not isinstance(row.get('organisation_number'), str):
                raise ValueError('invalid previous envelope at line ' + str(line_number))
            rows.append(row)
    if not validate(rows, [row['organisation_number'] for row in rows])['structurally_valid']:
        raise ValueError('previous file contains an invalid v0.7 envelope')
    # Same behavior as agent.py: the last previous envelope per number is used.
    return {row['organisation_number']: row for row in rows}


def execute(items, args, folder, previous):
    # One observation per distinct valid number avoids multiplying the 20-request
    # company budget for duplicate input lines. Every line is expanded afterwards.
    numbers = list(dict.fromkeys(item['org'] for item in items if item['valid']))
    rows = [{'organisation_number': org} for org in numbers]
    if not rows:
        return [], None
    source, staged = folder / 'input.jsonl', folder / 'collected.jsonl'
    source.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')
    command = [
        sys.executable, '-B', str(Path(__file__).with_name('agent.py')),
        '--input', str(source), '--output', str(staged), '--cache', str(args.cache),
        '--workers', str(args.workers), '--search', 'none',
        '--replay' if args.replay else '--fresh',
    ]
    if args.previous is not None:
        # Normalize accepted blank lines once: agent.py expects every line to be JSON.
        prior_path = folder / 'previous.jsonl'
        prior_path.write_text(''.join(json.dumps(row, ensure_ascii=True) + '\n'
                                      for row in previous.values()), encoding='utf-8')
        command.extend(['--previous', str(prior_path)])
    if args.registry_snapshot is not None:
        command.extend(['--registry-snapshot', str(args.registry_snapshot)])
    return collect(command, staged, rows, args.timeout_seconds,
                   folder / 'collector.log', previous, paid_search=False)


def counts(row):
    result = {state: 0 for state in sorted(STATES)}
    result.update(collections.Counter(claim['availability'] for claim in row['claims']))
    return result


def exclusive_file(path):
    # Final-path symlinks (including dangling ones) are rejected by O_EXCL.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    return os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n')


def run(args):
    if not math.isfinite(args.timeout_seconds) or not 0 < args.timeout_seconds <= 2600:
        raise ValueError('timeout must be finite, positive and <=2600 seconds')
    if not 1 <= args.workers <= 8:
        raise ValueError('workers must be between 1 and 8')
    items, origin = input_items(args)
    previous = previous_rows(args.previous)
    args.output = args.output.absolute()
    args.cache = args.cache.absolute()
    summary_path = (args.summary or args.output.with_suffix('.summary.json')).absolute()
    if args.output == summary_path:
        raise ValueError('output and summary paths must differ')
    for path in (args.output, summary_path):
        if path.exists() or path.is_symlink():
            raise FileExistsError('artifact already exists; choose a new path: ' + str(path))
    if args.replay and not args.cache.is_dir():
        raise ValueError('replay cache directory must already exist')
    if args.registry_snapshot is not None and not args.registry_snapshot.is_file():
        raise ValueError('registry snapshot must be a readable local file')
    args.cache.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    mode = 'replay' if args.replay else 'live'
    unique = list(dict.fromkeys(item['org'] for item in items if item['valid']))
    cancelled = False
    # Reserve both new artifacts before any collection. Failed publishers never
    # overwrite a pre-existing output or summary.
    with exclusive_file(args.output) as target:
        try:
            summary_target = exclusive_file(summary_path)
        except BaseException:
            args.output.unlink()
            raise
        with summary_target:
            with tempfile.TemporaryDirectory(prefix='signalpost-list-') as tmp:
                try:
                    results, guard = execute(items, args, Path(tmp), previous)
                except KeyboardInterrupt:
                    cancelled = True
                    results = [failed(org, 'collection cancelled', previous.get(org), True)
                               for org in unique]
                    guard = {'cancelled': True, 'collector_failed': True}
                except Exception as error:
                    results = [failed(org, 'collector could not complete: ' + type(error).__name__,
                                      previous.get(org), True) for org in unique]
                    guard = {'collector_failed': True, 'error_type': type(error).__name__}
            if len(results) != len(unique):
                results = [failed(org, 'collector output count mismatch',
                                  previous.get(org), True) for org in unique]
                guard = {**(guard or {}), 'output_count_mismatch': True}
            accepted = {}
            rejected = 0
            for org, row in zip(unique, results):
                try:
                    correct = validate([row], [org])['structurally_valid']
                except (TypeError, ValueError, KeyError, AttributeError):
                    correct = False
                if not correct:
                    row = failed(org, 'collector envelope shape, budget or input order invalid',
                                 previous.get(org), True)
                    rejected += 1
                accepted[org] = row
            final = []
            for item in items:
                row = copy.deepcopy(accepted[item['org']]) if item['valid'] else failed(
                    item['org'], 'invalid organisation number: expected nine ASCII digits '
                    'with valid Norwegian checksum')
                state_counts = counts(row)
                outcome = ('failed' if row['run']['terminal_status'] == 'failed' else
                           'completed_with_available_claims' if state_counts['available'] else
                           'completed_without_available_claims')
                row['_cli'] = {
                    'schema': SCHEMA, 'format': FORMAT, 'mode': mode, 'search': 'none',
                    'input_index': item['index'],
                    'source_line': item['index'] if origin == 'file' else None,
                    'input_source': origin, 'raw_input': item['raw'],
                    'normalized_input': item['org'], 'duplicate_of': item['duplicate'],
                    'input_valid': item['valid'], 'outcome': outcome,
                    'observation_input_index': item['duplicate'] or item['index'],
                    'observation_reused': bool(item['valid'] and item['duplicate']),
                    'claim_status_counts': state_counts,
                }
                target.write(json.dumps(row, ensure_ascii=True, sort_keys=True,
                                        separators=(',', ':')) + '\n')
                final.append(row)
            target.flush()
            os.fsync(target.fileno())
            statuses = {state: sum(row['_cli']['claim_status_counts'][state] for row in final)
                        for state in sorted(STATES)}
            unsuccessful = sum(row['_cli']['outcome'] != 'completed_with_available_claims'
                               for row in final)
            operations = [row['operations'] for row in accepted.values()]
            summary = {
                'schema': SCHEMA, 'format': FORMAT, 'mode': mode, 'search': 'none',
                'inputs': len(items), 'outputs': len(final),
                'unique_valid_companies': len(unique),
                'duplicate_entries': sum(item['duplicate'] is not None for item in items),
                'unsuccessful_entries': unsuccessful,
                'run_terminal_status_counts': dict(collections.Counter(
                    row['run']['terminal_status'] for row in final)),
                'claim_status_counts': statuses,
                'claim_counts_include_duplicate_entries': True,
                'requests': sum(op['requests'] for op in operations),
                'requests_include_upper_bounds': any(op.get('requests_are_upper_bound', False)
                                                      for op in operations),
                'request_budget_per_unique_company': 20,
                'request_budget_total': 20 * len(unique),
                'third_party_cost_usd': 0, 'timeout_seconds': args.timeout_seconds,
                'python_version': sys.version.split()[0],
                'guard': guard, 'rejected_collector_envelopes': rejected,
                'output': str(args.output), 'summary': str(summary_path),
                'output_sha256': hashlib.sha256(args.output.read_bytes()).hexdigest(),
                'official_score': None,
                'note': 'Run completion is not evidence availability or factual accuracy.',
            }
            summary_target.write(json.dumps(summary, sort_keys=True, indent=2) + '\n')
            summary_target.flush()
            os.fsync(summary_target.fileno())
    print(json.dumps(summary, sort_keys=True), file=sys.stderr)
    if cancelled:
        return 130
    bad_guard = guard and (guard.get('collector_failed') or guard.get('wall_clock_timeout')
                           or guard.get('synthesized_failures')
                           or guard.get('output_count_mismatch')
                           or guard.get('collector_exit') != 0)
    return 2 if unsuccessful or rejected or bad_guard else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--org-list', type=Path, help='UTF-8 file: one number per physical line')
    source.add_argument('--orgs', nargs='+', help='numbers supplied directly')
    parser.add_argument('--output', type=Path, required=True, help='new JSONL artifact')
    parser.add_argument('--summary', type=Path, help='new summary JSON (default: OUTPUT.summary.json)')
    parser.add_argument('--cache', type=Path, required=True, help='retained source cache/snapshots')
    parser.add_argument('--timeout-seconds', type=float, default=2400)
    parser.add_argument('--workers', type=int, default=4)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--replay', action='store_true', help='cache only; never make HTTP requests')
    mode.add_argument('--fresh', action='store_true', help='explicit LIVE mode (the default)')
    parser.add_argument('--previous', type=Path, help='previous v0.7 JSONL envelopes for refresh')
    parser.add_argument('--registry-snapshot', type=Path, help='local frozen-registry interchange JSONL')
    parser.add_argument('--search', choices=['none'], default='none', help='free public sources only')
    args = parser.parse_args(argv)
    try:
        return run(args)
    except KeyboardInterrupt:
        print(json.dumps({'schema': SCHEMA, 'ok': False, 'error': 'cancelled'}), file=sys.stderr)
        return 130
    except (OSError, ValueError, TypeError, KeyError, RecursionError) as error:
        print(json.dumps({'schema': SCHEMA, 'ok': False,
                          'error': type(error).__name__ + ': ' + str(error)}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
