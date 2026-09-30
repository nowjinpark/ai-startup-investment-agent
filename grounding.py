"""최종 검수에서 추출한 원문 사실을 평가 값으로 바꾸는 보수적인 규칙.

모델의 사유 문장이나 이전 점수는 근거로 사용하지 않습니다. 이 검증은
원문 해석의 완전한 증명이 아니므로 거절한 사실도 검토 기록에 남깁니다.
"""
import re
from typing import Literal

from pydantic import BaseModel, Field

from common import compact
from models import Evidence


class GroundedFact(BaseModel):
    subject_company_id: str
    kind: Literal['effect', 'poc', 'lab', 'paid', 'contact', 'no_contact',
                  'customer_site', 'application', 'payer', 'product', 'price_unit',
                  'price_basis', 'activity', 'achievement', 'stopped']
    state: Literal['completed', 'ongoing', 'planned', 'unknown']
    entity_type: Literal['company', 'site', 'use_case', 'customer_group', 'product', 'event', 'business_model', 'other']
    label: str = Field(description='원문에 있는 고객·현장·사용 목적·사건 이름. 고객군은 고객명이 아닙니다.')
    count: int = Field(ge=0, le=100000, description='보통 1. 원문에 명시된 실제 검증 수만 2 이상 또는 0을 허용합니다.')
    event_date: str | None
    excerpt: str = Field(description='해당 사실 한 개를 직접 지지하는 원문의 짧은 연속 구절. 요약하지 않습니다.')
    evidence: list[Evidence]


class AuditedFinding(BaseModel):
    criterion_id: int = Field(ge=1, le=10)
    facts: list[GroundedFact]
    unknown_reason: str


FUTURE = re.compile(r'예정|계획|목표|추진할|확대할|진출할|넓혀.{0,45}(?:되겠다|계획)|공급할|도입할|검증할|will\b|plans?\s+to', re.I)
KINDS = {2: {'effect', 'poc', 'lab'}, 3: {'paid', 'contact', 'no_contact'},
         6: {'customer_site'}, 7: {'payer', 'product', 'price_unit', 'price_basis'},
         8: {'application'}, 10: {'activity', 'achievement', 'stopped'}}
ACTUAL = re.compile(r'검증|실증|PoC|사용|납품|도입|판매|공급|적용|운영|설치', re.I)
GROUP = re.compile(r'B2[BC]|일반\s*소비자|고객군|고객\s*유형|기업[/·및\s]*기관', re.I)


