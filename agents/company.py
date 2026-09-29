"""1단계: 분석할 회사를 선택하고 회사 정보를 정리합니다."""
from agents import analysis
from agents.state import WorkflowState


def company(state: WorkflowState) -> dict:
    # 앞선 회사를 보류하고 이 단계로 돌아오면 다음 후보를 선택합니다.
    index = state.get("candidate_index", 0)
    if state.get("latest_decision") == "hold" and "current_candidate" in state:
        index += 1
    candidate = state["candidates"][index]
    result = analysis.run_analysis(candidate, "company", state["mode"])
    # 새 회사의 분석을 시작하므로 이전 회사의 중간 분석은 비웁니다.
    return {"candidate_index": index, "current_candidate": candidate, "analyses": [result]}
