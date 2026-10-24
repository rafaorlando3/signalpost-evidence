"""Portable, untrusted-data-safe reports. No network requests or input deduplication."""
from __future__ import annotations
import hashlib
import html
import json
import os
from pathlib import Path
import re
import stat
from urllib.parse import quote, urlsplit
from insights import STATES, synthesize


def _text(value):
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _plain(value):
    return ''.join(c if c >= ' ' and c != '\x7f' else ' ' for c in _text(value))


def _md(value):
    text = html.escape(_plain(value), quote=False)
    return re.sub(r'([\\`*_{}\[\]()#+.!|>~=-])', r'\\\1', text)


def _url(value):
    if not isinstance(value, str) or not value or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value) or '\\' in value:
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
            return None
        if parsed.port is not None and not 0 < parsed.port <= 65535:
            return None
    except (ValueError, UnicodeError):
        return None
    return quote(value, safe=':/?#@!$&*+,;=%~.-_')


def _link(value, label=None):
    url = _url(value)
    if not url:
        return _md(value) + ' (link withheld: unsafe or unsupported URL)'
    return '[' + _md(label if label is not None else value) + '](<' + url + '>)'


def _refs(ids):
    ids = ids if isinstance(ids, list) else []
    return ', '.join(_md(x) for x in dict.fromkeys(x for x in ids if isinstance(x, str))) or 'none'


def _claims(row):
    values = row.get('claims', [])
    return [c for c in values if isinstance(c, dict)] if isinstance(values, list) else []


def _evidence(row):
    found = {}
    seen = set()
    current = row
    org = row.get('organisation_number')
    while isinstance(current, dict) and id(current) not in seen:
        seen.add(id(current))
        if current.get('organisation_number') != org:
            break
        for evidence in current.get('evidence', []) if isinstance(current.get('evidence', []), list) else []:
            if isinstance(evidence, dict) and isinstance(evidence.get('id'), str):
                found.setdefault(evidence['id'], evidence)
        current = current.get('previous_snapshot')
    return found


def _summary(row, evidence):
    changes = row.get('changes', [])
    changes = changes if isinstance(changes, list) else []
    statements = synthesize(_claims(row), changes)
    result = []
    for statement in statements:
        ids = statement.get('evidence_ids', [])
        unresolved = [e for e in ids if e not in evidence]
        if statement['kind'] != 'limitation' and (not ids or unresolved):
            result.append({'kind': 'limitation', 'text': 'Factual synthesis withheld: evidence references are unresolved.',
                           'claim_fields': statement.get('claim_fields', []), 'evidence_ids': ids})
        else:
            result.append(statement)
    return result


def _counts(row):
    return {state: sum(c.get('availability') == state for c in _claims(row)) for state in STATES}


def _name(row):
    for claim in _claims(row):
        if claim.get('field') == 'legal_name' and claim.get('availability') == 'available' and claim.get('value') is not None:
            return _plain(claim['value'])
    return 'Company ' + _plain(row.get('organisation_number', 'unknown'))


def _state(row):
    run = row.get('run') if isinstance(row.get('run'), dict) else {}
    return run.get('terminal_status') or row.get('input_status') or row.get('status') or 'unknown'


def _filename(index, row):
    org = str(row.get('organisation_number', ''))
    return f'{index:05d}-' + (org if re.fullmatch(r'[0-9]{9}', org, flags=re.ASCII) else 'invalid-org') + '.md'


