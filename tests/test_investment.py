from copy import deepcopy

import pytest

from agents.investment import RUBRIC, evaluate


def source(key, company_id, text):
    return {"source_id": key, "company_id": company_id, "text": text, "title": "테스트 자료", "url": f"https://example.com/{key}", "doc_type": "company"}


def finding(key, source_id, quote, numeric=None, category=None, items=None):
    return {"criterion_id": key, "status": "verified", "numeric_value": numeric, "category_value": category, "items": items or [], "reason": quote, "evidence": [{"source_id": source_id, "quote": quote}]}


@pytest.fixture
def records():
    eligibility_quote = "테스트기업은 국내 비상장 Physical AI 기업이며 Seed 단계이고 인수 또는 Exit가 완료되지 않았습니다."
    identity_quote = "법인 등록번호로 현재 분석 기업과 동일한 법인임을 확인했습니다."
    operating_quote = "2026년 9월 30일 로봇 제품을 공급하며 현재 사업을 운영하고 있습니다."
    risk_quote = "안전 시험과 운영 점검 결과 중대한 미해결 위험은 없습니다."
    tech_quotes = ["고객 현장에서 작업 시간이 20% 단축됐습니다.", "등록 특허와 논문이 있습니다.", "CTO는 관련 연구 경력 3년입니다.", "일부 운영 위험은 대응 진행 중입니다.", "대표는 현재 관련 제품 개발에 참여합니다."]
    market_quotes = ["국내 물류 로봇 시장은 2025~2030년 CAGR 15%입니다.", "유료 공급 계약 1건을 체결했습니다.", "고객사 1곳에서 실제 현장 실증을 진행했습니다.", "구매자는 물류 기업, 제품은 로봇, 가격 단위는 월 구독입니다.", "검증된 적용 목적은 물류 운반 1개입니다."]
    candidate = {
        "company_id": "demo", "name": "테스트기업", "aliases": [], "overview": "테스트용 기업",
        "eligibility": {key: {"status": "pass", "reason": eligibility_quote, "evidence": [{"source_id": "basic", "quote": eligibility_quote}]} for key in ("domestic", "unlisted", "stage", "no_exit", "physical_ai")},
        "identity": {"status": "pass", "reason": "기업 동일성을 확인했습니다.", "evidence": [{"source_id": "basic", "quote": identity_quote}]},
        "operating": {"status": "pass", "reason": "현재 운영 중입니다.", "evidence": [{"source_id": "basic", "quote": operating_quote}]},
        "sources": [source("basic", "demo", eligibility_quote + " " + identity_quote + " " + operating_quote)], "source_ids": ["basic"],
    }
    tech = {
        "company_id": "demo", "round_id": 1, "rubric_version": RUBRIC["version"], "status": "completed", "summary": "기술 분석", "missing": [], "risks": [],
        "findings": [finding(2, "tech", tech_quotes[0], category="proven"), finding(4, "tech", tech_quotes[1], items=["registered_patent", "paper_or_report"]), finding(5, "tech", tech_quotes[2], numeric=3), finding(9, "tech", tech_quotes[3], category="in_progress"), finding(10, "tech", tech_quotes[4], category="active")],
        "sources": [source("tech", "demo", "\n".join(tech_quotes + [risk_quote]))],
        "details": {"critical_risk": False, "critical_risk_reason": risk_quote, "critical_risk_evidence": [{"source_id": "tech", "quote": risk_quote}], "technology": "자율 이동 로봇", "team": "CTO 경력 3년"},
    }
    market = {
        "company_id": "demo", "round_id": 1, "rubric_version": RUBRIC["version"], "status": "completed", "summary": "시장 분석", "missing": [], "risks": [],
        "findings": [finding(1, "market", market_quotes[0], numeric=15), finding(3, "market", market_quotes[1], category="paid"), finding(6, "market", market_quotes[2], numeric=1), finding(7, "market", market_quotes[3], items=["payer", "product", "price_unit"]), finding(8, "market", market_quotes[4], numeric=1)],
        "sources": [source("market", "demo", "\n".join(market_quotes))],
        "details": {"market_scope": "국내 물류 로봇 시장", "cagr_period": "2025~2030", "market_size": "확인 필요", "business_model": "월 구독", "competitors": []},
    }
    active = {rule["id"] for rule in RUBRIC["criteria"]}
    tech["findings"] = [item for item in tech["findings"] if item["criterion_id"] in active]
    market["findings"] = [item for item in market["findings"] if item["criterion_id"] in active]
    return candidate, tech, market


