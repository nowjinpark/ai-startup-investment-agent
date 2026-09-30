import json
import threading
from copy import deepcopy
from types import SimpleNamespace

import pytest

from test_investment import records
from workflow import build_graph
import workflow


def _case(template, number, score):
    candidate, tech, market = deepcopy(template)
    cid, name = f"company-{number}", f"테스트기업{number}"
    for record in (candidate, tech, market):
        record["company_id"] = cid
        for source in record["sources"]:
            source["company_id"] = cid
            source["text"] = source["text"].replace("테스트기업", name)
    candidate["name"] = name
    for item in candidate["eligibility"].values():
        item["evidence"][0]["quote"] = item["evidence"][0]["quote"].replace("테스트기업", name)

    def change(analysis, criterion_id, quote, **values):
        finding = next(f for f in analysis["findings"] if f["criterion_id"] == criterion_id)
        finding.update(values)
        finding["reason"] = quote
        finding["evidence"][0]["quote"] = quote
        analysis["sources"][0]["text"] += "\n" + quote

    conditional = isinstance(score, tuple)
    if conditional:
        score, _ = score
        candidate["eligibility"]["unlisted"] = {
            "status": "unknown", "reason": "비상장 여부를 추가 확인해야 합니다.", "evidence": []}
    change(tech, 2, "고객 환경에서 무료 PoC를 진행했습니다.", category_value="poc")
    change(market, 3, "고객과 무료 PoC 및 도입 협의를 진행했습니다.", category_value="contact")
    if score is None:
        tech["findings"][0]["status"] = "unknown"
    elif score == 11:
        change(tech, 2, "현재 연구실 데모 단계입니다.", category_value="lab")
    elif score in {13, 18}:
        change(tech, 2, "고객 현장 시험에서 작업 시간이 20% 단축됐습니다.", category_value="proven")
    if score == 18:
        change(tech, 10, "대표는 현재 참여하며 2025년 1월 제품 출시와 2026년 3월 상용 납품을 완료했습니다.", category_value="achievements_2plus")
        change(market, 3, "고객과 유료 공급 계약을 체결했습니다.", category_value="paid")
        change(market, 6, "서로 다른 고객사 A와 B 두 곳에서 현장 검증을 완료했습니다.", numeric_value=2)
        change(market, 7, "물류 기업이 로봇을 월 구독하며 로봇 1대당 월 10만 원으로 가격을 산정합니다.", items=["payer", "product", "price_unit", "price_basis"])
        change(market, 8, "제조 검사와 물류 운반 두 사용 목적에 실제 적용했습니다.", numeric_value=2)
    return candidate, tech, market


def _harness(monkeypatch, tmp_path, template, scores, failing=None, barrier=None):
    cases = [_case(template, index + 1, score) for index, score in enumerate(scores)]
    by_id = {case[0]["company_id"]: case for case in cases}
    calls, completed, reports, judgments = [], set(), [], []
    lock = threading.Lock()
    runtime = SimpleNamespace(output_dir=tmp_path, corpus=SimpleNamespace(history=[]), demo=True,
                              ask=lambda *args, **kwargs: None)

    def discovery_run(_runtime, request):
        calls.append(("discovery", request))
        return {"candidate_list": [deepcopy(case[0]) for case in cases], "doc_pages": len(cases) * 3,
                "page_cap": 200, "prepared": {}}

    def analysis_run(role):
        def run(_runtime, candidate, round_id):
            cid = candidate["company_id"]
            with lock:
                calls.append((role, cid, round_id))
            if barrier:
                barrier.wait(timeout=5)
            if failing == (cid, role):
                raise ValueError("테스트용 분석 실패")
            result = deepcopy(by_id[cid][1 if role == "technology" else 2])
            result.update(round_id=round_id, summary=f"{cid}: {role}, 회차 {round_id}")
            with lock:
                completed.add((cid, role, round_id))
            return result
        return run

    real_evaluate = workflow.investment.evaluate

    def judge(candidate, technology, market, round_id):
        judgments.append((candidate["company_id"], round_id, technology["status"], market["status"]))
        if barrier:
            assert (candidate["company_id"], "technology", round_id) in completed
            assert (candidate["company_id"], "market", round_id) in completed
        return real_evaluate(candidate, technology, market, round_id)

    def create_report(evaluated, output_dir, metadata, writer=None):
        reports.append({"records": deepcopy(evaluated), "metadata": deepcopy(metadata)})
        return {"pdf_path": str(output_dir / "test.pdf"), "markdown_path": str(output_dir / "test.md"), "page_count": 5}

    monkeypatch.setattr(workflow.discovery, "run", discovery_run)
    monkeypatch.setattr(workflow.technology, "run", analysis_run("technology"))
    monkeypatch.setattr(workflow.market_competition, "run", analysis_run("market"))
    monkeypatch.setattr(workflow.investment, "evaluate", judge)
    monkeypatch.setattr(workflow.report, "create_report", create_report)
    state = build_graph(runtime).invoke({"request": "국내 Physical AI"}, config={"recursion_limit": 110})
    return state, calls, reports, judgments


