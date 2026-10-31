"""Additive adapter for the public OUTPUT_CONTRACT.md (downloaded 2026-10-31).

confidence is a conservative rule score, not a measured probability. Legacy
fields remain available; official_website aliases website.verified_url only.
"""
import copy
import hashlib


def complete_envelope(row):
    run = row['run']
    run.setdefault('started_at', run.get('completed_at'))
    run.setdefault('run_id', hashlib.sha256((str(row['organisation_number']) + ':' +
                                            str(run['started_at'])).encode()).hexdigest()[:24])
    for claim in row['claims']:
        claim.setdefault('confidence', 0.9 if claim['availability'] == 'available' else 0.0)
        claim.setdefault('confidence_method', 'uncalibrated deterministic rule score; not statistical precision')
    if not any(c['field'] == 'official_website' for c in row['claims']):
        website = next((c for c in row['claims'] if c['field'] == 'website.verified_url'), None)
        if website:
            alias = copy.deepcopy(website)
            alias['field'] = 'official_website'
            alias['alias_of'] = 'website.verified_url'
            row['claims'].append(alias)
    for evidence in row['evidence']:
        evidence.setdefault('source_class', 'unclassified')
        evidence.setdefault('claim_span', '')
    row['operations'].setdefault('runtime_ms', 0)
    return row


def contract_errors(row):
    errors = []
    for key, kind in {'organisation_number': str, 'run': dict, 'claims': list,
                      'evidence': list, 'changes': list, 'errors': list, 'operations': dict}.items():
        if not isinstance(row.get(key), kind):
            errors.append('missing or invalid ' + key)
    if errors:
        return errors
    for key in ('run_id', 'started_at', 'completed_at', 'terminal_status'):
        if not isinstance(row['run'].get(key), str):
            errors.append('missing run.' + key)
    for claim in row['claims']:
        if type(claim.get('confidence')) not in (float, int) or not 0 <= claim['confidence'] <= 1:
            errors.append('missing or invalid claim.confidence')
    for evidence in row['evidence']:
        for key in ('id', 'source_url', 'source_class', 'retrieved_at', 'content_sha256', 'claim_span'):
            if not isinstance(evidence.get(key), str):
                errors.append('missing evidence.' + key)
    for key in ('requests', 'runtime_ms', 'third_party_cost_usd'):
        if key not in row['operations']:
            errors.append('missing operations.' + key)
    return errors