def update_finding(analysis, criterion_id, quote, **fields):
    item = next(f for f in analysis["findings"] if f["criterion_id"] == criterion_id)
    item.update(fields, reason=quote)
    item["evidence"] = [{"source_id": analysis["sources"][0]["source_id"], "quote": quote}]
    analysis["sources"][0]["text"] += "\n" + quote


def criterion(result, key):
    return next(item for item in result["criteria"] if item["criterion_id"] == key)


def test_sector_source_is_only_allowed_for_qualitative_comparison(records):
    candidate, tech, market = records
    sector = source('sector', '__sector__', '대안기업은 협동 로봇을 제조 현장에 공급합니다.')
    market['sources'].append(sector)
    own = market['sources'][0]
    comparison = {'name': '대안기업', 'comparison': '대상기업은 운반 로봇, 대안기업은 협동 로봇을 공급합니다.',
                  'comparison_kind': 'alternative', 'evidence': [
                      {'source_id': own['source_id'], 'quote': own['text']},
                      {'source_id': sector['source_id'], 'quote': sector['text']}]}
    market['details']['competitors'] = [comparison]
    assert len(evaluate(candidate, tech, market, 1)['details']['market']['competitors']) == 1
    market['findings'][0]['evidence'] = [comparison['evidence'][1]]
    result = evaluate(candidate, tech, market, 1)
    assert criterion(result, 3)['score'] is None
    market['details']['competitors'][0]['evidence'] = [comparison['evidence'][1]]
    assert not evaluate(candidate, tech, market, 1)['details']['market']['competitors']


def test_industry_context_keeps_cited_source_without_changing_company_decision(records):
    candidate, tech, market = records
    baseline = evaluate(candidate, tech, market, 1)
    sector = source('industry-risk', '__sector__', '산업 전반에서 안전 규제와 공급망 대응 비용이 증가하고 있습니다.')
    market['sources'].append(sector)
    market['details']['context_risks'] = [{'type': '운영', 'reason': '산업 공통 위험으로 이 기업의 실제 위험 발생을 뜻하지 않습니다.',
        'critical_risk': True, 'evidence': [{'source_id': sector['source_id'], 'quote': sector['text']}]}]
    result = evaluate(candidate, tech, market, 1)
    assert any(s['source_id'] == 'industry-risk' for s in result['sources'])
    context = result['details']['market']['context_risks'][0]
    assert context['context_only'] is True and 'critical_risk' not in context
    for field in ['total_score', 'decision', 'critical_risk_confirmed', 'score_pass', 'coverage_count', 'criteria']:
        assert result[field] == baseline[field]


@pytest.mark.parametrize('change', ['forged_quote', 'other_company'])
def test_context_rejects_unregistered_quote_or_other_company_source(records, change):
    candidate, tech, market = records
    sector = source('industry-risk', '__sector__', '산업 전반에서 안전 규제 대응 비용이 증가하고 있습니다.')
    evidence = {'source_id': sector['source_id'], 'quote': sector['text']}
    if change == 'forged_quote':
        evidence['quote'] = '원문에 없는 산업 위험과 수치를 임의로 추가했습니다.'
    else:
        sector['company_id'] = 'different-company'
    market['sources'].append(sector)
    market['details']['context_risks'] = [{'type': '산업', 'reason': '배경 설명', 'evidence': [evidence]}]
    result = evaluate(candidate, tech, market, 1)
    assert not result['details']['market']['context_risks']
    assert all(s['source_id'] != 'industry-risk' for s in result['sources'])


def all_medium(records):
    candidate, tech, market = records
    update_finding(tech, 2, "고객 현장에서 PoC를 진행했습니다.", category_value="poc")
    update_finding(market, 3, "고객과 무료 PoC를 진행했습니다.", category_value="contact")
    return candidate, tech, market


