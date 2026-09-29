"""2단계: 회사의 기술과 AI 활용을 분석합니다."""
from agents import analysis
from agents.state import WorkflowState


def technology(state: WorkflowState) -> dict:
    result = analysis.run_analysis(state["current_candidate"], "technology", state["mode"])
    return {"analyses": [*state["analyses"], result]}
