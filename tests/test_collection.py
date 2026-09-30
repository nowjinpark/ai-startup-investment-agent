import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfReader
from reportlab.pdfgen import canvas

from collection import Collector


def pdf_bytes(pages):
    output = io.BytesIO()
    document = canvas.Canvas(output)
    for index in range(pages):
        document.drawString(40, 750, f"Verified company document page {index + 1}. Customer and technology evidence.")
        document.showPage()
    document.save()
    return output.getvalue()


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.collector = Collector({"max_pages": 5, "max_pages_per_source": 8}, self.root / "corpus")

    def tearDown(self):
        self.temporary.cleanup()

    def local_pdf(self, pages=3, name="sample.pdf"):
        path = self.root / name
        path.write_bytes(pdf_bytes(pages))
        return path

    def test_local_pdf_preserves_pages_and_actual_files(self):
        sources = self.collector.add_local(self.local_pdf(), "c1", "technology", url="https://example.org/report.pdf")
        self.assertEqual(self.collector.page_count, 3)
        self.assertEqual([p["original_page"] for p in sources], [1, 2, 3])
        self.assertEqual(sum(len(PdfReader(self.collector.output_dir / p["file"]).pages) for p in sources), 3)
        self.assertEqual(sources[0]["saved_page"], 1)
        self.assertIn("Customer", sources[0]["text"])

    def test_global_cap_is_enforced_across_calls(self):
        self.collector.add_local(self.local_pdf(3), "c1", "technology")
        self.collector.add_local(self.local_pdf(7, "more.pdf"), "c1", "market")
        self.assertEqual(self.collector.page_count, 5)
        self.assertTrue(any(e["code"] == "page_limit" for e in self.collector.errors))

    def test_selected_original_pages(self):
        pages = self.collector.add_local(self.local_pdf(6), "c1", "technology", pages=[5, 2, 2])
        self.assertEqual([p["original_page"] for p in pages], [2, 5])
        self.assertIn("page 5", pages[1]["text"])
        self.assertEqual(self.collector.page_count, 2)
        self.assertEqual(self.collector.add_local(self.local_pdf(6), "c1", "market", pages=[0]), [])
        self.assertEqual(self.collector.page_count, 2)

    def test_export_pdf_has_identical_pages_and_source_bookmarks(self):
        self.collector.add_local(self.local_pdf(3), "c1", "technology", title="기업 기술 자료")
        path = self.collector.export_pdf()
        combined = PdfReader(path)
        self.assertEqual(len(combined.pages), self.collector.page_count)
        self.assertEqual(len(combined.outline), self.collector.page_count)
        for index, source in enumerate(self.collector.sources):
            original = PdfReader(self.collector.output_dir / source["file"])
            self.assertEqual(combined.pages[index].extract_text(), original.pages[0].extract_text())
            self.assertIn(source["source_id"], combined.outline[index]["/Title"])

    def test_hard_limit_cannot_exceed_200(self):
        collector = Collector({"max_pages": 999, "max_pages_per_source": 250}, self.root / "hard_limit")
        collector.add_local(self.local_pdf(201), "c1", "technology")
        self.assertEqual(collector.page_count, 200)
        self.assertEqual(len(list((collector.output_dir / "documents").glob("*.pdf"))), 200)

    def test_duplicate_updates_roles_and_keeps_original_company(self):
        path = self.local_pdf(1)
        first = self.collector.add_local(path, "c1", "technology")
        same = self.collector.add_local(path, "c1", "market")
        other = self.collector.add_local(path, "c2", "technology")
        self.assertEqual(self.collector.page_count, 1)
        self.assertEqual(first[0]["source_id"], same[0]["source_id"])
        self.assertEqual(set(same[0]["doc_types"]), {"technology", "market"})
        self.assertEqual(other[0]["company_id"], "c1")
        self.assertTrue(any(e["code"] == "company_mismatch" for e in self.collector.errors))

    def test_resume_keeps_global_budget(self):
        self.collector.add_local(self.local_pdf(3), "c1", "technology")
        self.collector._error('https://example.org/unavailable', '공개 원문 없음', 'collection_failed')
        resumed = Collector({"max_pages": 5}, self.collector.output_dir)
        self.assertEqual(resumed.page_count, 3)
        self.assertEqual(resumed.errors, self.collector.errors)
        resumed.add_local(self.local_pdf(7, "more.pdf"), "c1", "market")
        self.assertEqual(resumed.page_count, 5)

    def test_html_removes_menu_and_keeps_table_relationship(self):
        html = b'<title>Evidence</title><nav>MENU</nav><main><table><tr><th>Company</th><th>Stage</th></tr><tr><td>RobotCo</td><td>Series A</td></tr></table><p>' + b'Customer contract evidence. ' * 10 + b'</p></main>'
        text, title, date = self.collector._html(html)
        self.assertNotIn("MENU", text)
        self.assertIn("RobotCo | Series A", text)
        self.assertEqual(title, "Evidence")
        self.assertIsNone(date)
        with patch.object(self.collector, "_download", return_value=(html, "https://example.org/news", "text/html")):
            pages = self.collector.collect("https://example.org/news", "c1", "company")
        self.assertGreater(len(pages), 0)
        self.assertIsNone(pages[0]["original_page"])
        self.assertEqual(self.collector.page_count, len(pages))

    def test_policy_and_login_urls_are_skipped_before_download(self):
        with patch.object(self.collector, '_download') as download:
            for path in ['/policy/privacy', '/terms.html', '/member/login', '/privacy-policy/']:
                self.assertEqual(self.collector.collect('https://example.org' + path, 'c1', 'company'), [])
            download.assert_not_called()
        self.assertEqual(self.collector.page_count, 0)
        self.assertTrue(all(e['code'] == 'non_evidence_page' for e in self.collector.errors))

    def test_actual_policy_title_is_skipped_but_news_discussion_is_collected(self):
        for title, expected in [('개인정보처리방침 | RobotCo', False), ('이용약관', False),
                                ('RobotCo, 개인정보처리방침 개정과 규제 대응 기술 발표', True)]:
            html = ('<title>' + title + '</title><main>' + 'RobotCo의 기술 및 규제 대응 자료입니다. ' * 12 + '</main>').encode()
            with patch.object(self.collector, '_download', return_value=(html, 'https://example.org/article/123', 'text/html')):
                pages = self.collector.collect('https://example.org/article/123', 'c1', 'company', title='검색 결과 제목')
            self.assertEqual(bool(pages), expected)

    def test_private_addresses_are_rejected(self):
        for address in ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1"]:
            with self.subTest(address=address), patch("collection.socket.getaddrinfo", return_value=[(0, 0, 0, "", (address, 443))]):
                with self.assertRaises(ValueError):
                    self.collector._validate_url("https://example.org/")
        for url in ["file:///etc/passwd", "http://user:password@example.org/", "http://example.org:8080/"]:
            with self.assertRaises(ValueError):
                self.collector._validate_url(url)

    def test_unrelated_web_body_is_rejected_even_with_matching_title(self):
        html = b'<title>RobotCo official news</title><main><p>' + b'SpaceX rocket launch news and satellite operations. ' * 10 + b'</p></main>'
        with patch.object(self.collector, "_download", return_value=(html, "https://example.org/RobotCo", "text/html")):
            pages = self.collector.collect("https://example.org/RobotCo", "c1", "technology", title="RobotCo 기술", required_terms=["RobotCo"])
        self.assertEqual(pages, [])
        self.assertEqual(self.collector.page_count, 0)
        self.assertEqual(self.collector.errors[-1]["code"], "company_unrelated")
        self.assertEqual(list((self.collector.output_dir / "documents").glob("*.pdf")), [])

    def test_company_alias_in_web_body_is_accepted(self):
        html = b'<main><p>ROBOT CO product and customer contract evidence. ' + b'Navigation and field validation. ' * 8 + b'</p></main>'
        with patch.object(self.collector, "_download", return_value=(html, "https://example.org/product", "text/html")):
            pages = self.collector.collect("https://example.org/product", "c1", "technology", required_terms=["한국로봇", "RobotCo"])
        self.assertTrue(pages)
        self.assertEqual(pages[0]["company_id"], "c1")

    def test_company_check_reads_pdf_before_page_selection(self):
        output = io.BytesIO()
        document = canvas.Canvas(output)
        document.drawString(40, 750, "Navigation system technical details and field operation evidence.")
        document.showPage()
        document.drawString(40, 750, "RobotCo provides the system and this technical report.")
        document.showPage()
        document.save()
        with patch.object(self.collector, "_download", return_value=(output.getvalue(), "https://example.org/report.pdf", "application/pdf")):
            pages = self.collector.collect("https://example.org/report.pdf", "c1", "technology", pages=[1], required_terms=["RobotCo"])
        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0]["original_page"], 1)
        self.assertNotIn("RobotCo", pages[0]["text"])

    def test_unrelated_pdf_is_rejected_before_saving(self):
        with patch.object(self.collector, "_download", return_value=(pdf_bytes(2), "https://example.org/report.pdf", "application/pdf")):
            self.assertEqual(self.collector.collect("https://example.org/report.pdf", "c1", "technology", required_terms=["RobotCo"]), [])
        self.assertEqual(self.collector.page_count, 0)
        self.assertEqual(self.collector.errors[-1]["code"], "company_unrelated")

    def test_robots_disallow(self):
        with patch.object(self.collector, "_download", return_value=(b"User-agent: *\nDisallow: /private\n", "https://example.org/robots.txt", "text/plain")):
            self.assertFalse(self.collector._robot_allowed("https://example.org/private/data"))
            self.assertTrue(self.collector._robot_allowed("https://example.org/public"))

    def test_failure_is_recorded_without_secret(self):
        with patch.object(self.collector, "_download", side_effect=ValueError("자료를 읽지 못했습니다.")):
            self.assertEqual(self.collector.collect("https://example.org/?api_key=secret", "c1", "company"), [])
        self.assertNotIn("secret", json.dumps(self.collector.errors))
        self.assertTrue((self.collector.output_dir / "collection_errors.json").exists())

    def test_bad_input_does_not_consume_pages(self):
        path = self.root / "broken.pdf"
        path.write_bytes(b"not a PDF")
        self.assertEqual(self.collector.add_local(path, "c1", "technology"), [])
        self.assertEqual(self.collector.page_count, 0)
        self.assertTrue(self.collector.errors)