def all_high(records):
    candidate, tech, market = records
    update_finding(tech, 10, "대표가 현재 참여하며 2025년 3월 1일 출시와 2026년 5월 1일 납품을 완료했습니다.", category_value="achievements_2plus")
    update_finding(market, 6, "물류사 A와 B 등 고객사 2곳에서 실제 현장 실증을 완료했습니다.", numeric_value=2)
    update_finding(market, 7, "물류 회사가 로봇 1대당 월 구독료를 내며 보유 로봇 대수에 따라 가격을 산정합니다.", items=["payer", "product", "price_unit", "price_basis"])
    update_finding(market, 8, "제조 검사와 물류 운반 2개 사용 목적에서 실제 적용을 완료했습니다.", numeric_value=2)
    return candidate, tech, market


@pytest.mark.parametrize("score,decision", [(11, "hold"), (12, "pass"), (13, "pass")])
def test_score_boundary(records, score, decision):
    candidate, tech, market = all_medium(records)
    category = {11: "lab", 12: "poc", 13: "proven"}[score]
    update_finding(tech, 2, "고객 환경 시험 및 실험실 결과를 확인했습니다.", category_value=category)
    result = evaluate(candidate, tech, market, 1)
    assert result["total_score"] == score
    assert result["decision"] == decision
    assert result["score_pass"] == (score >= 12)
    assert result["score_scale"] == 18 and result["criterion_count"] == 6
    assert [x["criterion_id"] for x in result["criteria"]] == [2, 3, 6, 7, 8, 10]
    assert [x["display_number"] for x in result["criteria"]] == list(range(1, 7))
    assert result["rubric_version"] == "3.0"
    assert "normalized_score" not in result and "score_range" not in result


@pytest.mark.parametrize("key", [2, 3, 6, 7, 8, 10])
def test_every_remaining_item_needs_evidence_without_imputation(records, key):
    candidate, tech, market = all_high(records)
    for analysis in (tech, market):
        for item in analysis["findings"]:
            if item["criterion_id"] == key:
                item["status"] = "unknown"
    result = evaluate(candidate, tech, market, 1)
    assert result["total_score"] is None and result["decision"] == "hold"
    assert result["coverage_count"] == 5 and result["observed_sum"] == 15
    assert criterion(result, key)["score"] is None


@pytest.mark.parametrize("removed", [1, 4, 5, 9])
def test_removed_items_do_not_change_score(records, removed):
    candidate, tech, market = records
    tech["findings"].append({"criterion_id": removed, "status": "unknown"})
    result = evaluate(candidate, tech, market, 1)
    assert result["total_score"] == 14 and result["decision"] == "pass"


def seed_page_pair(candidate):
    title = "앞선 회사 상세내용 닫기\n투자 기업 소개\n테스트기업"
    body = "Seed 단계 투자를 유치한 국내 로봇 제어 기업입니다."
    pages = [source("seed1", "__discovery__", title), source("seed2", "__discovery__", body)]
    for index, page in enumerate(pages, 1):
        page.update(url="https://example.com/portfolio", rendered_page=index)
    candidate["sources"].extend(pages)
    candidate["eligibility"]["stage"]["evidence"] = [
        {"source_id": page["source_id"], "quote": page["text"]} for page in pages]
    return pages


def test_seed_company_heading_on_previous_page_is_valid(records):
    candidate, tech, market = records
    seed_page_pair(candidate)
    result = evaluate(candidate, tech, market, 1)
    assert result["decision"] == "pass"
    assert {"seed1", "seed2"} <= {s["source_id"] for s in result["sources"]}


@pytest.mark.parametrize("change", ["other_url", "nonadjacent", "missing_anchor", "other_title", "closing_boundary", "hidden_prefix", "not_a_heading", "ambiguous_tail", "forged_anchor"])
def test_seed_page_pair_rejects_ambiguous_or_unrelated_context(records, change):
    candidate, tech, market = records
    first, second = seed_page_pair(candidate)
    evidence = candidate["eligibility"]["stage"]["evidence"]
    if change == "other_url":
        second["url"] = "https://example.com/other"
    elif change == "nonadjacent":
        second["rendered_page"] = 3
    elif change == "missing_anchor":
        evidence.pop(0)
    elif change == "other_title":
        first["text"] += "\n다른기업"
        evidence[0]["quote"] = first["text"]
    elif change == "closing_boundary":
        second["text"] = "상세내용 닫기\n다른기업\n" + second["text"]
        evidence[1]["quote"] = second["text"]
    elif change == "hidden_prefix":
        second["text"] = "상세내용 닫기\n다른기업\n" + second["text"]
    elif change == "not_a_heading":
        first["text"] = "이 페이지에서는 테스트기업도 언급합니다."
        evidence[0]["quote"] = first["text"]
    elif change == "ambiguous_tail":
        first["text"] += "\n소속이 불명확한 다른 구간"
        evidence[0]["quote"] = first["text"]
    elif change == "forged_anchor":
        evidence[0]["quote"] = "이 원문에 없는 테스트기업 제목입니다."
    assert evaluate(candidate, tech, market, 1)["decision"] == "conditional"


