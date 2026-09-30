from copy import deepcopy

import pytest

from grounding import AuditedFinding, derive_finding


def fact(text, kind, label='사례', **changes):
    result = {'subject_company_id': 'target', 'kind': kind, 'state': 'completed',
              'entity_type': 'event', 'label': label, 'count': 1, 'event_date': None,
              'excerpt': text, 'evidence': [{'source_id': 's', 'quote': text}]}
    result.update(changes)
    return result


def derive(number, facts, reason='', text=None):
    item = AuditedFinding(criterion_id=number, facts=facts, unknown_reason=reason).model_dump()
    source = {'source_id': 's', 'company_id': 'target', 'text': text or '\n'.join(f['excerpt'] for f in facts)}
    return derive_finding(item, {'company_id': 'target', 'name': '대상기업'}, {'s': source})


def test_contact_is_medium_even_when_payment_is_not_public():
    text = '대상기업은 고객 A와 MOU 체결 이후 실제 공동 실증을 진행 중이다.'
    result = derive(3, [fact(text, 'contact', state='ongoing')], '유료 여부는 미공개입니다.')
    assert result['status'] == 'verified' and result['category_value'] == 'contact'
    assert result['evidence'][0]['quote'] == text


def test_single_verified_site_is_kept_without_requiring_two_sites():
    text = '가장 어려운 조선소 현장에서 먼저 검증을 마쳤다.'
    result = derive(6, [fact(text, 'customer_site', '조선소', entity_type='site')])
    assert result['numeric_value'] == 1


def test_two_known_business_elements_are_not_lost_with_undisclosed_prices():
    text = '물류 기업 고객에게 운반 로봇을 판매했다.'
    result = derive(7, [fact(text, 'payer', '물류 기업'), fact(text, 'product', '운반 로봇')], '가격은 공개되지 않았습니다.')
    assert result['items'] == ['payer', 'product'] and result['status'] == 'verified'


@pytest.mark.parametrize('state', ['planned', 'completed'])
def test_future_delivery_is_not_completed_application_even_if_model_mislabels_state(state):
    text = '연구용 휴머노이드를 연구기관에 공급할 계획이며 실증을 추진할 예정이다.'
    result = derive(8, [fact(text, 'application', '연구용', state=state, entity_type='use_case')])
    assert result['status'] == 'unknown'
    assert result['rejected_facts']


def test_existing_application_survives_rejection_of_expansion_plan():
    done = '조선소 용접 현장에서 로봇 검증을 마쳤다.'
    plan = '자동차 부품 공장으로 적용 범위를 확대할 계획이다.'
    result = derive(8, [fact(done, 'application', '조선소 용접', entity_type='use_case'),
                        fact(plan, 'application', '자동차 부품', entity_type='use_case')])
    assert result['numeric_value'] == 1 and len(result['rejected_facts']) == 1


@pytest.mark.parametrize('entity,label', [('customer_group', '소비자'), ('company', 'B2B'), ('site', '일반 소비자')])
def test_customer_group_is_not_a_verified_customer_count(entity, label):
    text = f'{label} 시장에서 로봇을 공급하고 사용하고 있다.'
    result = derive(6, [fact(text, 'customer_site', label, entity_type=entity)])
    assert result['status'] == 'unknown'


def test_duplicate_site_quotes_and_aggregate_are_not_added_twice():
    text = '고객사 2곳에서 실제 현장 실증을 완료했으며 A물류가 참여했다.'
    facts = [fact(text, 'customer_site', '고객사', count=2, entity_type='site'),
             fact(text, 'customer_site', 'A물류', entity_type='company')]
    result = derive(6, facts + deepcopy(facts))
    assert result['numeric_value'] == 2


def test_model_count_without_explicit_number_is_not_accepted():
    text = 'A물류 현장에서 실제 실증을 진행했다.'
    result = derive(6, [fact(text, 'customer_site', 'A물류', count=2, entity_type='company')])
    assert result['status'] == 'unknown'


def test_explicit_zero_is_kept_but_missing_information_is_not_zero():
    text = '실제 현장 실증을 진행한 고객은 0곳입니다.'
    assert derive(6, [fact(text, 'customer_site', '고객', count=0, entity_type='site')])['numeric_value'] == 0
    unknown = '현장 실증을 진행한 고객 수는 미공개입니다.'
    assert derive(6, [fact(unknown, 'customer_site', '고객', count=0, entity_type='site')])['status'] == 'unknown'


def test_other_company_fact_cannot_use_target_company_source():
    text = '다른기업은 고객 현장 생산성을 20% 개선했다.'
    result = derive(2, [fact(text, 'effect', subject_company_id='other')])
    assert result['status'] == 'unknown'


def test_reason_does_not_create_a_fact_or_override_missing_proof():
    assert derive(3, [], '실제로 유료 판매를 완료했습니다.')['status'] == 'unknown'
    result = derive(2, [fact('생산성이 20% 개선되었다고 가정했습니다.', 'effect')], text='원문은 개선 결과를 발표하지 않았다.')
    assert result['status'] == 'unknown'


@pytest.mark.parametrize('kind,text', [('activity', '법인 등록이 확인되며 폐업 정보는 없습니다.'),
                                     ('effect', '연간 매출 20억원과 로봇 판매가 확인됩니다.')])
def test_registration_is_not_activity_and_sales_are_not_problem_improvement(kind, text):
    result = derive(10 if kind == 'activity' else 2, [fact(text, kind)])
    assert result['status'] == 'unknown'


def test_completed_achievements_need_distinct_dates_and_source_dates():
    one = '2025년 3월 제품 출시를 완료했다.'
    two = '2026년 4월 고객에게 로봇 납품을 완료했다.'
    facts = [fact(one, 'achievement', '제품 출시', event_date='2025-03'),
             fact(two, 'achievement', '로봇 납품', event_date='2026-04')]
    assert derive(10, facts)['category_value'] == 'achievements_2plus'
    facts[1]['event_date'] = '2027-04'
    assert derive(10, facts)['category_value'] == 'active'
