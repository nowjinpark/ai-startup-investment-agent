"""5개 담당 파일을 순서대로 연결합니다. 현재 담당 파일의 내용은 연습용입니다."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

from langgraph.graph import END, START, StateGraph

from agents import company, investment, market_competition, report, technology
from shared import AGENT_KEYS, State
from validation import validate_agent_result, validate_candidates, validate_state

ROOT = Path(__file__).resolve().parent
EXAMPLE_NOTICE = "연습용 결과입니다. 예제 데이터가 포함되어 실제 투자 판단에 사용할 수 없습니다."


def load_candidates(path=ROOT / "data" / "companies.json"):
    candidates = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_candidates(candidates)
    return candidates


def prepare_state(candidates) -> State:
    validate_candidates(candidates)
    return {"domain": "Physical AI", "candidates": deepcopy(candidates), "candidate_index": 0, "history": []}


def empty_analysis():
    return {"summary": "", "sources": [], "uncertainties": [], "is_example": False}


def select_candidate(state: State) -> dict:
    """후보가 바뀌면 이전 회사의 분석과 판단을 빈 값으로 초기화합니다."""
    return {
        "company": deepcopy(state["candidates"][state["candidate_index"]]),
        "company_info": empty_analysis(),
        "technology": empty_analysis(),
        "market_competition": empty_analysis(),
        "investment": {"decision": "hold", "reason": "", "score": None, "sources": [], "is_example": False},
    }


def next_candidate(state: State) -> dict:
    index = state["candidate_index"] + 1
    return {"candidate_index": index, **select_candidate({**state, "candidate_index": index})}


def has_example(value) -> bool:
    """최종 안내와 보고서에는 누적 기록의 예제 표시까지 반영합니다."""
    if isinstance(value, dict):
        return value.get("is_example") is True or any(has_example(item) for item in value.values())
    if isinstance(value, list):
        return any(has_example(item) for item in value)
    return False


def run_agent(agent_name, run, state: State) -> dict:
    """자기 결과만 받으며, 입력 복사본을 주어 다른 담당자의 결과를 보호합니다."""
    # 단독 실행용 완성 예제에 후행 결과가 있어도 선행 입력만 예제 표시에 반영합니다.
    inputs = {
        "company": ["company"],
        "technology": ["company", "company_info"],
        "market_competition": ["company", "company_info", "technology"],
        "investment": ["company", "company_info", "technology", "market_competition"],
        "report": ["history"],
    }
    try:
        validate_state(state)
        for key in inputs[agent_name]:
            if key not in state:
                raise ValueError(f"입력에 {key}가 필요합니다.")
        result = deepcopy(run(deepcopy(state)))
        validate_agent_result(agent_name, result)
        key = AGENT_KEYS[agent_name]
        example_keys = inputs[agent_name]
        if agent_name == "report":
            example_keys = ["company", "company_info", "technology", "market_competition", "investment", "history"]
        if any(has_example(state.get(field)) for field in example_keys):
            result[key]["is_example"] = True
        return result
    except Exception as error:
        raise ValueError(f"{agent_name} agent 오류: {error}") from error


def company_node(state: State) -> dict:
    return run_agent("company", company.run, state)


def technology_node(state: State) -> dict:
    return run_agent("technology", technology.run, state)


def market_competition_node(state: State) -> dict:
    return run_agent("market_competition", market_competition.run, state)


def investment_node(state: State) -> dict:
    result = run_agent("investment", investment.run, state)
    # 다음 회사로 넘어가도 이미 검토한 회사의 결과는 남깁니다.
    record = {
        "company": deepcopy(state["company"]),
        "company_info": deepcopy(state["company_info"]),
        "technology": deepcopy(state["technology"]),
        "market_competition": deepcopy(state["market_competition"]),
        "investment": deepcopy(result["investment"]),
    }
    return {**result, "history": [*deepcopy(state.get("history", [])), record]}


def report_node(state: State) -> dict:
    return run_agent("report", report.run, state)


def after_investment(state: State) -> str:
    if state["investment"]["decision"] == "hold" and state["candidate_index"] + 1 < len(state["candidates"]):
        return "next_candidate"
    return "report"


def build_graph():
    graph = StateGraph(State)
    graph.add_node("select_candidate", select_candidate)
    graph.add_node("company", company_node)
    graph.add_node("technology", technology_node)
    graph.add_node("market_competition", market_competition_node)
    graph.add_node("investment", investment_node)
    graph.add_node("next_candidate", next_candidate)
    graph.add_node("report", report_node)

    graph.add_edge(START, "select_candidate")
    graph.add_edge("select_candidate", "company")
    graph.add_edge("company", "technology")
    graph.add_edge("technology", "market_competition")
    graph.add_edge("market_competition", "investment")
    graph.add_conditional_edges("investment", after_investment, {"next_candidate": "next_candidate", "report": "report"})
    graph.add_edge("next_candidate", "company")
    graph.add_edge("report", END)
    return graph.compile()


def save_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    # 환경 파일은 이 실행 입구에서만 읽습니다. import와 테스트는 읽지 않습니다.
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=False)

    parser = argparse.ArgumentParser(description="Physical AI 기업 분석 연결 연습")
    parser.add_argument("--agent", choices=list(AGENT_KEYS), help="담당 파일 하나만 실행")
    parser.add_argument("--state", type=Path, help="단독 실행 입력 JSON (기본: data/test_state.json)")
    parser.add_argument("--companies", type=Path, help="전체 실행 후보 JSON (기본: data/companies.json)")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs", help="결과를 저장할 폴더")
    args = parser.parse_args(argv)
    try:
        if args.state is not None and args.agent is None:
            raise ValueError("--state는 --agent와 함께 사용하세요.")
        if args.companies is not None and args.agent is not None:
            raise ValueError("--companies는 전체 실행 전용입니다. --agent와 함께 사용할 수 없습니다.")
        args.output.mkdir(parents=True, exist_ok=True)
        if args.agent:
            state_path = args.state or ROOT / "data" / "test_state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            modules = {"company": company, "technology": technology, "market_competition": market_competition, "investment": investment, "report": report}
            result = run_agent(args.agent, modules[args.agent].run, state)
            json_path = args.output / f"{args.agent}.json"
            save_json(json_path, result)
            print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        else:
            state = prepare_state(load_candidates(args.companies or ROOT / "data" / "companies.json"))
            result = build_graph().invoke(state, {"recursion_limit": len(state["candidates"]) * 6 + 5})
            json_path = args.output / "state.json"
            save_json(json_path, result)
        print(f"JSON 저장: {json_path.resolve()}")
        if "report" in result:
            from export_outputs import export_report
            paths = export_report(result["report"], args.output)
            for name, path in paths.items():
                print(f"{name} 저장: {Path(path).resolve()}")
        if has_example(result):
            print(EXAMPLE_NOTICE)
        return 0
    except Exception as error:
        print(f"오류: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