def test_seed_original_pdf_page_pair_and_word_wrap(records):
    candidate, tech, market = records
    pages = seed_page_pair(candidate)
    for page in pages:
        page["original_page"] = page.pop("rendered_page")
    pages[0]["text"] = pages[0]["text"].replace("테스트기업", "테스트 기업")
    pages[1]["text"] = pages[1]["text"].replace("투자를", "투\n자를")
    assert evaluate(candidate, tech, market, 1)["decision"] == "pass"


@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), "15", None, [], {}])
def test_malformed_number(records, value):
    candidate, tech, market = records
    market["findings"][1]["numeric_value"] = value
    result = evaluate(candidate, tech, market, 1)
    assert result["decision"] == "hold" and criterion(result, 6)["score"] is None


@pytest.mark.parametrize("change", ["missing", "duplicate", "wrong_role", "bad_items", "duplicate_items"])
def test_finding_structure(records, change):
    candidate, tech, market = records
    if change == "missing":
        tech["findings"].pop()
    elif change == "duplicate":
        tech["findings"].append(deepcopy(tech["findings"][0]))
    elif change == "wrong_role":
        market["findings"].append(tech["findings"].pop())
    elif change == "bad_items":
        market["findings"][2]["items"] = ["patent"]
    elif change == "duplicate_items":
        market["findings"][2]["items"] = ["payer", "payer"]
    result = evaluate(candidate, tech, market, 1)
    assert result["decision"] == "hold" and result["coverage_count"] < 6


@pytest.mark.parametrize("change", ["unknown_id", "fabricated_quote", "mixed_company", "conflicting_id"])
def test_bad_evidence(records, change):
    candidate, tech, market = records
    if change == "unknown_id":
        tech["findings"][0]["evidence"][0]["source_id"] = "forged"
    elif change == "fabricated_quote":
        tech["findings"][0]["evidence"][0]["quote"] = "고객 현장에서 비용이 99% 절감됐습니다."
    elif change == "mixed_company":
        tech["sources"][0]["company_id"] = "other"
    elif change == "conflicting_id":
        market["sources"].append(source("tech", "other", "다른 기업의 문서입니다."))
    result = evaluate(candidate, tech, market, 1)
    assert result["decision"] == "hold" and result["total_score"] is None


def test_whitespace_normalization_and_evidence_dedup(records):
    candidate, tech, market = records
    tech["sources"][0]["text"] = tech["sources"][0]["text"].replace(" ", "  \n").replace("현장에서", "현\n장에서")
    tech["findings"][0]["evidence"] *= 2
    result = evaluate(candidate, tech, market, 1)
    assert result["decision"] == "pass" and len(criterion(result, 2)["evidence"]) == 1


@pytest.mark.parametrize("field,value", [("round_id", 0), ("round_id", True), ("company_id", "other"), ("status", "failed"), ("status", "pending")])
def test_join_guard(records, field, value):
    candidate, tech, market = records
    tech[field] = value
    result = evaluate(candidate, tech, market, 1)
    assert result["decision"] == "hold" and result["total_score"] is None
    assert result["technology_summary"] == ""


@pytest.mark.parametrize("value", [None, 0, "false", False])
def test_unconfirmed_risk_is_not_a_deleted_scoring_requirement(records, value):
    candidate, tech, market = records
    tech["details"]["critical_risk"] = value
    tech["details"]["critical_risk_evidence"] = []
    result = evaluate(candidate, tech, market, 1)
    assert result["decision"] == "pass" and not result["critical_risk_confirmed"]