def test_stops_at_five_passed_without_evaluating_sixth_best(monkeypatch, tmp_path, records):
    state, calls, reports, judgments = _harness(monkeypatch, tmp_path, records, [12, 13, 12, 12, 12, 18])
    assert state["stop_reason"] == "five_candidates"
    assert len(state["records"]) == len(state["passed_records"]) == 5
    assert len(judgments) == 5
    assert [r["total_score"] for r in state["ranked_passed"]] == [13, 12, 12, 12, 12]
    assert all(call[1] != "company-6" for call in calls if call[0] != "discovery")
    assert [call[0] for call in calls].count("discovery") == 1
    assert len(reports) == 1
    assert reports[0]["metadata"]["candidate_count"] == 6
    assert reports[0]["metadata"]["evaluated_count"] == 5


def test_exhausts_twenty_candidates_with_all_hold(monkeypatch, tmp_path, records):
    state, calls, reports, judgments = _harness(monkeypatch, tmp_path, records, [11, None] * 10)
    assert state["stop_reason"] == "candidates_exhausted"
    assert len(state["records"]) == 20
    assert not state["passed_records"]
    assert all(record["decision"] == "hold" and record["reasons"] for record in state["records"])
    assert [round_id for _, round_id, *_ in judgments] == list(range(1, 21))
    assert [record["company_id"] for record in state["records"]] == [f"company-{i}" for i in range(1, 21)]
    assert len(reports) == 1
    assert reports[0]["metadata"]["evaluated_count"] == 20


def test_hold_continues_to_next_candidate_and_resets_round(monkeypatch, tmp_path, records):
    state, calls, reports, judgments = _harness(monkeypatch, tmp_path, records, [12, 11, None, 13])
    assert [result["decision"] for result in state["records"]] == ["pass", "hold", "hold", "pass"]
    assert state["stop_reason"] == "candidates_exhausted"
    assert len(state["passed_records"]) == 2
    assert [item["round_id"] for item in state["records"]] == [1, 2, 3, 4]
    for index, record in enumerate(state["records"], 1):
        assert f"company-{index}" in record["technology_summary"]
        assert f"회차 {index}" in record["market_summary"]
    assert len([call for call in calls if call[0] == "technology"]) == 4
    assert len([call for call in calls if call[0] == "market"]) == 4


def test_analyses_run_in_parallel_and_join_before_judgment(monkeypatch, tmp_path, records):
    barrier = threading.Barrier(2)
    state, calls, reports, judgments = _harness(monkeypatch, tmp_path, records, [12], barrier=barrier)
    assert not barrier.broken
    assert judgments == [("company-1", 1, "completed", "completed")]
    assert state["records"][0]["decision"] == "pass"