def _proof(fact, candidate, sources):
    if fact['subject_company_id'] != candidate['company_id']:
        return '다른 기업을 주체로 한 사실입니다.'
    if fact['state'] not in {'completed', 'ongoing'}:
        return '계획 또는 미확인 사실은 완료·진행 실적으로 세지 않습니다.'
    excerpt = fact['excerpt']
    if len(compact(excerpt)) < 8 or not fact['evidence']:
        return '직접 인용한 원문 구절이 필요합니다.'
    matched = False
    for item in fact['evidence']:
        source = sources.get(item['source_id'])
        if not source or source.get('company_id') != candidate['company_id']:
            return '현재 기업에 속한 원문 근거가 아닙니다.'
        if not compact(item['quote']) or compact(item['quote']) not in compact(source.get('text')):
            return '등록 원문에서 인용을 확인하지 못했습니다.'
        matched = matched or compact(excerpt) in compact(item['quote'])
    if not matched:
        return '직접 발췌가 인용 원문 안에 없습니다.'
    if FUTURE.search(excerpt):
        return '미래 계획이 포함된 발췌입니다. 완료·진행 사실의 구절을 별도로 확인해야 합니다.'
    if re.search(r'미확인|미완료|미공개|확인되지|알\s*수\s*없|하지\s*못|추정|가능성', excerpt):
        return '추정·미확인 표현을 완료 사실로 확정하지 않습니다.'
    kind = fact['kind']
    if kind == 'effect' and not re.search(r'개선|향상|단축|절감|감소|줄었|줄였|증가|정밀도|오차|효율|성능', excerpt):
        return '판매·매출만으로 고객 문제 해결 효과를 확정하지 않습니다.'
    if kind in {'poc', 'contact'} and not re.search(r'PoC|실증|검증|MOU|LOI|협약|도입\s*협의', excerpt, re.I):
        return '고객 실증 또는 도입 접점의 직접 근거가 없습니다.'
    if kind == 'lab' and not re.search(r'실험실|데모|자체\s*실험|laboratory|demo', excerpt, re.I):
        return '자체 실험·데모 단계의 직접 근거가 없습니다.'
    if kind == 'paid' and not re.search(r'유료|판매|매출|수출|공급\s*계약|수주|구매\s*계약', excerpt):
        return '단순 공급·납품을 유료 계약으로 추정하지 않습니다.'
    if kind == 'no_contact' and not re.search(r'접점.{0,10}없|고객.{0,10}없|고객\s*0', excerpt):
        return '고객 접점 부재의 명시적 근거가 없습니다.'
    if kind in {'customer_site', 'application'}:
        expected = {'company', 'site'} if kind == 'customer_site' else {'use_case'}
        if fact['entity_type'] not in expected or (kind == 'customer_site' and GROUP.search(fact['label'])):
            return '고객군·판매채널을 고객·현장 수 또는 실제 사용 목적으로 세지 않습니다.'
        if not compact(fact['label']) or compact(fact['label']) not in compact(excerpt) or not ACTUAL.search(excerpt):
            return '고객·현장·사용 목적 이름과 실제 검증의 직접 근거가 필요합니다.'
        if fact['count'] > 1 and not re.search(rf"{fact['count']}\s*(?:개|곳|건|고객|현장|산업|분야|종)", excerpt):
            return '집계 수가 원문에 명시되어 있지 않습니다.'
        if fact['count'] == 0 and not re.search(r'0\s*(?:개|곳|건)|없(?:다|음|습니다)|전무', excerpt):
            return '0건의 명시적 원문 근거가 필요합니다.'
    if kind in {'activity', 'achievement'} and not re.search(r'개발|검증|실증|공급|납품|출시|생산|운영|매출|판매|투자\s*유치|선정|수상|특허', excerpt):
        return '법인 등록이나 폐업 정보의 부재만으로 실제 활동을 확정하지 않습니다.'
    if kind == 'achievement' and (fact['state'] != 'completed' or not fact['event_date']):
        return '달성 성과에는 완료 상태와 날짜가 필요합니다.'
    if kind == 'achievement':
        year = re.match(r'20\d{2}', fact['event_date'])
        if not year or year.group() not in excerpt:
            return '성과 날짜가 직접 발췌에 없습니다.'
    if kind == 'stopped' and not re.search(r'폐업|사업\s*중단|영업\s*종료|청산', excerpt):
        return '사업 중단의 직접 근거가 없습니다.'
    return None


def derive_finding(item, candidate, sources):
    """등급 조건을 낮추지 않고 확인된 중·하 사실도 평가 값으로 만듭니다."""
    number = item['criterion_id']
    facts, rejected = [], []
    for fact in item['facts']:
        issue = _proof(fact, candidate, sources)
        if fact['kind'] not in KINDS.get(number, set()):
            issue = '해당 평가 항목에 속하지 않는 사실입니다.'
        if issue:
            rejected.append({'fact': fact, 'reason': issue})
        else:
            facts.append(fact)
    result = {'criterion_id': number, 'status': 'unknown', 'numeric_value': None,
              'category_value': None, 'items': [], 'reason': item['unknown_reason'] or '직접 확인된 평가 근거가 없습니다.',
              'evidence': [], 'grounded_facts': facts, 'rejected_facts': rejected}
    if not facts:
        if rejected:
            result['reason'] = '근거 검증: ' + rejected[0]['reason']
        return result
    by_kind = {f['kind'] for f in facts}
    if number == 2:
        result['category_value'] = 'proven' if 'effect' in by_kind else 'poc' if 'poc' in by_kind else 'lab'
    elif number == 3:
        result['category_value'] = 'paid' if 'paid' in by_kind else 'contact' if 'contact' in by_kind else 'none'
    elif number in {6, 8}:
        # 같은 이름의 재인용과 집계 수/개별 사례의 중복을 합산하지 않습니다.
        individuals = {compact(f['label']).casefold() for f in facts if f['count'] == 1}
        result['numeric_value'] = max([len(individuals)] + [f['count'] for f in facts])
    elif number == 7:
        result['items'] = [key for key in ['payer', 'product', 'price_unit', 'price_basis'] if key in by_kind]
    elif number == 10:
        achievements = {(f['event_date'], compact(f['label'])) for f in facts if f['kind'] == 'achievement'}
        dates = {date for date, _ in achievements}
        result['category_value'] = ('stopped' if 'stopped' in by_kind else
                                    'achievements_2plus' if len(dates) >= 2 else 'active')
    else:
        return result
    result['status'] = 'verified'
    result['reason'] = ' / '.join(dict.fromkeys(f['excerpt'].strip() for f in facts))
    evidence = {(e['source_id'], e['quote']): e for f in facts for e in f['evidence']}
    result['evidence'] = list(evidence.values())
    return result
