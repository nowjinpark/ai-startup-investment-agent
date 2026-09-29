"""5명이 함께 사용하는 입력·출력 형식. 변경할 때는 팀원과 먼저 합의하세요."""
from typing import Literal, NotRequired, TypedDict


class Company(TypedDict):
    id: str
    name: str
    description: str
    website: str
    is_example: bool


class Source(TypedDict):
    title: str
    url: str
    page: int | None
    published_at: NotRequired[str | None]  # 확인한 발행일. 웹·보고서 출처 표기에 사용합니다.


class Analysis(TypedDict):
    summary: str
    sources: list[Source]
    uncertainties: list[str]
    is_example: bool


class Investment(TypedDict):
    decision: Literal["invest", "hold"]
    reason: str
    score: float | None  # 팀이 정한 기준으로 계산한 0~100점. 미확인이면 None.
    sources: list[Source]
    is_example: bool


class CompanyRecord(TypedDict):
    company: Company
    company_info: Analysis
    technology: Analysis
    market_competition: Analysis
    investment: Investment


class Report(TypedDict):
    summary: str
    markdown: str
    is_example: bool


class State(TypedDict, total=False):
    domain: str
    candidates: list[Company]
    candidate_index: int
    company: Company
    company_info: Analysis
    technology: Analysis
    market_competition: Analysis
    investment: Investment
    history: list[CompanyRecord]
    report: Report


# 각 파일은 자기 결과 한 개만 반환합니다. 다른 담당자의 결과를 덮어쓰지 않습니다.
AGENT_KEYS = {
    "company": "company_info",
    "technology": "technology",
    "market_competition": "market_competition",
    "investment": "investment",
    "report": "report",
}
