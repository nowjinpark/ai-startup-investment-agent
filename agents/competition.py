"""4단계: 경쟁기업과 비교하여 회사의 강점을 분석합니다."""
from agents import analysis
from agents.state import WorkflowState


def competition(state: WorkflowState) -> dict:
    result = analysis.run_analysis(state["current_candidate"], "competition", state["mode"])
    return {"analyses": [*state["analyses"], result]}
