import json

from common import ROOT, review_findings, review_details
from models import TechnologyOutput


CRITERIA = [2, 10]

QUESTIONS = [
    '고객 현장에서 성능 비용 생산성이 개선된 수치와 시험 조건',
    '핵심 제품 기술 작동 원리 실제 적용 방식',
    'CEO CTO 관련 연구 산업 경력 연도',
    '기술 운영 안전 규제 위험 인증 실패 사례와 해결 조치',
    '현재 사업 참여 지속 활동 서로 다른 날짜 실제 달성 성과',
]

_PROMPT = (
    '기술 분석 담당입니다. findings에는 2번 문제 해결 효과와 10번 실행 지속성만 추출합니다. 점수는 코드가 계산합니다. '
    'rules의 사실·등급 정의에 맞춰 실제 인용을 반환합니다. 자사 주장과 외부 검증, 실험실과 고객 환경을 구분합니다. '
    'problem_stage는 proven/poc/lab, execution은 achievements_2plus/active/stopped입니다. '
    '안전 인증만으로 고객의 생산성·비용 개선을 입증하지 않습니다. 미래 계획을 완료 성과로 쓰지 않습니다. '
    '매출·판매량은 고객의 실제 문제 해결 효과와 다릅니다. 개선이 미확인이어도 고객 환경 PoC·실증이면 poc로 남깁니다. '
    '법인 등재나 폐업 정보가 없다는 사실만으로 실제 개발·검증·공급 활동을 확정하지 않습니다. '
    '기술·창업팀·위험은 별도 정성 설명입니다. 특허 수·경력 연수·위험 대응 점수를 만들지 않습니다. '
    'technology_evidence와 team_evidence에 각 설명의 원문 근거를 붙이며 자료가 없으면 확인 필요로 기록합니다. '
    '중대한 미해결 위험의 발생·지속이 확인되면 critical_risk=true, 대응 근거가 있으면 false, 자료 부족이면 null입니다. '
    '각 finding은 status,numeric_value,category_value,items,reason,evidence로 반환합니다.'
)

_DETAIL_FIELDS = {
    13: 'technology',
    14: 'team',
}

_INSUFFICIENT = {
    'status': 'insufficient',
    'summary': '기술 자료 미확인',
    'findings': [],
    'sources': [],
    'details': {},
    'risks': [],
    'missing': ['기술 분석 자료'],
    'error': None,
}


def _build_risk_items(result):
    return [
        {
            'criterion_id': 11,
            'claim': {
                'critical_risk': result['critical_risk'],
                'reason': result['critical_risk_reason'],
            },
            'evidence': result['critical_risk_evidence'],
        },
        {
            'criterion_id': 13,
            'claim': result['technology'],
            'evidence': result.get('technology_evidence', []),
        },
        {
            'criterion_id': 14,
            'claim': result['team'],
            'evidence': result.get('team_evidence', []),
        },
    ]


def _apply_risk_check(result, risk_check):
    if 11 not in risk_check:
        result['critical_risk'] = None
        result['critical_risk_reason'] = '중대한 위험 또는 대응 근거를 추가 확인해야 합니다.'
        result['critical_risk_evidence'] = []

    for criterion_id, field in _DETAIL_FIELDS.items():
        if criterion_id not in risk_check:
            result[field] = '확인 필요'
            result[field + '_evidence'] = []


def run(runtime, candidate, round_id):
    cid = candidate['company_id']
    name = candidate['name']

    queries = [f'{name} {q}' for q in QUESTIONS]
    chunks = runtime.corpus.evidence_for(queries, cid, 'technology')
    sources = runtime.corpus.source_pages(chunks)

    rubric = json.loads((ROOT / 'config/rubric.json').read_text(encoding='utf-8'))

    if not chunks:
        return {**_INSUFFICIENT, 'company_id': cid, 'round_id': round_id, 'rubric_version': rubric['version']}

    rules = [r for r in rubric['criteria'] if r['id'] in CRITERIA]

    result = runtime.ask(
        TechnologyOutput,
        _PROMPT,
        {'company': name, 'overview': candidate.get('overview', ''), 'rules': rules, 'sources': chunks},
    )

    result['findings'] = review_findings(
        runtime,
        candidate,
        [f for f in result['findings'] if f['criterion_id'] in CRITERIA],
        sources,
    )

    risk_items = _build_risk_items(result)
    risk_check = review_details(runtime, candidate, risk_items, sources)
    _apply_risk_check(result, risk_check)

    detail_keys = [
        'technology', 'team',
        'critical_risk', 'critical_risk_reason', 'critical_risk_evidence',
        'technology_evidence', 'team_evidence',
    ]

    return {
        'company_id': cid,
        'round_id': round_id,
        'status': 'completed',
        'rubric_version': rubric['version'],
        'summary': result['summary'],
        'findings': result['findings'],
        'sources': sources,
        'details': {k: result[k] for k in detail_keys},
        'risks': result['risks'],
        'missing': result['missing'],
        'error': None,
    }
