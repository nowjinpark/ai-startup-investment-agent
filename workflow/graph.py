"""후보를 순서대로 평가하고 투자 검토 대상 발견 또는 후보 소진 시 보고한다."""
from collections.abc import Callable

from langgraph.graph import END, START, StateGraph

from agents.analysis import load_demo_candidates, run_analysis
from agents.evaluation import evaluate_candidate
from contracts.schema import WorkflowState


def build_graph(report_node: Callable):
    """report_node(state)는 {'report_paths': {...}}를 반환한다. API 호출 없음."""
    def initial_route(state: WorkflowState):
        if state.get("mode") == "live":
            raise NotImplementedError("실제 검색·RAG·LLM 분석은 아직 구현되지 않았습니다.")
        if state.get("mode") != "demo":
            raise ValueError("mode='demo'를 지정하세요.")
        candidates = state.get("candidates", [])
        ids = [candidate["id"] for candidate in candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("후보 ID가 중복되었습니다.")
        index = state.get("candidate_index", 0)
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            raise ValueError("candidate_index는 0 이상의 정수여야 합니다.")
        return "select" if index < len(candidates) else "report"

    def select(state: WorkflowState):
        index = state.get("candidate_index", 0)
        return {"current_candidate": state["candidates"][index], "candidate_index": index, "analyses": []}

    def analyze(section: str):
        def node(state: WorkflowState):
            analysis = run_analysis(state["current_candidate"], section, state["mode"])
            return {"analyses": [*state["analyses"], analysis]}
        return node

    def judge(state: WorkflowState):
        result = evaluate_candidate(state["current_candidate"], state["analyses"])
        return {"evaluations": [*state.get("evaluations", []), result],
                "latest_decision": result["decision"]}

    def after_judge(state: WorkflowState):
        has_next = state["candidate_index"] + 1 < len(state["candidates"])
        return "next_candidate" if state["latest_decision"] == "hold" and has_next else "report"

    def next_candidate(state: WorkflowState):
        return {"candidate_index": state["candidate_index"] + 1}

    graph = StateGraph(WorkflowState)
    graph.add_node("select", select)
    for section in ("company", "technology", "market", "competition"):
        graph.add_node(section, analyze(section))
    graph.add_node("judge", judge)
    graph.add_node("next_candidate", next_candidate)
    graph.add_node("report", report_node)
    graph.add_conditional_edges(START, initial_route, {"select": "select", "report": "report"})
    for left, right in zip(("select", "company", "technology", "market", "competition"),
                           ("company", "technology", "market", "competition", "judge")):
        graph.add_edge(left, right)
    graph.add_conditional_edges("judge", after_judge,
                                {"next_candidate": "next_candidate", "report": "report"})
    graph.add_edge("next_candidate", "select")
    graph.add_edge("report", END)
    return graph.compile()
