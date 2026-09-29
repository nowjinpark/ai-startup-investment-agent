"""분석 담당들이 함께 읽고 쓰는 데이터 모양.

수업의 TypedDict 예제처럼 필요한 항목을 정리합니다.
None은 '아직 모름'이며, 점수 0과 다릅니다. demo는 가상 자료로 흐름만 확인하는 모드입니다.
"""
from typing import Literal, TypedDict

CRITERIA = {"founder": 30, "market": 25, "technology": 15,
            "advantage": 10, "traction": 10, "deal": 10}


class Candidate(TypedDict):
    """분석할 회사 후보."""
    id: str
    name: str
    domain: str
    eligibility: Literal["eligible", "ineligible", "unverified"]


class Evidence(TypedDict):
    """출처와 원문을 함께 보관하는 근거."""
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
    """회사·기술·시장·경쟁 담당이 각각 만든 분석 결과."""
    candidate_id: str
    section: Literal["company", "technology", "market", "competition"]
    summary: str
    evidence: list[Evidence]
    scores: dict[str, Score]
    missing_information: list[str]
    is_demo: bool


class Evaluation(TypedDict):
    """한 회사의 분석을 모아 계산한 판단 결과."""
    candidate: Candidate
    analyses: list[Analysis]
    scores: dict[str, Score]
    weighted_score: float | None  # 미확인 항목이 있으면 종합점수 확정하지 않음.
    coverage: float  # 확인된 항목의 가중치 합, 0~1.
    decision: Literal["invest", "hold"]
    reason: str
    is_demo: bool


class WorkflowState(TypedDict, total=False):
    """그래프에서 다음 단계로 전달할 공용 데이터."""
    candidates: list[Candidate]
    candidate_index: int
    current_candidate: Candidate
    analyses: list[Analysis]
    evaluations: list[Evaluation]
    latest_decision: Literal["invest", "hold"]
    mode: Literal["demo", "live"]
    report_paths: dict[str, str]
