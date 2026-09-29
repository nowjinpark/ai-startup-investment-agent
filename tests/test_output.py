"""고정 입력으로 PDF 출력만 검사합니다. 분석 에이전트·LLM을 호출하지 않습니다."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfReader

from export_outputs import export_report


class OutputTests(unittest.TestCase):
    def setUp(self):
        summary = "[연습용] 후보 1곳을 보류합니다. 실제 투자 근거가 없기 때문입니다."
        self.report = {
            "summary": summary,
            "markdown": f"# SUMMARY\n\n{summary}\n\n# 후보별 분석\n\n예제 로봇 회사 A의 자료는 미확인입니다.\n\n# REFERENCE\n\n실제 인용 자료가 없는 출력 검사 예제입니다.",
            "is_example": True,
        }

    def test_example_report_has_judgment_and_readable_korean_pdf(self):
        result = self.report
        with tempfile.TemporaryDirectory() as folder:
            paths = export_report(result, Path(folder))
            self.assertEqual(Path(paths["markdown"]).read_text(encoding="utf-8"), result["markdown"])
            reader = PdfReader(paths["pdf"])
            self.assertGreater(len(reader.pages), 0)
            self.assertLessEqual(len(reader.pages), 5)
            text = "\n".join(page.extract_text() for page in reader.pages)
            self.assertIn("예제 로봇 회사 A", text)
            self.assertIn("연습용 예제", text)
            self.assertLess(text.index("SUMMARY"), text.index("REFERENCE"))

    def test_summary_over_half_page_preserves_previous_files(self):
        result = self.report
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            paths = export_report(result, directory)
            previous = {key: Path(path).read_bytes() for key, path in paths.items()}
            summary = "긴 요약 문장입니다. " * 300
            oversized = {"summary": summary, "markdown": f"# SUMMARY\n\n{summary}\n\n# REFERENCE\n\n없음", "is_example": True}
            with self.assertRaisesRegex(ValueError, "반 쪽"):
                export_report(oversized, directory)
            for key, path in paths.items():
                self.assertEqual(Path(path).read_bytes(), previous[key])
            self.assertEqual(sorted(p.name for p in directory.iterdir()), ["report.md", "report.pdf"])

    def test_over_five_pages_leaves_no_partial_output(self):
        body = "\n\n".join("시장 규모와 기술 근거를 검증하는 긴 본문입니다. " * 15 for _ in range(50))
        oversized = {"summary": "[연습용] 모두 보류입니다.", "markdown": f"# SUMMARY\n\n[연습용] 모두 보류입니다.\n\n# 분석\n\n{body}\n\n# REFERENCE\n\n없음", "is_example": True}
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            with self.assertRaisesRegex(ValueError, "5쪽 이하"):
                export_report(oversized, directory)
            self.assertEqual(list(directory.iterdir()), [])

    def test_summary_field_cannot_hide_a_different_markdown_summary(self):
        result = self.report
        result["summary"] = "짧은 요약"
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, "같아야"):
                export_report(result, Path(folder))

    def test_invalid_requested_font_is_reported(self):
        result = self.report
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {"REPORT_FONT_PATH": str(Path(folder) / "missing.ttf")}):
                with self.assertRaisesRegex(ValueError, "글꼴 파일"):
                    export_report(result, Path(folder))
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_cid_fallback_without_a_local_font(self):
        # CID의 텍스트 인코딩과 경고를 검사합니다. 화면 표시는 뷰어 지원에 달려 있습니다.
        result = self.report
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {"REPORT_FONT_PATH": "", "ReportFontPath": ""}):
                with patch("export_outputs.Path.is_file", return_value=False):
                    with self.assertWarnsRegex(RuntimeWarning, "REPORT_FONT_PATH"):
                        paths = export_report(result, Path(folder))
            text = "\n".join(p.extract_text() for p in PdfReader(paths["pdf"]).pages)
            self.assertIn("보류", text)


if __name__ == "__main__":
    unittest.main()
