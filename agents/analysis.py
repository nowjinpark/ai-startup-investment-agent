"""data/example.json의 가상 자료를 읽는 공통 함수. 실제 AI 분석은 미구현입니다."""
import json
from pathlib import Path

from agents.state import Analysis, Candidate

EXAMPLE_PATH = Path(__file__).resolve().parents[1] / "data" / "example.json"
SECTIONS = ("company", "technology", "market", "competition")


def _read_example() -> dict:
    return json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))


def load_demo_candidates() -> list[Candidate]:
    """실제 회사와 무관한 가상의 후보 두 개를 매번 새로 읽는다."""
    return _read_example()["candidates"]


def run_analysis(candidate: Candidate, section: str, mode: str) -> Analysis:
    if mode == "live":
        raise NotImplementedError("실제 검색·RAG·LLM 분석은 아직 구현되지 않았습니다.")
    if mode != "demo":
        raise ValueError(f"지원하지 않는 실행 모드: {mode}")
    if section not in SECTIONS:
        raise ValueError(f"알 수 없는 분석 영역: {section}")
    try:
        return _read_example()["analyses"][candidate["id"]][section]
    except KeyError as exc:
        raise ValueError(f"가상 예제 자료가 없는 후보: {candidate['id']}") from exc
