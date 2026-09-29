"""실제 조사 대신 명시적으로 합성된 입력을 사용하는 데모 구현."""
import json
from pathlib import Path

from contracts.schema import Analysis, Candidate

FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "demo_candidates.json"
SECTIONS = ("company", "technology", "market", "competition")


def _load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def load_demo_candidates() -> list[Candidate]:
    """실제 회사와 무관한 가상의 후보 두 개를 매번 새로 읽는다."""
    return _load_fixture()["candidates"]


def run_analysis(candidate: Candidate, section: str, mode: str) -> Analysis:
    if mode == "live":
        raise NotImplementedError("실제 검색·RAG·LLM 분석은 아직 구현되지 않았습니다.")
    if mode != "demo":
        raise ValueError(f"지원하지 않는 실행 모드: {mode}")
    if section not in SECTIONS:
        raise ValueError(f"알 수 없는 분석 영역: {section}")
    try:
        return _load_fixture()["analyses"][candidate["id"]][section]
    except KeyError as exc:
        raise ValueError(f"합성 fixture가 없는 후보: {candidate['id']}") from exc
