import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from pypdf import PdfReader

from agents.report import create_report, ReportTooLongError, _evidence_items


def record(number, score=24, decision="pass", separate_sources=False):
    company = f"company-{number}"
    sources, criteria = [], []
    for i in range(1, 11):
        source_id = f"{company}-s{i}"
        text = f"검증 자료 {i}: 실제 고객 환경에서 작동을 확인했습니다."
        sources.append({"source_id": source_id, "company_id": company, "title": f"기업 {number} 공식 기술·사업 자료",
                        "url": f"https://example.com/{company}/{i if separate_sources else 'report'}.pdf", "original_page": i,
                        "text": text})
        criteria.append({"criterion_id": i, "name": f"평가항목 {i}", "score": 3 if i <= 4 else 2,
                         "grade": "상" if i <= 4 else "중", "reason": text, "evidence": [{"source_id": source_id, "quote": text}]})
    return {"company_id": company, "name": f"예시기업{number}", "decision": decision, "total_score": score,
            "criteria": criteria, "sources": sources, "reasons": [] if decision == "pass" else ["고객 반복 구매와 사업화 근거 보완이 필요합니다."],
            "details": {"market_size": "확인 필요", "competitors": []}, "missing": [], "risks": []}


class ReportTests(unittest.TestCase):
    def generate(self, records, **metadata):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        result = create_report(records, directory.name, {"demo": True, "page_count": 15, **metadata})
        reader = PdfReader(result["pdf_path"])
        texts = [page.extract_text() for page in reader.pages]
        markdown = Path(result["markdown_path"]).read_text(encoding="utf-8")
        self.assertLessEqual(len(reader.pages), 5)
        self.assertIn("SUMMARY", texts[0])
        self.assertIn("REFERENCE", texts[-1])
        self.assertIn("테스트 자료", texts[0])
        return result, texts, markdown

    def test_empty_report(self):
        result, texts, markdown = self.generate([], stop_reason="no_candidates")
        self.assertEqual(result["page_count"], 1)
        self.assertIn("평가가 완료된 기업이 없어", texts[0])

    def test_five_passed_sorted_and_original_scores_unchanged(self):
        records = [record(i, 24 + i) for i in range(5)]
        before = deepcopy(records)
        result, texts, markdown = self.generate(records, stop_reason="target_reached")
        self.assertEqual(records, before)
        self.assertLess(texts[0].index("예시기업4"), texts[0].index("예시기업0"))
        self.assertIn("원문 페이지", texts[-1])
        self.assertIn("https://example.com/", markdown)
        self.assertIn("28/30", markdown)

    def test_twenty_held_reports_every_company_and_closest(self):
        records = [record(i, 23 - i % 5, "hold") for i in range(20)]
        result, texts, markdown = self.generate(records, stop_reason="candidates_exhausted")
        full = "\n".join(texts)
        for i in range(20):
            self.assertIn(f"예시기업{i}", full)
        self.assertIn("기준선에 가장 가까운 기업", full.replace("\n", ""))
        self.assertIn("추가 검토 항목", full)
        self.assertIn("평가한 기업과 수집 자료에 한정", full)

    def test_all_unknown_does_not_rank_missing_scores(self):
        records = [record(i, None, "hold") for i in range(3)]
        for rec in records:
            for criterion in rec["criteria"]:
                criterion.update(score=None, evidence=[])
        _, texts, markdown = self.generate(records)
        self.assertIn("기준선에 가장 가까운 기업을 판단할 수 없습니다", "".join(texts).replace("\n", ""))
        self.assertNotIn("https://example.com/", markdown)

    def test_large_reference_set_stays_five_pages(self):
        records = [record(i, 24, separate_sources=True) for i in range(5)]
        records += [record(i, 22, "hold", separate_sources=True) for i in range(5, 20)]
        result, texts, markdown = self.generate(records)
        self.assertLessEqual(result["page_count"], 5)
        self.assertIn("https://example.com/company-19/10.pdf", markdown)
        self.assertNotIn("…", "".join(texts))

    def test_invalid_and_cross_company_quotes_not_referenced(self):
        rec = record(1)
        rec["sources"][0]["company_id"] = "another-company"
        rec["criteria"][1]["evidence"][0]["quote"] = "원문에 없는 문장"
        for criterion in rec["criteria"][2:]:
            criterion["evidence"] = []
        _, texts, markdown = self.generate([rec])
        self.assertIn("본문에서 인용한 원문 자료가 없습니다", texts[-1])

    def test_invalid_pass_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                create_report([record(1, 23)], directory, {})

    def test_writer_cannot_add_claims(self):
        def writer(schema, system, payload):
            return {"sentence_indices": [99, -1, 0], "untrusted_summary": "시장 전체가 고성장합니다."}
        with tempfile.TemporaryDirectory() as directory:
            result = create_report([record(1, None, "hold")], directory, {"demo": True}, writer)
            markdown = Path(result["markdown_path"]).read_text(encoding="utf-8")
            self.assertNotIn("시장 전체가 고성장", markdown)

    def test_unverified_market_details_are_hidden_in_pdf_and_markdown(self):
        rec = record(1)
        rec["details"] = {"market": {"market_size": "765조 원", "market_size_evidence": [],
                                     "competitors": [{"name": "근거없는경쟁사", "evidence": []}]}}
        _, texts, markdown = self.generate([rec])
        self.assertNotIn("765조", markdown + "\n".join(texts))
        self.assertNotIn("근거없는경쟁사", markdown + "\n".join(texts))
        self.assertIn("시장 규모, 경쟁 비교 근거가 필요합니다", markdown)

    def test_market_details_have_verified_citations(self):
        rec = record(1)
        quote = "국내 관련 세부시장은 765조 원이며 비교경쟁사가 참여합니다."
        rec["sources"].append({"source_id": "extra-market", "company_id": "company-1", "text": quote,
                               "url": "https://example.com/market.pdf", "title": "시장 검증 보고서", "original_page": 7})
        evidence = [{"source_id": "extra-market", "quote": quote}]
        rec["details"] = {"market": {"market_size": "765조 원", "market_size_evidence": evidence,
                                     "competitors": [{"name": "비교경쟁사", "evidence": evidence}]}}
        _, texts, markdown = self.generate([rec])
        self.assertIn("시장 규모: 765조 원 [2]", markdown)
        self.assertIn("경쟁 비교: 비교경쟁사 [2]", markdown)
        self.assertIn("시장 검증 보고서", texts[-1])
        self.assertIn("https://example.com/market.pdf", markdown)

    def test_report_never_calls_paid_writer(self):
        calls = []
        def writer(schema, system, payload):
            calls.append(True)
            raise RuntimeError("비밀 키가 들어갈 수 있는 원본 오류")
        with tempfile.TemporaryDirectory() as directory:
            result = create_report([record(1, None, "hold")], directory, {}, writer)
            self.assertTrue(Path(result["pdf_path"]).exists())
            self.assertEqual(calls, [])

    def test_twenty_unknown_long_reasons_fit(self):
        rows = [record(i, None, "hold") for i in range(20)]
        for rec in rows:
            rec["reasons"] = ["공개 자료에서 원문과 회사의 관련성 및 최신 계약 현황을 추가로 확인해야 합니다. " * 100]
            for criterion in rec["criteria"]:
                criterion.update(score=None, evidence=[])
        result, texts, markdown = self.generate(rows)
        self.assertLessEqual(result["page_count"], 5)
        self.assertIn("예시기업19", "".join(texts))
        self.assertNotIn("…", "".join(texts))

    def test_eighty_distinct_used_sources_fit_five_pages(self):
        rows = [record(i, 24, separate_sources=True) for i in range(5)]
        for rec in rows:
            evidence = []
            for i in range(3):
                sid = f"{rec['company_id']}-extra-{i}"
                quote = f"별도 시장 근거 {i}를 확인했습니다."
                rec["sources"].append({"source_id": sid, "company_id": rec["company_id"], "text": quote,
                                       "url": f"https://example.com/{sid}.pdf", "title": "보완자료", "original_page": 1})
                evidence.append([{"source_id": sid, "quote": quote}])
            rec["details"] = {"market": {"market_size": "시장 규모 확인", "market_size_evidence": evidence[0],
                                         "competitors": [{"name": f"경쟁사{i}", "evidence": evidence[i]} for i in (1, 2)]}}
        rows += [record(i, 22, "hold", separate_sources=True) for i in range(5, 20)]
        result, texts, markdown = self.generate(rows)
        self.assertLessEqual(result["page_count"], 5)
        self.assertGreaterEqual(result["body_font_size"], 8.5)
        self.assertIn("https://example.com/company-19/10.pdf", markdown)

    def test_summary_contains_confirmed_strengths_and_readable_stop(self):
        rows = [record(i, 24 + i) for i in range(5)]
        _, texts, markdown = self.generate(rows, stop_reason="five_passed")
        self.assertIn("5개를 투자 검토 후보로 선정", texts[0])
        self.assertNotIn("five_passed", markdown)
        self.assertEqual(texts[0].count("주요 근거"), 2)
        self.assertIn("보완 항목", texts[0])
        self.assertIn("[1]", texts[0])

    def test_summary_all_hold_explains_reason_and_two_unknown_items(self):
        rows = [record(i, None, "hold") for i in range(3)]
        for rec in rows:
            for criterion in rec["criteria"]:
                criterion.update(score=None, evidence=[])
        _, texts, markdown = self.generate(rows)
        self.assertIn("3개 기업 모두 필수 평가 근거가 부족해 총점을 확정하지 못했습니다", texts[0])
        self.assertEqual(texts[0].count("주요 미확인 항목"), 2)

    def test_all_evidence_urls_and_dates_are_preserved(self):
        rec = record(1)
        quote = "독립 논문에서 기술 특성을 확인했습니다."
        rec["sources"].append({"source_id": "paper-extra", "company_id": "company-1", "text": quote,
                               "url": "https://example.com/paper.pdf", "title": "별도 논문", "original_page": 3,
                               "published_at": "2026-08-01", "collected_at": "2026-09-30T12:00:00"})
        rec["criteria"][0]["evidence"].append({"source_id": "paper-extra", "quote": quote})
        _, texts, markdown = self.generate([rec])
        self.assertIn("[1,2]", markdown)
        self.assertIn("https://example.com/paper.pdf", markdown)
        self.assertIn("발행 2026-08-01", markdown)
        self.assertIn("수집 2026-09-30", markdown)

    def test_report_preserves_material_hold_reason_and_full_url(self):
        rec = record(1, None, "hold")
        reason = "등록 권리자가 다른 법인이므로 현재 기업의 특허로 인정할 수 없습니다. 자료 발행일과 최신 권리자 확인이 필요합니다."
        rec["reasons"] = [reason]
        url = "https://example.com/reports/full-source-with-important-ending.pdf?reference=verified-evidence-end"
        for source in rec["sources"]:
            source["url"] = url
        result, texts, markdown = self.generate([rec])
        text = "".join(texts).replace("\n", "")
        self.assertIn(reason.replace(" ", ""), text.replace(" ", ""))
        self.assertIn(url, text)
        self.assertNotIn("…", text)
        reader = PdfReader(result["pdf_path"])
        urls = [str(annotation.get_object().get("/A", {}).get("/URI", "")) for page in reader.pages for annotation in page.get("/Annots", [])]
        self.assertIn(url, urls)

    def test_partial_score_and_coverage_are_not_changed(self):
        rec = record(1, 26.7, "pass")
        rec.update(normalized_score=26.7, observed_sum=24, coverage_count=9, score_range={"min": 25, "max": 27})
        rec["criteria"][7].update(score=None, grade="미확인", evidence=[])
        before = deepcopy(rec)
        _, texts, markdown = self.generate([rec])
        self.assertEqual(rec, before)
        self.assertIn("26.7/30", "".join(texts))
        self.assertIn("9/10", "".join(texts))
        self.assertIn("확인 항목 평균×10", "".join(texts))
        self.assertIn("25~27/30", "".join(texts))

    def test_raw_summary_and_revenue_as_market_size_are_not_reported(self):
        rec = record(1)
        rec["technology_summary"] = "검증되지않은독점기술"
        rec["overview"] = "검증되지않은우주사업"
        quote = "기업의 매출액은 131억 원입니다."
        rec["sources"].append({"source_id": "revenue", "company_id": rec["company_id"], "text": quote,
                               "url": "https://example.com/revenue", "title": "매출 자료", "original_page": None})
        rec["details"] = {"market": {"market_size": "131억 원 매출", "market_size_evidence": [{"source_id": "revenue", "quote": quote}]}}
        _, texts, markdown = self.generate([rec])
        text = "".join(texts) + markdown
        for forbidden in ("검증되지않은독점기술", "검증되지않은우주사업", "131억 원 매출"):
            self.assertNotIn(forbidden, text)

    def test_excluded_companies_are_separate_from_evaluated_count(self):
        _, texts, markdown = self.generate([record(1)], excluded_count=3)
        text = "".join(texts).replace("\n", "")
        self.assertIn("1개 기업을 평가", text)
        self.assertIn("제외된 3개 기업", text)

    def test_whitespace_in_source_quotes_uses_shared_validator(self):
        rec = record(1)
        rec["criteria"][0]["evidence"][0]["quote"] = "검증자료1:실제고객환경에서작동을확인했습니다."
        _, texts, markdown = self.generate([rec])
        self.assertIn("[1]", texts[0])

    def test_overlong_material_is_saved_and_report_fails_explicitly(self):
        rec = record(1, None, "hold")
        rec["reasons"] = [f"보류 사유 {i}: 거래 상대방과 계약 범위를 확인할 수 없어 해당 계약을 현재 기업의 실적으로 판단하기 어렵습니다." for i in range(600)]
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ReportTooLongError):
                create_report([rec], directory, {})
            text = (Path(directory) / "investment-report.md").read_text()
            self.assertIn("보류 사유 599", text)
            self.assertFalse((Path(directory) / "investment-report.pdf").exists())

    def test_compact_layout_preserves_every_distinct_hold_reason(self):
        rec = record(1, None, "hold")
        rec["reasons"] = [f"보류 사유 {i}: 거래 상대방과 계약 범위를 확인할 수 없어 해당 계약을 현재 기업의 실적으로 판단하기 어렵습니다." for i in range(300)]
        _, texts, markdown = self.generate([rec])
        pdf_text = "".join("".join("\n".join(text.splitlines()[1:]) for text in texts).split())
        for reason in rec["reasons"]:
            self.assertIn(reason, markdown)
            self.assertIn("".join(reason.split()), pdf_text)