def _audit_hash(row):
    return hashlib.sha256(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()


def _markdown(row, index, filename):
    evidence = _evidence(row)
    summary = _summary(row, evidence)
    lines = ['# ' + _md(_name(row)), '', '[All entries](index.md)', '',
             '- Input position: ' + str(index), '- Organisation number: ' + _md(row.get('organisation_number', 'unknown')),
             '- Entry status: ' + _md(_state(row)), '- Report file: ' + _md(filename),
             '- Canonical input SHA256: ' + _audit_hash(row),
             '- Run: ' + _md(row.get('run', {})), '- Refresh: ' + _md(row.get('refresh', {})), '', '## Short synthesis', '']
    if not summary:
        lines.append('No evidence-linked factual synthesis available. Unknown is not zero or proof of absence.')
    for statement in summary:
        lines.append('- ' + _md(statement['text']) + ' Evidence IDs: ' + _refs(statement.get('evidence_ids')) + '.')
        if statement.get('calculation'):
            lines.append('  Calculation audit: ' + _md(statement['calculation']))
    lines += ['', '## Availability and limits', '',
              'All six states are distinct. An unknown state remains unknown; failed collection does not show absence.', '',
              '| State | Fields |', '| --- | ---: |']
    lines += ['| ' + state + ' | ' + str(count) + ' |' for state, count in _counts(row).items()]
    unknown = [c for c in _claims(row) if c.get('availability') not in STATES]
    if unknown:
        lines += ['', 'Unrecognized states: ' + _md([{'field': c.get('field'), 'availability': c.get('availability')} for c in unknown])]
    lines += ['', 'Collection errors: ' + _md(row.get('errors', [])), '', '## Facts and source references', '']
    if not _claims(row):
        lines.append('No collected claims. This entry remains in its original input position.')
    for claim in _claims(row):
        availability = claim.get('availability', 'unknown')
        lines += ['### ' + _md(claim.get('field', 'unknown')), '', '- State: ' + _md(availability),
                  '- Value: ' + _md(claim.get('value') if availability == 'available' else None),
                  '- Reporting period: ' + _md(claim.get('reporting_period')),
                  '- Evidence IDs: ' + _refs(claim.get('evidence_ids'))]
        unresolved = [x for x in claim.get('evidence_ids', []) if isinstance(x, str) and x not in evidence]
        if unresolved:
            lines.append('- Unresolved evidence IDs: ' + _refs(unresolved))
        for key in ('source_pointer', 'evidence_excerpt', 'identity_support'):
            if claim.get(key) is not None:
                lines.append('- ' + key.replace('_', ' ').capitalize() + ': ' + _md(claim[key]))
        extra_metadata = {key: value for key, value in claim.items() if key not in
                          ('field', 'availability', 'value', 'reporting_period', 'evidence_ids',
                           'source_pointer', 'evidence_excerpt', 'identity_support')}
        if extra_metadata:
            lines.append('- Additional claim metadata: ' + _md(extra_metadata))
        if claim.get('field') in ('website.social_links', 'website.contact_channels', 'website.hiring', 'website.activity') and isinstance(claim.get('value'), list):
            for item in claim['value']:
                if isinstance(item, dict):
                    for key in ('url', 'source_url'):
                        if item.get(key):
                            lines.append('- Context source: ' + _link(item[key]))
        lines.append('')
    lines += ['## Changes and comparison limits', '',
              'Compare periods, currencies and before/after evidence. Missing or failed observations do not prove stability.']
    changes = row.get('changes', []) if isinstance(row.get('changes', []), list) else []
    if not changes:
        lines.append('No recorded supported change in this observation; this does not establish that the company was unchanged.')
    for change in changes:
        if not isinstance(change, dict):
            continue
        lines += ['', '### ' + _md(change.get('field', 'unknown')),
                  '- Previous value: ' + _md(change.get('old_value')),
                  '- Previous period: ' + _md(change.get('old_period')),
                  '- Previous evidence IDs: ' + _refs(change.get('old_evidence_ids')),
                  '- Current value: ' + _md(change.get('new_value')),
                  '- Current period: ' + _md(change.get('new_period')),
                  '- Current evidence IDs: ' + _refs(change.get('new_evidence_ids'))]
    lines += ['', '## Evidence audit', '']
    if not evidence:
        lines.append('No evidence records available. Referenced but unresolved IDs are explicitly marked above.')
    for eid, source in evidence.items():
        lines += ['### Evidence ' + _md(eid), '', '- Source: ' + _link(source.get('source_url', 'unknown')),
                  '- Retrieved at: ' + _md(source.get('retrieved_at', 'unknown')),
                  '- Content SHA256: ' + _md(source.get('content_sha256', 'unknown')),
                  '- Source class: ' + _md(source.get('source_class', 'unknown'))]
        for key in ('retained_text_sha256', 'excerpt', 'cache_file', 'snapshot_file'):
            if source.get(key) is not None:
                lines.append('- ' + key.replace('_', ' ').capitalize() + ': ' + _md(source[key]))
        lines.append('')
    lines += ['## Additional audit metadata', '', _md({k: v for k, v in row.items() if k not in
              ('claims', 'evidence', 'changes', 'synthesis', 'previous_snapshot', 'run', 'refresh', 'errors')}), '',
              'Historical filings are not live balances. Company-declared context is attributed, not independently endorsed.',
              'No ranking, prediction, contact test or official competition score is inferred.', '']
    return '\n'.join(lines)


def _index(rows, entries):
    lines = ['# Signalpost company review', '',
             f'{len(rows)} input entries, preserved in input order, including duplicate and invalid entries.', '',
             '[Interactive HTML index](index.html)', '', '[Compare companies and inspect evidence](workspace.html)', '',
             '| Input | Company | Organisation | Status | Report |', '| ---: | --- | --- | --- | --- |']
    for index, (row, filename) in enumerate(zip(rows, entries), 1):
        lines.append(f'| {index} | {_md(_name(row))} | {_md(row.get("organisation_number", "unknown"))} | {_md(_state(row))} | [Open]({filename}) |')
    lines += ['', 'States: ' + ', '.join(STATES) + '.',
              'Unknown states remain unknown. All dates, IDs, source URLs and content hashes are available in each entry.',
              'No inferred absence, current balance, ranking or automatic business recommendation.', '']
    return '\n'.join(lines)


def _html(rows, entries):
    esc = lambda v: html.escape(_plain(v), quote=True)
    parts = ['<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
             '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; script-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">',
             '<title>Signalpost company review</title><style>body{font:16px/1.6 system-ui;max-width:1000px;margin:auto;padding:24px;color:#183d36}input{padding:10px;width:100%;box-sizing:border-box}article{border:1px solid #cadbd4;border-radius:8px;padding:18px;margin:18px 0;overflow-wrap:anywhere}small{color:#536761}a{color:#175f4d}.limits{background:#fff8e6;padding:10px}li{margin:8px 0}[hidden]{display:none}</style>',
             '<h1>Signalpost company review</h1><p>' + str(len(rows)) + ' input entries, preserved in input order. Duplicate and invalid entries remain visible.</p>',
             '<p><a href="workspace.html">Compare companies and inspect evidence</a></p><label for="query">Find company, organisation number or entry status</label><input id="query" type="search" autocomplete="off">',
             '<p id="count" aria-live="polite"></p><p>Six states: ' + ', '.join(STATES) + '. Unknown remains unknown.</p>']
    for index, (row, filename) in enumerate(zip(rows, entries), 1):
        parts += ['<article><small>Input ' + str(index) + ' · ' + esc(row.get('organisation_number', 'unknown')) + ' · ' + esc(_state(row)) + '</small>',
                  '<h2>' + esc(_name(row)) + '</h2><ul>']
        for statement in _summary(row, _evidence(row)):
            parts.append('<li' + (' class="limits"' if statement['kind'] == 'limitation' else '') + '>' + esc(statement['text']) +
                         '<br><small>Evidence IDs: ' + esc(', '.join(statement.get('evidence_ids', [])) or 'none') + '</small></li>')
        parts += ['</ul><p>States: ' + esc(_counts(row)) + '</p>',
                  '<p><a href="' + filename + '">Full readable report, changes and evidence audit</a></p>',
                  '<small>Input SHA256: ' + _audit_hash(row) + '</small></article>']
    parts += ['<footer>Historical filings are not live balances. Source gaps do not establish absence or business quality. Social links are company-declared; ownership is not independently verified.</footer>',
              '<script>const q=document.getElementById("query"),cards=[...document.querySelectorAll("article")],count=document.getElementById("count");function filter(){const value=q.value.toLocaleLowerCase();let n=0;for(const card of cards){card.hidden=!card.textContent.toLocaleLowerCase().includes(value);if(!card.hidden)n++;}count.textContent=n+" entries shown";}q.addEventListener("input",filter);filter();</script></html>']
    return '\n'.join(parts)


def _workspace_row(row):
    # Presentation defaults for invalid entries are not promoted to factual claims.
    view = dict(row)
    view['organisation_number'] = str(row.get('organisation_number', 'unknown'))
    for key in ('claims', 'evidence', 'changes', 'errors'):
        view[key] = row.get(key) if isinstance(row.get(key), list) else []
    view['claims'] = [c for c in view['claims'] if isinstance(c, dict)]
    view['run'] = row.get('run') if isinstance(row.get('run'), dict) else {'terminal_status': _state(row)}
    view['previous_snapshot'] = row.get('previous_snapshot') if isinstance(row.get('previous_snapshot'), dict) else None
    view['synthesis'] = _summary(row, _evidence(row))
    operations = dict(row.get('operations')) if isinstance(row.get('operations'), dict) else {}
    for key in ('requests', 'cache_hits'):
        if not isinstance(operations.get(key), (int, float)) or isinstance(operations.get(key), bool):
            operations[key] = 0  # An invalid entry generated no collection operation here.
    operations.setdefault('third_party_cost_usd', None)
    view['operations'] = operations
    return view


def _new_directory(directory):
    directory = Path(os.path.abspath(os.fspath(directory)))
    if directory.name in ('', '.', '..'):
        raise ValueError('A new report directory is required')
    for parent in [*reversed(directory.parents), directory]:
        try:
            mode = parent.lstat().st_mode
        except FileNotFoundError:
            if parent != directory:
                raise FileNotFoundError('Report parent directory must exist')
            continue
        if stat.S_ISLNK(mode):
            raise ValueError('Symlink report paths are not permitted')
        if parent == directory:
            raise FileExistsError('Report directory already exists; refusing overwrite')
        if not stat.S_ISDIR(mode):
            raise NotADirectoryError('Report parent is not a directory')
    directory.mkdir(mode=0o700)
    return directory


def write_reports(rows, directory):
    """Create a fresh private directory. Raises on existing/symlink paths; never writes inputs."""
    rows = [dict(row) if isinstance(row, dict) else {'raw_input': row, 'input_status': 'invalid', 'claims': [],
            'errors': [{'reason': 'Input entry is not an object'}]} for row in rows]
    entries = [_filename(index, row) for index, row in enumerate(rows, 1)]
    # Prepare all content before creating output, so serialization errors leave no partial report.
    documents = {filename: _markdown(row, index, filename) for index, (row, filename) in enumerate(zip(rows, entries), 1)}
    documents['index.md'] = _index(rows, entries)
    documents['index.html'] = _html(rows, entries)
    from report import build
    documents['workspace.html'] = build([_workspace_row(row) for row in rows])
    destination = _new_directory(directory)
    for filename, content in documents.items():
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
        fd = os.open(destination / filename, flags, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as target:
            target.write(content)
    return {'state': 'completed', 'status': 'written', 'index_path': str(destination / 'index.md'),
            'html_path': str(destination / 'index.html'), 'count': len(rows),
            'files': entries + ['index.md', 'index.html', 'workspace.html']}