def test_confirmed_material_risk_blocks_score_pass(records):
    candidate, tech, market = records
    quote = "안전 사고로 현재 로봇의 공급과 운영이 중단되었습니다."
    tech["sources"][0]["text"] += " " + quote
    tech["details"].update(critical_risk=True, critical_risk_reason=quote, critical_risk_evidence=[{"source_id": "tech", "quote": quote}])
    result = evaluate(candidate, tech, market, 1)
    assert result["score_pass"] and result["decision"] == "hold" and result["critical_risk_confirmed"]


def test_fabricated_material_risk_is_not_confirmed(records):
    candidate, tech, market = records
    tech["details"].update(critical_risk=True, critical_risk_evidence=[{"source_id": "tech", "quote": "원문에 없는 중대 사고"}])
    result = evaluate(candidate, tech, market, 1)
    assert result["decision"] == "pass" and result["details"]["technology"]["critical_risk"] is None


@pytest.mark.parametrize("policy,decision", [("hold", "hold"), ("conditional", "conditional")])
def test_pending_qualification_is_separate_from_score(records, monkeypatch, policy, decision):
    monkeypatch.setitem(RUBRIC, "eligibility_pending_policy", policy)
    candidate, tech, market = records
    candidate["eligibility"]["no_exit"]["status"] = "unknown"
    result = evaluate(candidate, tech, market, 1)
    assert result["decision"] == decision and result["score_pass"]
    assert result["eligibility_status"] == "pending" and result["eligibility_issues"]
    assert result["qualification"]["no_exit"]["status"] == "unknown"


@pytest.mark.parametrize("change", ["missing_evidence", "other_company", "unsupported_failure"])
def test_unverified_qualification_is_pending_not_eligible(records, change):
    candidate, tech, market = records
    if change == "missing_evidence":
        candidate["sources"] = []
    elif change == "other_company":
        candidate["sources"][0]["company_id"] = "other"
    else:
        candidate["eligibility"]["unlisted"].update(status="fail", evidence=[])
    result = evaluate(candidate, tech, market, 1)
    assert result["eligibility_status"] == "pending" and result["decision"] == "conditional"


@pytest.mark.parametrize("policy", ["hold", "conditional"])
def test_listed_company_fails_even_at_eighteen_points(records, monkeypatch, policy):
    monkeypatch.setitem(RUBRIC, "eligibility_pending_policy", policy)
    candidate, tech, market = all_high(records)
    quote = "테스트기업은 2026년 6월 1일 코스닥에 상장했습니다."
    candidate["sources"][0]["text"] += " " + quote
    candidate["eligibility"]["unlisted"] = {"status": "fail", "reason": "상장 기업입니다.", "evidence": [{"source_id": "basic", "quote": quote}]}
    result = evaluate(candidate, tech, market, 1)
    assert result["total_score"] == 18 and result["decision"] == "hold"
    assert result["eligibility_status"] == "ineligible"


@pytest.mark.parametrize("field", ["identity", "operating"])
def test_identity_and_operating_status_are_qualification_checks(records, field):
    candidate, tech, market = all_high(records)
    candidate[field]["status"] = "unknown"
    result = evaluate(candidate, tech, market, 1)
    assert result["total_score"] == 18 and result["decision"] == "conditional" and result["eligibility_status"] == "pending"


def test_dated_closure_blocks_high_score(records):
    candidate, tech, market = all_high(records)
    update_finding(tech, 10, "테스트기업은 2026년 10월 1일 관련 사업을 종료하고 폐업했습니다.", category_value="stopped")
    result = evaluate(candidate, tech, market, 1)
    assert result["total_score"] == 16 and result["decision"] == "hold"
    assert result["eligibility_status"] == "ineligible"
    assert any("사업 중단" in reason for reason in result["reasons"])


@pytest.mark.parametrize("publication", [None, "2026-10-02"])
def test_new_operation_after_old_closure_requires_confirmation(records, publication):
    candidate, tech, market = all_high(records)
    update_finding(tech, 10, "테스트기업은 2024년 10월 1일 관련 사업을 중단했습니다.", category_value="stopped")
    tech["sources"][0]["published_at"] = publication
    result = evaluate(candidate, tech, market, 1)
    assert criterion(result, 10)["score"] is None
    assert "과거 사업 중단 이후" in criterion(result, 10)["reason"]
    assert not any("폐업 또는 관련 사업 중단 근거" in reason for reason in result["reasons"])


