"""합성 그래프 결과의 파일 출력만 검증한다. 실제 투자 보고서 검증이 아니다."""
import copy
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from pypdf import PdfReader

from agents.report import write_reports
from app import build_graph, load_demo_candidates


class ReportingTests(unittest.TestCase):
    @staticmethod
    def initial_state():
        return {"candidates": load_demo_candidates(), "candidate_index": 0,
                "evaluations": [], "mode": "demo"}

    def assert_pdf_structure(self, path):
        pages = PdfReader(str(path)).pages
        self.assertGreaterEqual(len(pages), 3)
        self.assertLessEqual(len(pages), 5)
        texts = [page.extract_text() or "" for page in pages]
        self.assertIn("SUMMARY", texts[0])
        self.assertIn("REFERENCE", texts[-1])
        self.assertNotIn("REFERENCE", "\n".join(texts[:-1]))
        for text in texts:
            self.assertIn("DEMO ONLY", text)
            self.assertIn("Not an investment report", text)

    def test_demo_graph_writes_three_explicitly_demo_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            report_calls = []

            def report(state):
                report_calls.append(len(state["evaluations"]))
                return {"report_paths": write_reports(state["evaluations"], output_dir)}

            state = build_graph(report).invoke(self.initial_state())
            self.assertEqual(report_calls, [2])
            self.assertEqual([item["decision"] for item in state["evaluations"]], ["hold", "hold"])
            paths = state["report_paths"]
            self.assertEqual(set(paths), {"json", "markdown", "pdf"})
            for path in paths.values():
                self.assertTrue(Path(path).is_absolute())
                self.assertTrue(Path(path).is_file())
                self.assertGreater(Path(path).stat().st_size, 0)

            payload = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
            self.assertIs(payload["is_demo"], True)
            self.assertEqual(len(payload["evaluations"]), 2)
            self.assertTrue(all(item["is_demo"] is True for item in payload["evaluations"]))
            self.assertTrue(all(item["weighted_score"] is None for item in payload["evaluations"]))
            markdown = Path(paths["markdown"]).read_text(encoding="utf-8")
            headings = re.findall(r"^# (.+)$", markdown, re.MULTILINE)
            self.assertEqual(headings[0], "SUMMARY")
            self.assertEqual(headings[-1], "REFERENCE")
            self.assertIn("DEMO ONLY", markdown)
            self.assertIn("제출용 보고서가 아닙니다", markdown)
            self.assert_pdf_structure(paths["pdf"])

    def test_real_evaluation_is_rejected_before_writing_files(self):
        state = build_graph(lambda state: {}).invoke(self.initial_state())
        evaluations = copy.deepcopy(state["evaluations"])
        evaluations[0]["is_demo"] = False
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            with self.assertRaises(ValueError):
                write_reports(evaluations, output_dir)
            self.assertEqual(list(output_dir.iterdir()), [])

    def test_cid_font_fallback_still_produces_bounded_demo_pdf(self):
        state = build_graph(lambda state: {}).invoke(self.initial_state())
        with tempfile.TemporaryDirectory() as temporary:
            # 한글 TTF가 없는 환경도 지원해야 하므로 fallback을 제외하지 않는다.
            # 이 검증은 PDF 구조·추출 검증이며 모든 뷰어의 한글 렌더링 보장은 아니다.
            with patch("agents.report.os.environ", {}), \
                 patch("agents.report.Path.is_file", return_value=False):
                paths = write_reports(state["evaluations"], Path(temporary), stem="DEMO-cid-report")
            self.assert_pdf_structure(paths["pdf"])


if __name__ == "__main__":
    unittest.main()
