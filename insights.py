"""Short, deterministic, evidence-linked company observations, never ratings."""
import datetime as dt
import math

STATES = ('available', 'not_available', 'blocked', 'not_applicable', 'ambiguous', 'failed')


def number(value):
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    except OverflowError:
        return False


def annual(record):
    try:
        p = record['period']
        start, end = dt.date.fromisoformat(p['fraDato']), dt.date.fromisoformat(p['tilDato'])
        if start.month == 1 and start.day == 1 and end == dt.date(start.year, 12, 31):
            return start.year
    except (KeyError, TypeError, ValueError, OverflowError):
        pass
    return None


def _ids(claim):
    values = claim.get('evidence_ids', [])
    return list(dict.fromkeys(x for x in values if isinstance(x, str) and x)) if isinstance(values, list) else []


def _short(value, limit=260):
    return ' '.join(str(value).split())[:limit]


def synthesize(claims, changes=()):
    claims = [c for c in claims if isinstance(c, dict)]
    known = {c['field']: c for c in claims if isinstance(c.get('field'), str)
             and c.get('availability') == 'available' and _ids(c) and c.get('value') is not None}
    statements = []

    def add(text, fields, kind='observation', **extra):
        evidence = list(dict.fromkeys(e for f in fields for e in _ids(known[f])))
        statements.append(dict(text=text, claim_fields=fields, evidence_ids=evidence, kind=kind, **extra))

    def value(field):
        return known[field]['value']

    if 'legal_name' in known:
        add('Registered legal entity: ' + _short(value('legal_name')) + '.', ['legal_name'])
    activity_fields = [f for f in ('industry', 'activity') if f in known]
    if activity_fields:
        parts = []
        for field in activity_fields:
            v = value(field)
            if isinstance(v, dict):
                v = v.get('beskrivelse') or v.get('kode') or str(v)
            elif isinstance(v, list):
                v = '; '.join(str(x) for x in v)
            parts.append(_short(v))
        add('Registered business context: ' + '; '.join(parts) + '.', activity_fields)
    if 'employees' in known:
        add('Registry employee count: ' + str(value('employees')) + '.', ['employees'])

    for field, title in [('revenue', 'revenue'), ('net_income', 'net income'), ('equity', 'equity')]:
        key = 'financials.' + field
        if key not in known or 'financials.currency' not in known:
            continue
        period = known[key].get('reporting_period') or {}
        add(f"Latest available filed {title}: {value(key)} {value('financials.currency')}, "
            f"reporting period {period.get('fraDato', 'unknown')} to {period.get('tilDato', 'unknown')}. "
            'Historical filing, not a current balance.', [key, 'financials.currency'])

    if 'financials.history' in known:
        history = value('financials.history')
        usable = [r for r in history if isinstance(r, dict) and annual(r) is not None] if isinstance(history, list) else []
        usable.sort(key=annual)
        years = [annual(r) for r in usable]
        if len(usable) >= 2 and len(years) == len(set(years)):
            old, new = usable[-2:]
            if (annual(new) == annual(old) + 1 and old.get('currency') and old['currency'] == new.get('currency')
                    and number(old.get('revenue')) and old['revenue'] > 0 and number(new.get('revenue'))):
                change = 100 * (new['revenue'] - old['revenue']) / old['revenue']
                if math.isfinite(change):
                    add(f"Filed revenue changed by {change:+.1f}% from calendar year {annual(old)} "
                        f"to {annual(new)} ({old['revenue']} to {new['revenue']} {old['currency']}). "
                        'Calculated from consecutive calendar-year filings; not a forecast.',
                        ['financials.history'], kind='calculation',
                        calculation={'formula': '100 * (new - old) / old', 'old': old['revenue'],
                                     'new': new['revenue'], 'currency': old['currency'],
                                     'old_period': old['period'], 'new_period': new['period'], 'percent': change})

    if 'website.verified_url' in known:
        add('Website identity established against the legal entity: ' + _short(value('website.verified_url')) + '.',
            ['website.verified_url'])
    if 'website.description' in known:
        add('The checked company website describes its work as: ' + _short(value('website.description')) +
            ' This is company-declared context.', ['website.description'])
    for field, label in [('website.hiring', 'job posting'), ('website.activity', 'dated activity item')]:
        if field in known and isinstance(value(field), list):
            add(f'{len(value(field))} supported {label}(s) in the checked company sources. '
                'Check source dates and closing dates before acting.', [field])
    if 'website.contact_channels' in known and isinstance(value('website.contact_channels'), list):
        contacts = value('website.contact_channels')
        kinds = sorted({str(c.get('type')) for c in contacts if isinstance(c, dict) and c.get('type') in ('email', 'phone')})
        add(f"{len(contacts)} literal contact channel(s) published in checked company pages" +
            (' (' + ', '.join(kinds) + ')' if kinds else '') +
            '. Availability and responsiveness were not tested.', ['website.contact_channels'])
    if 'website.social_links' in known and isinstance(value('website.social_links'), list):
        add(f"{len(value('website.social_links'))} social profile link(s) declared on checked company pages. "
            'Destination ownership was not independently verified.', ['website.social_links'])

    for status in STATES[1:]:
        group = [c for c in claims if c.get('availability') == status]
        if group:
            reason = {'failed': 'Collection failed', 'blocked': 'Source access blocked',
                      'ambiguous': 'Attribution not established', 'not_available': 'Not established in checked sources',
                      'not_applicable': 'Not applicable in this observation'}[status]
            statements.append({'text': reason + ': ' + ', '.join(str(c.get('field', 'unknown')) for c in group) +
                               '. Missing data is not zero or proof of absence.',
                               'claim_fields': [c.get('field', 'unknown') for c in group],
                               'evidence_ids': list(dict.fromkeys(e for c in group for e in _ids(c))),
                               'kind': 'limitation', 'availability': status})
    unlinked = [c for c in claims if c.get('availability') == 'available' and not _ids(c)]
    unknown = [c for c in claims if c.get('availability') not in STATES]
    for group, text in [(unlinked, 'Available-labelled fields lack evidence IDs; no factual synthesis is inferred'),
                        (unknown, 'Unrecognized availability state; not treated as available')]:
        if group:
            statements.append({'text': text + ': ' + ', '.join(str(c.get('field', 'unknown')) for c in group) + '.',
                               'claim_fields': [c.get('field', 'unknown') for c in group], 'evidence_ids': [],
                               'kind': 'limitation', 'availability': 'ambiguous'})
    changes = [c for c in changes if isinstance(c, dict)]
    if changes:
        statements.append({'text': f'{len(changes)} field change(s) recorded since the last available observations. '
                           'An outage does not reset the comparison baseline. Inspect before/after evidence.',
                           'claim_fields': [c.get('field', 'unknown') for c in changes],
                           'evidence_ids': list(dict.fromkeys(e for c in changes for e in c.get('new_evidence_ids', [])
                                                            if isinstance(e, str))), 'kind': 'refresh'})
    return statements