if __name__ == "__main__":
    unittest.main()


class SixCriterionReportTests(unittest.TestCase):
    generate = ReportTests.generate

    def v3_record(self, number, decision="conditional", score=12):
        rec = record(number, score, decision)
        rec.update(rubric_version="3.0", score_scale=18, criterion_count=6, coverage_count=6,
                   eligibility_status="pending" if decision == "conditional" else "eligible",
                   score_pass=score >= 12,
                   reasons=["비상장 여부의 원문 확인이 필요합니다."] if decision == "conditional" else [])
        rec["qualitative_findings"] = [c for c in rec["criteria"] if c["criterion_id"] in (4, 5, 9)]
        rec["criteria"] = [c for c in rec["criteria"] if c["criterion_id"] in (2, 3, 6, 7, 8, 10)]
        for criterion in rec["criteria"]:
            criterion.update(score=2, grade="중")
        return rec

    def test_six_items_18_points_and_conditional_not_recommendation(self):
        rec = self.v3_record(1)
        _, texts, markdown = self.generate([rec])
        full = "".join(texts).replace("\n", "")
        self.assertIn("12/18", markdown)
        self.assertIn("추천 기업은 0개", full)
        self.assertIn("조건부 후보는 1개", full)
        self.assertIn("6개 항목", full)
        self.assertNotIn("24점", full)
        self.assertNotIn("/30", markdown)
        self.assertNotIn("/10", markdown)
        self.assertIn("창업팀", full)
        self.assertIn("기술·운영·규제 위험", full)
        self.assertIn("확인 조건", markdown)

    def test_pass_and_conditional_counts_separate(self):
        records = [self.v3_record(1, "pass", 14), self.v3_record(2, "conditional", 13)]
        _, texts, markdown = self.generate(records)
        full = "".join(texts).replace("\n", "")
        self.assertIn("추천 기업은 1개", full)
        self.assertIn("조건부 후보는 1개", full)
        self.assertLess(markdown.index("예시기업1"), markdown.index("예시기업2"))

    def test_pending_cannot_be_rendered_as_confirmed_recommendation(self):
        rec = self.v3_record(1, "pass")
        rec["eligibility_status"] = "pending"
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                create_report([rec], directory, {})

    def test_compact_summary_keeps_facts_plans_and_hold_reasons(self):
        rec = self.v3_record(1, "pass", 12)
        sales = next(c for c in rec["criteria"] if c["criterion_id"] == 3)
        fact = "보행 로봇 3000대를 판매했습니다. 연구용 로봇은 내년에 공급할 계획입니다."
        sales["reason"] = fact
        sales["evidence"] = [{"source_id": "company-1-s3", "quote": fact}]
        rec["sources"][2]["text"] = fact
        held = self.v3_record(2, "hold", 12)
        held.update(total_score=None, coverage_count=5, score_pass=False,
                    reasons=["수익모델 근거가 부족하여 보류합니다."])
        held["criteria"][3].update(score=None, evidence=[])
        before = deepcopy([rec, held])
        result, texts, _ = self.generate([rec, held], candidate_count=8, stop_reason="five_candidates")
        summary = texts[0].split("기업별 평가")[0].replace("\n", "")
        self.assertEqual([rec, held], before)
        self.assertEqual(result["layout_profile"], 4)
        self.assertIn("3000대를 판매했습니다", summary)
        self.assertIn("공급할 계획입니다", summary)
        self.assertIn("보류 사유", summary)
        self.assertIn("후보 8개 중 2개", summary)
        self.assertIn("나머지 6개 후보는 미평가", summary)
        self.assertNotIn("상 등급", summary)

    def test_compact_pdf_keeps_team_market_competitors_and_qualitative_risk(self):
        rec = self.v3_record(1, "conditional", 12)
        business = "예시기업1의 제품은 텍스트 전송에 그치지 않습니다. 실제 현장을 3D 스캔으로 정밀하게 재현합니다."
        rec.update(overview=business, overview_evidence=[{"source_id": "business", "quote": business}])
        rec["sources"].append({"source_id": "business", "company_id": rec["company_id"], "text": business,
                               "url": "https://example.com/business", "title": "사업 설명"})
        team = next(c for c in rec["qualitative_findings"] if c["criterion_id"] == 5)
        team["reason"] = "창업자는 로봇 제어 분야에서 12년간 연구했습니다."
        team["evidence"][0]["quote"] = team["reason"]
        rec["sources"][4]["text"] = team["reason"]
        risk = next(c for c in rec["qualitative_findings"] if c["criterion_id"] == 9)
        risk["reason"] = "안전 인증을 준비하고 있습니다. 외부 안전 검증 완료 여부는 확인되지 않습니다."
        risk["evidence"][0]["quote"] = risk["reason"]
        rec["sources"][8]["text"] = risk["reason"]
        quote = "2025년 국내 조리로봇 참고시장은 1000대이며 기존 수작업이 대체 수단입니다."
        source = {"source_id": "market", "company_id": rec["company_id"], "text": quote,
                  "url": "https://example.com/market-scope", "title": "시장 범위", "published_at": "2025-12-01"}
        rec["sources"].append(source)
        evidence = [{"source_id": "market", "quote": quote}]
        rec["details"] = {"market": {"market_size": "2025년 국내 조리로봇 참고시장 1000대이며 회사 TAM은 아닙니다.",
                                     "market_size_evidence": evidence,
                                     "competitors": [{"name": "기존 수작업", "comparison": "자동 조리의 대체 수단입니다.", "evidence": evidence}]},
                          "technology": {"critical_risk": None}}
        _, texts, _ = self.generate([rec])
        full = "".join(texts).replace("\n", "")
        for value in ("실제 현장을 3D 스캔으로 정밀하게 재현", "12년간", "2025년 국내", "1000대", "회사 TAM은 아닙니다", "기존 수작업", "안전 인증을 준비", "확인되지 않습니다"):
            self.assertIn(value, full)
        self.assertNotIn("관련 경력의 원문 근거를 확인했습니다", full)

    def test_held_company_market_and_risk_survive_condensed_section(self):
        rows = [self.v3_record(1, "pass", 12), self.v3_record(2, "hold", 12)]
        held = rows[1]
        held.update(total_score=None, score_pass=False, coverage_count=5,
                    reasons=["유료 구매 계약의 근거가 부족합니다."])
        held["criteria"][1].update(score=None, evidence=[])
        quote = "2025년 한국 산업용 로봇 설치는 30000대이며 기업별 매출과 구분됩니다."
        held["sources"].append({"source_id": "sector", "company_id": "__sector__", "text": quote,
                                "url": "https://example.com/sector-market", "title": "참고시장"})
        held["details"] = {"market": {"market_size": quote, "market_size_evidence": [{"source_id": "sector", "quote": quote}], "competitors": []}}
        risk = next(c for c in held["qualitative_findings"] if c["criterion_id"] == 9)
        risk["reason"] = "희귀 상황의 안전 검증이 필요합니다."
        held["sources"][8]["text"] = risk["reason"]
        risk["evidence"][0]["quote"] = risk["reason"]
        _, texts, _ = self.generate(rows)
        full = "".join(texts).replace("\n", "")
        self.assertIn("보류 기업", full)
        self.assertIn("30000대", full)
        self.assertIn("희귀 상황의 안전 검증", full)
        self.assertIn("https://example.com/sector-market", full)

    def test_sector_context_is_allowed_only_for_nonscoring_comparison_and_risk(self):
        rec = self.v3_record(1, "conditional", 12)
        quote = "Flippy automates the fry station. Safety validation remains necessary."
        rec["sources"].append({"source_id": "context", "company_id": "__sector__", "text": quote,
                               "url": "https://example.com/flippy", "title": "조리로봇 비교 자료"})
        evidence = [{"source_id": "context", "quote": quote}]
        rec["details"] = {"market": {"competitors": [{"name": "Flippy", "comparison": "튀김 공정 자동화 대안입니다. 대상 제품은 굽기 공정을 다룹니다. 제3자 비교 실측은 없습니다.", "evidence": evidence}],
                                     "context_risks": [{"type": "규제", "reason": "업계 공통 안전 검증 과제이며 해당 기업의 위험 발생을 뜻하지 않습니다.", "evidence": evidence}]}}
        rec["qualitative_findings"] = [{"criterion_id": 9, "reason": "안전 검증의 추가 확인이 필요합니다.", "evidence": evidence}]
        for number in (2, 3, 6, 7, 8, 10):
            self.assertEqual(_evidence_items(rec, {"criterion_id": number, "score": 3, "evidence": evidence}), [])
        self.assertEqual(_evidence_items(rec, {"criterion_id": 9, "score": 3, "evidence": evidence}), [])
        before = deepcopy(rec)
        _, texts, markdown = self.generate([rec])
        self.assertEqual(rec, before)
        full = "".join(texts).replace("\n", "")
        self.assertIn("Flippy", full)
        self.assertIn("제3자 비교 실측은 없습니다", full)
        self.assertIn("대상 제품은 굽기 공정을 다룹니다", full)
        self.assertIn("안전 검증의 추가 확인", full)
        self.assertIn("업계 위험·확인 사항", full)
        self.assertIn("해당 기업의 위험 발생을 뜻하지 않습니다", full)
        self.assertIn("https://example.com/flippy", markdown)

    def test_explanatory_endings_are_polite_without_changing_quotes_or_records(self):
        rec = self.v3_record(1, "conditional", 12)
        text = '예시기업1은 조리 로봇 이다. 공간 데이터를 제공한다. 판매를 준비하고 있다. 회사는 “내년에 공급한다.”라고 설명했다.'
        rec.update(overview=text, overview_evidence=[{"source_id": "prose", "quote": text}])
        rec["sources"].append({"source_id": "prose", "company_id": rec["company_id"],
                               "text": text, "url": "https://example.com/prose", "title": "사업 설명"})
        before = deepcopy(rec)
        _, texts, markdown = self.generate([rec])
        full = "".join(texts).replace("\n", "")
        for value in ("조리 로봇입니다", "공간 데이터를 제공합니다", "준비하고 있습니다", "설명했습니다"):
            self.assertIn(value, full)
            self.assertIn(value, markdown)
        self.assertIn("“내년에 공급한다.”", full)
        self.assertIn("> " + text, markdown)
        self.assertEqual(rec, before)
