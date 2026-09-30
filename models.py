from typing import Literal, TypedDict

from pydantic import BaseModel, Field


class Evidence(BaseModel):
    source_id: str
    quote: str


class Qualification(BaseModel):
    status: Literal['pass', 'fail', 'unknown']
    reason: str
    evidence: list[Evidence]


class Eligibility(BaseModel):
    domestic: Qualification
    unlisted: Qualification
    stage: Qualification
    no_exit: Qualification
    physical_ai: Qualification


class EligibilityResult(BaseModel):
    identity: Qualification = Field(description='초기 후보와 후속 자료의 동일 법인 확인: pass=확인, fail=서로 다른 법인 근거, unknown=미확인')
    eligibility: Eligibility
    operating: Qualification = Field(description='현재 영업 지속 pass, 완료된 폐업·청산·사업 중단 fail, 미확인 unknown. 자료 날짜와 재개 여부 확인')


class CandidateHint(BaseModel):
    name: str
    aliases: list[str]
    website: str
    overview: str
    evidence: list[Evidence]


class CandidateHints(BaseModel):
    companies: list[CandidateHint]


class Finding(BaseModel):
    criterion_id: int = Field(ge=1, le=10)
    status: Literal['verified', 'unknown']
    numeric_value: float | None
    category_value: str | None
    items: list[str]
    reason: str
    evidence: list[Evidence]


class FindingCheck(BaseModel):
    criterion_id: int
    supported: bool
    reason: str


class EvidenceReview(BaseModel):
    checks: list[FindingCheck]


class TechnologyOutput(BaseModel):
    summary: str
    findings: list[Finding]
    technology: str
    technology_evidence: list[Evidence] = Field(default_factory=list)
    team: str
    team_evidence: list[Evidence] = Field(default_factory=list)
    critical_risk: bool | None
    critical_risk_reason: str
    critical_risk_evidence: list[Evidence]
    risks: list[str]
    missing: list[str]


class Competitor(BaseModel):
    name: str
    comparison: str
    evidence: list[Evidence]
    comparison_kind: Literal['direct', 'alternative'] = Field(default='direct', description='direct는 원문 직접 비교, alternative는 각사 사실을 별도 출처로 나란히 제시한 대안입니다.')


class MarketOutput(BaseModel):
    summary: str
    findings: list[Finding]
    market_size: str
    market_size_evidence: list[Evidence]
    market_scope: str
    cagr_period: str
    business_model: str
    competitors: list[Competitor]
    risks: list[str]
    missing: list[str]


class GraphState(TypedDict, total=False):
    request: str
    candidate_list: list[dict]
    candidate_index: int
    candidate: dict
    round_id: int
    prepared: dict
    doc_pages: int
    page_cap: int
    technology: dict
    market: dict
    investment: dict
    records: list[dict]
    passed_records: list[dict]
    conditional_records: list[dict]
    candidate_records: list[dict]
    ranked_candidates: list[dict]
    has_next: bool
    ranked_passed: list[dict]
    stop_reason: str
    error: str | None
    report: dict
    report_error: str | None
