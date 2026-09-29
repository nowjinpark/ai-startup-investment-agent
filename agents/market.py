"""3단계: 고객의 문제와 시장을 분석합니다."""
from agents import analysis
from agents.state import WorkflowState


def market(state: WorkflowState) -> dict:
    result = analysis.run_analysis(state["current_candidate"], "market", state["mode"])
    return {"analyses": [*state["analyses"], result]}
