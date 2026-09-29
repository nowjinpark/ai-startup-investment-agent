"""API 호출 없이 공통 계약과 Graph 연결을 확인하는 협업용 데모."""
import argparse
from pathlib import Path

from reporting.export import write_reports
from workflow.graph import build_graph, load_demo_candidates


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