def test_failed_analysis_is_saved_and_next_candidate_continues(monkeypatch, tmp_path, records):
    state, calls, reports, judgments = _harness(monkeypatch, tmp_path, records, [12, 13], failing=("company-1", "technology"))
    assert [record["decision"] for record in state["records"]] == ["hold", "pass"]
    assert state["records"][0]["total_score"] is None
    failed = json.loads((tmp_path / "analyses/company-1-technology.json").read_text(encoding="utf-8"))
    market = json.loads((tmp_path / "analyses/company-1-market.json").read_text(encoding="utf-8"))
    assert failed["status"] == "failed"
    assert failed["error"] == "ValueError"
    assert failed["company_id"] == "company-1" and failed["round_id"] == 1
    assert market["status"] == "completed" and market["sources"]
    assert "국내 물류 로봇 시장" in market["sources"][0]["text"]
    assert judgments[0] == ("company-1", 1, "failed", "completed")
    assert judgments[1] == ("company-2", 2, "completed", "completed")


def test_empty_candidates_generates_report_without_analysis(monkeypatch, tmp_path, records):
    state, calls, reports, judgments = _harness(monkeypatch, tmp_path, records, [])
    assert state["stop_reason"] == "no_candidates"
    assert state["records"] == []
    assert judgments == []
    assert calls == [("discovery", "국내 Physical AI")]
    assert len(reports) == 1 and reports[0]["records"] == []
    assert reports[0]["metadata"]["candidate_count"] == 0
    assert reports[0]["metadata"]["evaluated_count"] == 0
    assert state["report_error"] is None


def test_passed_and_conditional_candidates_share_five_candidate_limit(monkeypatch, tmp_path, records):
    scores = [(12, "conditional"), 13, (12, "conditional"), 12, (13, "conditional"), 18]
    state, calls, reports, judgments = _harness(monkeypatch, tmp_path, records, scores)
    assert state["stop_reason"] == "five_candidates"
    assert len(judgments) == len(state["candidate_records"]) == 5
    assert len(state["passed_records"]) == 2
    assert len(state["conditional_records"]) == 3
    assert all(r["decision"] == "pass" for r in state["ranked_passed"])
    assert {r["decision"] for r in state["ranked_candidates"]} == {"pass", "conditional"}
    assert [r["total_score"] for r in state["ranked_candidates"]] == [13, 13, 12, 12, 12]
    assert all(call[1] != "company-6" for call in calls if call[0] != "discovery")
    assert len(reports) == 1


def test_demo_fixture_explicit_version_and_boundary_scores():
    from common import ROOT, rubric

    fixtures = json.loads((ROOT / "data/demo_inputs.json").read_text(encoding="utf-8"))
    actual = []
    for index, item in enumerate(fixtures, 1):
        for role in ("technology", "market"):
            assert item[role]["rubric_version"] == rubric()["version"]
            item[role]["round_id"] = index
            expected = {rule["id"] for rule in rubric()["criteria"] if rule["owner"] == role}
            assert {f["criterion_id"] for f in item[role]["findings"]} == expected
        result = workflow.investment.evaluate(item["candidate"], item["technology"], item["market"], index)
        actual.append((result["total_score"], result["decision"]))
    assert actual == [(11, "hold"), (12, "pass"), (13, "pass"), (14, "pass"),
                      (15, "pass"), (16, "pass"), (18, "pass")]


def test_demo_rejects_old_rubric_instead_of_silently_relabeling(monkeypatch, tmp_path):
    import demo

    fixtures = json.loads((demo.ROOT / "data/demo_inputs.json").read_text(encoding="utf-8"))
    fixtures[0]["technology"]["rubric_version"] = "2.0"
    (tmp_path / "data").mkdir()
    (tmp_path / "data/demo_inputs.json").write_text(json.dumps(fixtures), encoding="utf-8")
    monkeypatch.setattr(demo, "ROOT", tmp_path)
    with pytest.raises(ValueError, match="평가표 버전"):
        demo.DemoRuntime({"max_candidates": 7}, tmp_path / "output")
