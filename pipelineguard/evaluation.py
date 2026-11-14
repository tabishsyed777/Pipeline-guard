"""Replay an already chosen plan on independently authored fixture cases."""
from .core import InputError, analyze, apply_plan, fingerprint, validate_contract


def verify(contract, plan, cases):
    validate_contract(contract)
    if not isinstance(cases, list) or not cases:
        raise InputError('Verification requires a nonempty case list')
    results = []
    names = set()
    for case in cases:
        if not isinstance(case, dict) or set(case) != {'name', 'headers', 'rows', 'expected_status', 'expected_outputs'}:
            raise InputError('Invalid verification case fields')
        if not isinstance(case['name'], str) or case['name'] in names:
            raise InputError('Case names must be distinct strings')
        names.add(case['name'])
        if case['expected_status'] not in ('passed', 'failed'):
            raise InputError('Expected status must be passed or failed')
        if not isinstance(case['headers'], list) or not case['headers'] or any(not isinstance(h, str) or not h for h in case['headers']) or len(set(case['headers'])) != len(case['headers']):
            raise InputError('Invalid verification headers')
        if not isinstance(case['rows'], list) or any(not isinstance(r, dict) or set(r) != set(case['headers']) or any(not isinstance(v, str) for v in r.values()) for r in case['rows']):
            raise InputError('Invalid verification rows')
        if not isinstance(case['expected_outputs'], list) or len(case['expected_outputs']) != len(case['rows']):
            raise InputError('Each input row requires an explicit expected output map')
        allowed_outputs = {t['output'] for t in contract.get('transforms', [])}
        if any(not isinstance(row, dict) or set(row) != allowed_outputs or any(not isinstance(v, (str, type(None))) for v in row.values()) for row in case['expected_outputs']):
            raise InputError('Expected output maps must cover every transform (null means unavailable)')
        headers, rows = apply_plan(case['headers'], case['rows'], contract, plan)
        result = analyze(headers, rows, contract)
        actual = [{name: row.get(name) for name in allowed_outputs} for row in result['computed_rows']]
        passed = result['status'] == case['expected_status'] and actual == case['expected_outputs']
        results.append({'name': case['name'], 'passed': passed, 'expected_status': case['expected_status'],
                        'actual_status': result['status'], 'outputs_match': actual == case['expected_outputs'],
                        'finding_codes': sorted({f['code'] for f in result['findings']})})
    return {'title': 'Held-out repair verification', 'status': 'passed' if all(r['passed'] for r in results) else 'failed',
            'case_count': len(results), 'passed_cases': sum(r['passed'] for r in results),
            'cases_sha256': fingerprint(cases), 'plan_sha256': fingerprint(plan), 'cases': results,
            'scope': 'Synthetic fixtures. Expected answers are checked after plan selection; not a hidden or secure benchmark.'}
