"""JSON으로 저장할 수 있는 공통 계약 v0.1 (Python 3.11+).

section별 에이전트는 Analysis를 반환합니다. 점수 미확인은 None이며 0과 다릅니다.
이 파일을 합의하면 다른 담당자의 구현 없이 fixtures로 병렬 개발할 수 있습니다.
"""
from typing import Literal, TypedDict

CRITERIA = {"founder": 30, "market": 25, "technology": 15,
            "advantage": 10, "traction": 10, "deal": 10}


class Candidate(TypedDict):
    id: str
    name: str
    domain: str
    eligibility: Literal["eligible", "ineligible", "unverified"]


class Evidence(TypedDict):
    id: str
    candidate_id: str
    title: str
    url: str
    published_at: str | None
    page: int | None
    text: str
    source_type: Literal["company", "customer", "research", "institution", "news", "demo"]


class Score(TypedDict):
    value: float | None  # 0~5. 알 수 없으면 None.
    evidence_ids: list[str]
    reason: str


class Analysis(TypedDict):
    candidate_id: str
    section: Literal["company", "technology", "market", "competition"]
    summary: str
    evidence: list[Evidence]
    scores: dict[str, Score]
    missing_information: list[str]
    is_demo: bool


class Evaluation(TypedDict):
    candidate: Candidate
    analyses: list[Analysis]
    scores: dict[str, Score]
    weighted_score: float | None  # 미확인 항목이 있으면 종합점수 확정하지 않음.
    coverage: float  # 확인된 항목의 가중치 합, 0~1.
    decision: Literal["invest", "hold"]
    reason: str
    is_demo: bool


class WorkflowState(TypedDict, total=False):
    candidates: list[Candidate]
    candidate_index: int
    current_candidate: Candidate
    analyses: list[Analysis]
    evaluations: list[Evaluation]
    latest_decision: Literal["invest", "hold"]
    mode: Literal["demo", "live"]
    report_paths: dict[str, str]
