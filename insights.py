"""Deterministic, evidence-linked observations. No ratings or inferred missing facts."""
import datetime as dt
import math


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def annual(record):
    try:
        p = record['period']
        start, end = dt.date.fromisoformat(p['fraDato']), dt.date.fromisoformat(p['tilDato'])
        if start.month == 1 and start.day == 1 and end == dt.date(start.year, 12, 31):
            return start.year
    except (KeyError, TypeError, ValueError):
        pass
    return None


def synthesize(claims, changes=()):
    known = {c['field']: c for c in claims if c['availability'] == 'available'}
    statements = []

    def add(text, fields, kind='observation', **extra):
        evidence = list(dict.fromkeys(e for f in fields for e in known[f]['evidence_ids']))
        statements.append(dict(text=text, claim_fields=fields, evidence_ids=evidence, kind=kind, **extra))

    def value(field):
        return known[field]['value']

    if 'legal_name' in known:
        add('Registered legal entity: ' + str(value('legal_name')) + '.', ['legal_name'])
    if 'activity' in known:
        v = value('activity')
        add('Registered activity: ' + (' '.join(v) if isinstance(v, list) else str(v)), ['activity'])
    if 'employees' in known:
        add('Registry employee count: ' + str(value('employees')) + '.', ['employees'])

    for field, title in [('revenue', 'revenue'), ('net_income', 'net income'), ('equity', 'equity')]:
        key = 'financials.' + field
        if key not in known or 'financials.currency' not in known:
            continue
        period = known[key].get('reporting_period') or {}
        add(f"Latest available filed {title}: {value(key)} {value('financials.currency')}, "
            f"reporting period {period.get('fraDato', 'unknown')} to {period.get('tilDato', 'unknown')}. "
            'This is a historical filing, not a current balance.', [key, 'financials.currency'])

    if 'financials.history' in known:
        history = value('financials.history')
        usable = [r for r in history if isinstance(r, dict) and annual(r) is not None]
        usable.sort(key=annual)
        if len(usable) >= 2:
            a, b = usable[-2:]
            # No implicit currency conversion, partial-year annualization, zero
            # denominator, duplicate period or negative-baseline growth claim.
            if (annual(b) == annual(a) + 1 and a.get('currency') and a['currency'] == b.get('currency')
                    and number(a.get('revenue')) and a['revenue'] > 0 and number(b.get('revenue'))):
                change = 100 * (b['revenue'] - a['revenue']) / a['revenue']
                if math.isfinite(change):
                    add(f"Filed revenue changed by {change:+.1f}% from calendar year {annual(a)} "
                        f"to {annual(b)} ({a['revenue']} to {b['revenue']} {a['currency']}). "
                        'Calculated from consecutive calendar-year filings; not a forecast.',
                        ['financials.history'], kind='calculation',
                        calculation={'formula': '100 * (new - old) / old', 'old': a['revenue'],
                                     'new': b['revenue'], 'currency': a['currency'],
                                     'old_period': a['period'], 'new_period': b['period'], 'percent': change})

    if 'website.verified_url' in known:
        add('Website identity established against the legal entity: ' + str(value('website.verified_url')) + '.',
            ['website.verified_url'])
    for field, label in [('website.hiring', 'job posting'), ('website.activity', 'dated activity item')]:
        if field not in known:
            continue
        items = value(field)
        add(f'{len(items)} supported {label}(s) in the checked company sources. '
            'Check the source dates and any closing date before acting.', [field])

    # Separate observation failures from absence, and make all limitation text
    # reproducible from the claim state rather than a model's speculation.
    unavailable = [c for c in claims if c['availability'] != 'available']
    for status in ('failed', 'blocked', 'ambiguous', 'not_available', 'not_applicable'):
        fields = [c['field'] for c in unavailable if c['availability'] == status]
        if not fields:
            continue
        reason = {'failed': 'Collection failed', 'blocked': 'Source access blocked',
                  'ambiguous': 'Attribution not established', 'not_available': 'Not established in checked sources',
                  'not_applicable': 'Not applicable in this observation'}[status]
        statements.append({'text': reason + ': ' + ', '.join(fields) + '. Missing data is not zero or proof of absence.',
                           'claim_fields': fields, 'evidence_ids': [], 'kind': 'limitation', 'availability': status})
    if changes:
        statements.append({'text': f'{len(changes)} supported field change(s) since the last available observations. '
                            'An outage does not reset the comparison baseline. See the before/after evidence.',
                           'claim_fields': [c['field'] for c in changes],
                           'evidence_ids': list(dict.fromkeys(e for c in changes for e in c['new_evidence_ids'])),
                           'kind': 'refresh'})
    return statements