@unittest.skipUnless(os.getenv("RUN_NETWORK_TESTS") == "1", "공개 사이트 수집은 명시적으로 실행합니다.")
class PublicCollectionTests(unittest.TestCase):
    def test_public_html_and_pdf(self):
        with tempfile.TemporaryDirectory() as directory:
            collector = Collector({"max_pages": 4, "max_pages_per_source": 2}, directory)
            html = collector.collect("https://startuprecipe.co.kr/invest", "__discovery__", "company")
            pdf = collector.collect("https://www.pwc.com/kr/ko/insights/issue-brief/samilpwc_physical-ai-robot.pdf", "__sector__", "market")
            self.assertTrue(html, collector.errors)
            self.assertTrue(pdf, collector.errors)
            self.assertLessEqual(collector.page_count, 4)


if __name__ == "__main__":
    unittest.main()


def test_portfolio_keeps_company_description_and_official_url():
    text, _, _ = Collector._html(b'''<html><title>Portfolio</title><body>
      <nav><a href="https://ads.example.com">Menu</a></nav><main>
      <a href="https://robot.example.com/about">RobotAlpha develops autonomous warehouse robots</a>
      </main></body></html>''')
    assert 'RobotAlpha develops autonomous warehouse robots' in text
    assert 'https://robot.example.com/about' in text
    assert 'ads.example.com' not in text
