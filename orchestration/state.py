"""LLM 응답 형식과 그래프가 공유하는 작은 상태를 정의합니다."""
from typing import Annotated, Literal, TypedDict
from pydantic import BaseModel, Field

View = Literal['technology', 'market', 'stakeholders', 'application']
VIEWS = ('technology', 'market', 'stakeholders', 'application')
VIEW_LABELS = {'technology': '기술 성숙도', 'market': '시장성',
               'stakeholders': '이해관계자', 'application': '도메인 적용성'}


class Task(BaseModel):
    task_id: str
    company_id: str
    views: list[View] = Field(min_length=1, max_length=4)
    question: str
    queries: list[str] = Field(min_length=1, max_length=3)
    reason: str
    done_condition: str


class Plan(BaseModel):
    reason: str
    tasks: list[Task] = Field(min_length=1, max_length=20)


class Evidence(BaseModel):
    source_id: str
    quote: str


class Finding(BaseModel):
    view: View
    text: str
    evidence: list[Evidence]


class Research(BaseModel):
    summary: str
    findings: list[Finding]
    limitations: list[str]


class GroundingCheck(BaseModel):
    index: int
    supported: bool
    corrected_text: str
    reason: str
    evidence_indices: list[int]
    suitable_views: list[View]


class GroundingReview(BaseModel):
    checks: list[GroundingCheck]


class ViewSelection(BaseModel):
    company_id: str
    view: View
    finding_ids: list[str] = Field(max_length=2)
    condition_codes: list[Literal['independent', 'paid', 'scope', 'planned', 'team', 'market_size']] = Field(max_length=2)


class Report(BaseModel):
    selections: list[ViewSelection]


class Criterion(BaseModel):
    criterion: Literal['groundedness', 'neutrality', 'bias', 'coverage']
    passed: bool
    reason: str


class Evaluation(BaseModel):
    criteria: list[Criterion]
    action: Literal['approve', 'research', 'rewrite']
    feedback: str
    retry_task_ids: list[str]


def merge_results(old: dict, new: dict) -> dict:
    """병렬 도착 순서와 무관하게 task_id별 최신 회차 한 개만 보관합니다."""
    merged = dict(old)
    for key, value in new.items():
        previous = merged.get(key)
        if previous is None or value['revision'] > previous['revision']:
            merged[key] = value
        elif value['revision'] == previous['revision'] and value != previous:
            raise ValueError(f'같은 작업·회차의 결과 충돌: {key}')
    return dict(sorted(merged.items()))


class AgentState(TypedDict, total=False):
    # 입력 및 결과: 원문 전체는 외부 raw 파일에 두고 참조만 전달합니다.
    request: str
    companies: list[dict]
    plan: list[dict]
    plan_reason: str
    results: Annotated[dict, merge_results]
    report: str
    evaluation: dict
    # 제어 및 복구: 실행 식별자, 한도, 상태, 오류를 따로 둡니다.
    trace_id: str
    revision: int
    max_revisions: int
    step_count: int
    node_status: dict
    last_error: str
    feedback: str
    pending_task_ids: list[str]
    route: str
    status: str
