"""합의 전 임시 평가 정책. 실제 투자 권고를 생성하지 않는다."""
import math
import json
from pathlib import Path

from agents.state import CRITERIA, Analysis, Candidate, Evaluation, Score, WorkflowState

SECTIONS = {"company", "technology", "market", "competition"}


def load_policy() -> tuple[dict[str, float], float]:
    path = Path(__file__).resolve().parents[1] / "evaluation.json"
    policy = json.loads(path.read_text(encoding="utf-8"))
    weights, threshold = policy["weights"], policy["invest_threshold"]
    if set(weights) != set(CRITERIA):
        raise ValueError("평가 항목을 변경하려면 agents/state.py와 평가 코드도 함께 변경하세요.")
    if any(isinstance(x, bool) or not isinstance(x, (int, float))
           or not math.isfinite(x) or x <= 0 for x in weights.values()):
        raise ValueError("평가 가중치는 양의 유한한 수여야 합니다.")
    if not math.isclose(sum(weights.values()), 100):
        raise ValueError("평가 가중치 합은 100이어야 합니다.")
    if (isinstance(threshold, bool) or not isinstance(threshold, (int, float))
            or not math.isfinite(threshold) or not 0 <= threshold <= 100):
        raise ValueError("투자 검토 기준은 0~100이어야 합니다.")
    return weights, threshold


def evaluate_candidate(candidate: Candidate, analyses: list[Analysis]) -> Evaluation:
    """누락 점수는 None을 유지하고, 근거 무결성 오류는 조용히 통과시키지 않는다."""
    weights, threshold = load_policy()
    evidence_by_id = {}
    seen_sections = set()
    for analysis in analyses:
        if analysis["candidate_id"] != candidate["id"]:
            raise ValueError("분석과 평가 대상 후보가 다릅니다.")
        section = analysis["section"]
        if section not in SECTIONS or section in seen_sections:
            raise ValueError(f"알 수 없거나 중복된 분석 영역: {section}")
        seen_sections.add(section)
        for evidence in analysis["evidence"]:
            if evidence["candidate_id"] != candidate["id"]:
                raise ValueError("다른 후보의 근거를 사용할 수 없습니다.")
            evidence_id = evidence["id"]
            if evidence_id in evidence_by_id:
                raise ValueError(f"중복 근거 ID: {evidence_id}")
            if any(not isinstance(evidence.get(key), str) or not evidence[key].strip()
                   for key in ("id", "title", "url", "text")):
                raise ValueError("근거의 ID·제목·URL·본문은 비어 있을 수 없습니다.")
            evidence_by_id[evidence_id] = evidence

    scores: dict[str, Score] = {}
    for analysis in analyses:
        for key, score in analysis["scores"].items():
            if key not in weights:
                raise ValueError(f"알 수 없는 평가 항목: {key}")
            if key in scores:
                raise ValueError(f"중복 평가 항목: {key}")
            refs = score["evidence_ids"]
            if len(refs) != len(set(refs)):
                raise ValueError(f"중복 근거 인용: {key}")
            if any(ref not in evidence_by_id for ref in refs):
                raise ValueError(f"존재하지 않는 근거 인용: {key}")
            value = score["value"]
            if value is not None:
                if (isinstance(value, bool) or not isinstance(value, (int, float))
                        or not math.isfinite(value) or not 0 <= value <= 5):
                    raise ValueError(f"점수는 0~5의 유한한 수 또는 None이어야 합니다: {key}")
                if not refs:
                    raise ValueError(f"확정 점수에는 근거 인용이 필요합니다: {key}")
            scores[key] = dict(score)

    for key in weights:
        scores.setdefault(key, {"value": None, "evidence_ids": [], "reason": "평가 정보 미확인"})
    coverage = sum(weight for key, weight in weights.items()
                   if scores[key]["value"] is not None) / sum(weights.values())
    missing = [key for key in weights if scores[key]["value"] is None]
    weighted_score = None if missing else sum(
        scores[key]["value"] / 5 * weight for key, weight in weights.items()
    )
    decision = "hold"
    if candidate["eligibility"] != "eligible":
        reason = "후보 자격 미충족 또는 미확인으로 보류합니다."
    elif missing:
        reason = f"미확인 평가 항목으로 보류합니다: {', '.join(missing)}."
    elif weighted_score >= threshold:
        decision = "invest"
        reason = "임시 기준을 충족하여 투자 검토 대상으로 분류합니다."
    else:
        reason = "종합점수가 임시 기준에 미달하여 보류합니다."
    return {
        "candidate": candidate,
        "analyses": analyses,
        "scores": scores,
        "weighted_score": weighted_score,
        "coverage": coverage,
        "decision": decision,
        "reason": f"{reason} {threshold:g}점은 팀 검토가 필요한 임시 기준이며 실제 투자 권고가 아닙니다.",
        "is_demo": any(analysis["is_demo"] for analysis in analyses),
    }


def judge(state: WorkflowState) -> dict:
    """5단계: 네 담당의 결과를 모아 판단하고 회사별 결과 목록에 추가합니다."""
    result = evaluate_candidate(state["current_candidate"], state["analyses"])
    return {
        "evaluations": [*state.get("evaluations", []), result],
        "latest_decision": result["decision"],
    }