@pytest.mark.parametrize("version", [None, "1.0", "2.0"])
def test_old_analysis_is_not_silently_rescored(records, version):
    candidate, tech, market = records
    tech["rubric_version"] = version
    result = evaluate(candidate, tech, market, 1)
    assert result["total_score"] is None and result["decision"] == "hold"
    assert any("다시 실행" in reason for reason in result["reasons"])


def test_zero_requires_explicit_absence(records):
    candidate, tech, market = records
    target = market["findings"][1]
    target["numeric_value"] = 0
    assert criterion(evaluate(candidate, tech, market, 1), 6)["score"] is None
    update_finding(market, 6, "실증 고객은 0곳입니다.", numeric_value=0)
    assert criterion(evaluate(candidate, tech, market, 1), 6)["score"] == 1
    update_finding(market, 6, "실증 고객이 없다는 사실은 확인 불가입니다.", numeric_value=0)
    assert criterion(evaluate(candidate, tech, market, 1), 6)["score"] is None


def test_invalid_inputs_do_not_crash():
    result = evaluate(None, [], "bad", None)
    assert result["decision"] == "hold" and result["total_score"] is None


def test_market_context_remains_in_report_without_becoming_score(records):
    candidate, tech, market = records
    quote = "국내 물류 로봇 시장 규모는 2025년 1조 원입니다."
    market["sources"].append(source("sector", "__sector__", quote))
    market["details"].update(market_size=quote, market_size_evidence=[{"source_id": "sector", "quote": quote}])
    result = evaluate(candidate, tech, market, 1)
    assert result["decision"] == "pass" and result["total_score"] == 14
    assert result["details"]["market"]["market_size"] == quote
    assert "sector" in {s["source_id"] for s in result["sources"]}
    market["findings"][0]["evidence"] = [{"source_id": "sector", "quote": quote}]
    assert evaluate(candidate, tech, market, 1)["total_score"] is None


def test_invalid_display_claim_is_not_reported(records):
    candidate, tech, market = records
    market["details"].update(market_size="근거 없는 100조 원", market_size_evidence=[{"source_id": "market", "quote": "없는 시장 규모입니다."}], competitors=[{"name": "비교기업", "comparison": "검증되지 않은 비교", "evidence": [{"source_id": "forged", "quote": "위조 인용"}]}])
    result = evaluate(candidate, tech, market, 1)
    assert result["decision"] == "pass"
    assert result["details"]["market"]["market_size"] == "확인 필요"
    assert result["details"]["market"]["competitors"] == []
    assert market["details"]["market_size"] == "근거 없는 100조 원"


def test_qualitative_evidence_keeps_report_sources_without_changing_score(records):
    candidate, tech, market = records
    quote = "해당 기업의 CTO는 로봇 제어 분야 박사 학위가 있습니다."
    tech["sources"].append(source("team", "demo", quote))
    tech["qualitative_findings"] = [finding(5, "team", quote, category="phd_or_research")]
    tech["details"].update(team=quote, team_evidence=[{"source_id": "team", "quote": quote}])
    result = evaluate(candidate, tech, market, 1)
    assert result["total_score"] == 14 and result["decision"] == "pass"
    assert result["qualitative_findings"][0]["status"] == "verified"
    assert "team" in {x["source_id"] for x in result["sources"]}
    assert result["details"]["technology"]["team_evidence"]


@pytest.mark.parametrize("field", ["technology", "team"])
def test_unsupported_qualitative_claims_do_not_block_score_but_are_hidden(records, field):
    candidate, tech, market = records
    tech["qualitative_findings"] = [finding(4, "forged", "원문에 없는 특허 내용", items=["registered_patent"])]
    tech["details"][field] = "원문에 없는 분석 내용"
    tech["details"][field + "_evidence"] = [{"source_id": "forged", "quote": "원문에 없는 분석 내용"}]
    result = evaluate(candidate, tech, market, 1)
    assert result["total_score"] == 14 and result["decision"] == "pass"
    assert result["qualitative_findings"][0]["status"] == "unknown"
    assert result["qualitative_findings"][0]["evidence"] == []
    assert result["details"]["technology"][field] == "확인 필요"
