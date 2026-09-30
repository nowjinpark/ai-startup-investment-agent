from copy import deepcopy

import pytest

from evidence_audit import audit
from test_investment import records


def answer_for(tech, market):
    risk = tech['details']
    facts = []
    for finding in tech['findings'] + market['findings']:
        number = finding['criterion_id']
        kinds = {2: ['effect'], 3: ['paid'], 6: ['customer_site'], 7: finding['items'], 8: ['application'], 10: ['activity']}[number]
        label = {6: '고객사', 8: '물류 운반'}.get(number, '확인된 사실')
        facts.append({'criterion_id': number, 'unknown_reason': '', 'facts': [
            {'subject_company_id': tech['company_id'], 'kind': kind, 'state': 'completed',
             'entity_type': 'site' if number == 6 else 'use_case' if number == 8 else 'event',
             'label': label, 'count': 1, 'event_date': None,
             'excerpt': finding['evidence'][0]['quote'], 'evidence': deepcopy(finding['evidence'])} for kind in kinds]})
    return {'findings': facts,
            'critical_risk': risk['critical_risk'], 'critical_risk_reason': risk['critical_risk_reason'],
            'critical_risk_evidence': deepcopy(risk['critical_risk_evidence']),
            'market_size_supported': False, 'competitors': []}


class Runtime:
    def __init__(self, answer=None, error=None):
        self.answer, self.error, self.calls = answer, error, []

    def ask(self, schema, instructions, payload, **options):
        self.calls.append((schema.__name__, payload, options))
        if self.error:
            raise self.error
        return deepcopy(self.answer)


def test_audit_uses_literal_proof_and_does_not_mutate_inputs(records):
    candidate, tech, market = records
    old = deepcopy(records)
    rt = Runtime(answer_for(tech, market))
    new_tech, new_market = audit(rt, candidate, tech, market)
    assert records == old
    assert new_tech['audit_status'] == 'completed'
    assert [f['criterion_id'] for f in new_tech['findings']] == [2, 10]
    assert [f['criterion_id'] for f in new_market['findings']] == [3, 6, 7, 8]
    assert rt.calls[0][2] == {'model': 'gpt-4.1', 'max_tokens': 6144}
    assert 'total_score' not in new_tech


def test_audit_can_recover_supported_middle_grade(records):
    candidate, tech, market = records
    response = answer_for(tech, market)
    tech['findings'][0].update(status='unknown', reason='독립 개선 수치 없음')
    quote = '고객 현장에서 무료 PoC를 진행하고 있습니다.'
    tech['sources'][0]['text'] += '\n' + quote
    response['findings'][0]['facts'][0].update(kind='poc', excerpt=quote, evidence=[{'source_id': 'tech', 'quote': quote}])
    result, _ = audit(Runtime(response), candidate, tech, market)
    assert result['findings'][0]['status'] == 'verified'
    assert result['findings'][0]['category_value'] == 'poc'


@pytest.mark.parametrize('change', ['forged_quote', 'other_company', 'sector_for_customer'])
def test_audit_rejects_unregistered_or_wrong_owner_proof(records, change):
    candidate, tech, market = records
    response = answer_for(tech, market)
    target = response['findings'][0]
    if change == 'forged_quote':
        target['facts'][0]['evidence'][0]['quote'] = '원문에 없는 비용 개선을 확인했습니다.'
    elif change == 'other_company':
        tech['sources'][0]['company_id'] = 'other'
    else:
        tech['sources'][0]['company_id'] = '__sector__'
    result, _ = audit(Runtime(response), candidate, tech, market)
    assert result['findings'][0]['status'] == 'unknown'
    if change != 'forged_quote':
        assert result['details']['critical_risk'] is None


def test_audit_failure_never_falls_back_to_previous_verified_results(records):
    candidate, tech, market = records
    result = audit(Runtime(error=TimeoutError()), candidate, tech, market)
    assert all(f['status'] == 'unknown' for a in result for f in a['findings'])
    assert result[0]['details']['critical_risk'] is None
    assert all(a['audit_status'] == 'failed' for a in result)
    assert all(a['audit_error']['type'] == 'TimeoutError' for a in result)


def test_audit_unknown_duplicate_and_missing_are_not_approved(records):
    candidate, tech, market = records
    response = answer_for(tech, market)
    response['findings'][0]['facts'] = []
    response['findings'].append(deepcopy(next(f for f in response['findings'] if f['criterion_id'] == 3)))
    response['findings'] = [f for f in response['findings'] if f['criterion_id'] != 10]
    results = audit(Runtime(response), candidate, tech, market)
    by_id = {f['criterion_id']: f for result in results for f in result['findings']}
    assert all(by_id[number]['status'] == 'unknown' for number in [2, 3, 10])


def test_audit_does_not_call_model_for_stale_round(records):
    candidate, tech, market = records
    tech['round_id'] = 2
    rt = Runtime(answer_for(tech, market))
    result = audit(rt, candidate, tech, market)
    assert rt.calls == []
    assert all(a['audit_status'] == 'failed' for a in result)


def test_removed_criteria_are_not_returned_or_sent_as_scoring_rules(records):
    candidate, tech, market = records
    response = answer_for(tech, market)
    for number in [1, 4, 5, 9]:
        extra = deepcopy(response['findings'][0])
        extra['criterion_id'] = number
        response['findings'].append(extra)
    runtime = Runtime(response)
    result = audit(runtime, candidate, tech, market)
    assert {f['criterion_id'] for a in result for f in a['findings']} == {2, 3, 6, 7, 8, 10}
    assert {r['id'] for r in runtime.calls[0][1]['rules']} == {2, 3, 6, 7, 8, 10}
