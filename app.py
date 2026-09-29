"""수업 예제처럼 여섯 단계를 연결합니다. 현재는 가상 자료로만 실행합니다."""
import argparse
from collections.abc import Callable
from pathlib import Path

from langgraph.graph import END, START, StateGraph

from agents.analysis import load_demo_candidates
from agents.company import company
from agents.technology import technology
from agents.market import market
from agents.competition import competition
from agents.evaluation import judge
from agents.report import report, write_reports
from agents.state import WorkflowState


def start_route(state: WorkflowState) -> str:
    """실행 모드와 후보 목록을 확인합니다."""
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
    return "company" if index < len(candidates) else "report"


def after_judge(state: WorkflowState) -> str:
    """보류했고 남은 후보가 있으면 다시 회사탐색, 그 외에는 보고서로 갑니다."""
    has_next = state["candidate_index"] + 1 < len(state["candidates"])
    if state["latest_decision"] == "hold" and has_next:
        return "company"
    return "report"


def build_graph(report_node: Callable = report):
    """일반 함수와 명시적인 연결로 구성한 6단계 그래프."""
    graph = StateGraph(WorkflowState)
    graph.add_node("company", company)          # 1. 회사탐색
    graph.add_node("technology", technology)    # 2. 기술분석
    graph.add_node("market", market)            # 3. 시장분석
    graph.add_node("competition", competition)  # 4. 경쟁분석
    graph.add_node("judge", judge)              # 5. 투자판단
    graph.add_node("report", report_node)       # 6. 보고서작성

    graph.add_conditional_edges(START, start_route,
                                {"company": "company", "report": "report"})
    graph.add_edge("company", "technology")
    graph.add_edge("technology", "market")
    graph.add_edge("market", "competition")
    graph.add_edge("competition", "judge")
    graph.add_conditional_edges("judge", after_judge,
                                {"company": "company", "report": "report"})
    graph.add_edge("report", END)
    return graph.compile()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["demo", "live"], default="demo")
    parser.add_argument("--output", type=Path, default=Path("outputs/demo"))
    args = parser.parse_args()
    if args.mode == "live":
        parser.error("실제 RAG/LLM 분석은 담당자가 구현해야 합니다. 현재는 --mode demo만 지원합니다.")

    def report_node(state):
        return {"report_paths": write_reports(state["evaluations"], args.output)}

    graph = build_graph(report_node)
    result = graph.invoke({
        "candidates": load_demo_candidates(), "candidate_index": 0,
        "evaluations": [], "mode": "demo",
    }, config={"recursion_limit": 50})
    print("DEMO ONLY: 가상기업으로 연결을 확인했습니다. 실제 기업 투자 분석 결과가 아닙니다.")
    for kind, path in result["report_paths"].items():
        print(f"{kind}: {path}")


if __name__ == "__main__":
    main()
