"""PDF 제출 형식, 원문 보존, 분량 상한을 실제 PDF로 검증합니다."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from pypdf import PdfReader
from reportlab.pdfbase import pdfmetrics

from reporting.agent_submission import BODY_SIZE, ReportTooLongError, build_report


def fixture_state():
    paragraphs = ["## SUMMARY", "", "테스트용 가상 기업 5곳을 네 관점으로 검토했습니다. 투자 판단은 추가 확인이 필요한 상태입니다."]
    companies, tasks, results = [], [], {}
    for number in range(1, 6):
        company_id = f"test-{number}"
        companies.append({"company_id": company_id, "name": f"가상기업{number}"})
        paragraphs.extend(["", f"## 가상기업{number}", "",
                           "| 관점 | 검토 결과 |", "| --- | --- |",
                           "| 기술 성숙도 | 시험 환경과 실제 운영 환경의 차이를 확인해야 합니다. [근거1] |",
                           "| 시장성 | 검증된 매출 정보가 없어 시장성을 확정하지 않았습니다. [근거1] |",
                           "| 이해관계자 | 고객과 파트너의 역할은 공개 자료 범위에서 확인했습니다. [근거1] |",
                           "| 도메인 적용성 | 실사용 조건과 규제 적합성 확인이 필요합니다. [근거1] |",
                           "", "**투자 판단:** 보류. **리스크:** 실증과 상용화 사이의 간극. & <자료 확인 필요>"])
        tasks.append({"task_id": company_id, "company_id": company_id,
                      "views": ["technology", "market", "stakeholders", "application"],
                      "question": "네 관점별 공개 근거 확인", "done_condition": "확인 내용과 미확인 내용을 구분"})
        results[company_id] = {"revision": 0, "status": "success"}
    paragraphs.extend(["", "## REFERENCE", "", "[근거1] 테스트 출처. 실제 투자 자료가 아닙니다.",
                       "https://example.com/" + "long-source-segment-" * 30 + "ENDSOURCE"])
    return {"report": "\n".join(paragraphs), "companies": companies, "plan": tasks,
            "results": results, "trace_id": "test-run", "revision": 0, "max_revisions": 2,
            "step_count": 6, "status": "approved", "route": "approve",
            "plan_reason": "회사별 과제는 독립적으로 조사할 수 있습니다.",
            "evaluation": {"action": "approve", "feedback": "테스트 입력의 형식을 확인했습니다.",
                           "criteria": [{"criterion": key, "passed": True, "reason": "테스트 데이터의 기준 확인"}
                                        for key in ["groundedness", "neutrality", "bias", "coverage"]]}}


class AgentPDFTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def write_state(self, state):
        (self.folder / "state.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

    def test_korean_content_order_usage_and_long_source_are_preserved(self):
        state = fixture_state()
        self.write_state(state)
        (self.folder / "llm_usage.json").write_text(json.dumps([
            {"stage": "planner", "model": "test-model", "seconds": 1,
             "usage": {"input_tokens": 100, "output_tokens": 40, "total_tokens": 140}},
            {"stage": "evaluator", "model": "test-model", "seconds": 2,
             "usage": {"input_tokens": 200, "output_tokens": 60, "total_tokens": 260}}]), encoding="utf-8")
        (self.folder / "execution-summary.json").write_text(json.dumps({
            "elapsed_seconds": 12.5, "estimated_cost_usd": 0.0123, "llm_calls": 2}), encoding="utf-8")
        output = build_report(self.folder, self.folder / "report.pdf")
        reader = PdfReader(output)
        text = "\n".join(page.extract_text() for page in reader.pages)
        compact = "".join(text.split())
        self.assertLessEqual(len(reader.pages), 10)
        self.assertIn("SUMMARY", reader.pages[0].extract_text())
        self.assertLess(text.index("SUMMARY"), text.index("가상기업1"))
        self.assertLess(text.index("설계와 실행 검증"), text.index("REFERENCE"))
        self.assertIn("ENDSOURCE", reader.pages[-1].extract_text())
        for number in range(1, 6):
            self.assertIn(f"가상기업{number}", compact)
        for value in ["기술성숙도", "시장성", "이해관계자", "도메인적용성", "자료확인필요", "12.5초", "400", "추정비용"]:
            self.assertIn(value, compact)
        self.assertNotIn("100점", text)
        self.assertGreaterEqual(BODY_SIZE, 10)
        # 긴 URL의 양끝과 반복 구간이 모두 남아 있어야 합니다.
        expected_url = "https://example.com/" + "long-source-segment-" * 30 + "ENDSOURCE"
        self.assertIn(expected_url, compact)
        self.assertEqual(json.loads((self.folder / "state.json").read_text()), state)
        # 긴 URL과 표의 각 텍스트 줄이 페이지 오른쪽을 벗어나지 않는지 확인합니다.
        # pypdf의 세로 문자 위치는 행 간격 연산에 따라 부정확할 수 있어 가로 경계만 봅니다.
        for page in reader.pages:
            def check_bounds(text, cm, tm, font, size):
                if not text.strip():
                    return
                x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
                name = "AgentReportBold" if font and "Bold" in str(font.get("/BaseFont", "")) else "AgentReport"
                for line in text.splitlines():
                    self.assertGreaterEqual(x, 30)
                    self.assertLessEqual(x + pdfmetrics.stringWidth(line, name, size), float(page.mediabox.width) - 30)
                if size != 8.5:  # 쪽 번호와 하단 표지만 8.5pt입니다.
                    self.assertGreaterEqual(size, 10)
            page.extract_text(visitor_text=check_bounds)

    def test_missing_optional_logs_are_reported_as_unknown(self):
        self.write_state(fixture_state())
        output = build_report(self.folder, self.folder / "report.pdf")
        text = "".join(page.extract_text() for page in PdfReader(output).pages)
        self.assertIn("기록 없음", text)
        self.assertIn("이벤트 기록 없음", text)
        self.assertNotIn("추정 비용", text)

    def test_over_limit_raises_without_replacing_previous_output(self):
        state = fixture_state()
        state["report"] = state["report"].replace("## REFERENCE", ("추가 근거 원문 보존 확인 문장입니다. " * 80 + "\n\n") * 60 + "## REFERENCE")
        self.write_state(state)
        output = self.folder / "report.pdf"
        output.write_bytes(b"previous-approved-artifact")
        with self.assertRaises(ReportTooLongError):
            build_report(self.folder, output)
        self.assertEqual(output.read_bytes(), b"previous-approved-artifact")
        self.assertEqual(list(self.folder.glob(".agent-report-*.pdf")), [])

    def test_missing_summary_or_reference_does_not_create_pdf(self):
        state = fixture_state()
        state["report"] = state["report"].replace("## SUMMARY", "## 요약")
        self.write_state(state)
        with self.assertRaisesRegex(ValueError, "SUMMARY"):
            build_report(self.folder, self.folder / "report.pdf")
        self.assertFalse((self.folder / "report.pdf").exists())

    def review_fixture(self, state):
        folder = self.folder / "reviewed"
        folder.mkdir()
        report = state["report"].replace("## REFERENCE", "## 제출 전 검토\n\n새로 확인한 검토 내용입니다.\n\n## REFERENCE")
        (folder / "report.md").write_text(report, encoding="utf-8")
        manifest = {
            "base_trace_id": state["trace_id"],
            "base_report_sha256": hashlib.sha256(state["report"].encode()).hexdigest(),
            "report_sha256": hashlib.sha256(report.encode()).hexdigest(),
            "automated_judge_applies_to": "base_run_only",
        }
        (folder / "review-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return folder, manifest

    def test_reviewed_pdf_preserves_run_and_separates_automatic_approval(self):
        state = fixture_state()
        self.write_state(state)
        review, _ = self.review_fixture(state)
        output = build_report(self.folder, self.folder / "reviewed.pdf", review_dir=review)
        text = "".join("".join(page.extract_text().split()) for page in PdfReader(output).pages)
        self.assertIn("새로확인한검토내용", text)
        self.assertIn("Judge가평가했다는뜻은아닙니다", text)
        self.assertEqual(json.loads((self.folder / "state.json").read_text()), state)

    def test_review_from_other_run_or_changed_text_is_rejected(self):
        state = fixture_state()
        self.write_state(state)
        review, manifest = self.review_fixture(state)
        for key in ("base_trace_id", "base_report_sha256", "report_sha256"):
            with self.subTest(key=key):
                changed = {**manifest, key: "wrong"}
                (review / "review-manifest.json").write_text(json.dumps(changed), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, key):
                    build_report(self.folder, self.folder / "reviewed.pdf", review_dir=review)
        self.assertFalse((self.folder / "reviewed.pdf").exists())

    def test_review_cannot_claim_original_judge_evaluated_changed_content(self):
        state = fixture_state()
        self.write_state(state)
        review, manifest = self.review_fixture(state)
        manifest["automated_judge_applies_to"] = "reviewed_report"
        (review / "review-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "자동 평가"):
            build_report(self.folder, self.folder / "reviewed.pdf", review_dir=review)


if __name__ == "__main__":
    unittest.main()
