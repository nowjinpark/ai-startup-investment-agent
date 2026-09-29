"""공통 PDF 저장 도구입니다. 보고서 담당자는 agents/report.py의 본문만 수정하세요.

Markdown의 기본 제목(#, ##, ###)과 문단을 지원합니다. 표·이미지·HTML은 렌더링하지 않습니다.
"""
import os
import re
import warnings
from pathlib import Path
from tempfile import TemporaryDirectory
from xml.sax.saxutils import escape

from pypdf import PdfReader
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate
from reportlab.platypus.doctemplate import LayoutError

from shared import Report

MARGIN = 48
# SimpleDocTemplate의 문단 영역에는 양쪽 6pt 여백이 추가됩니다.
CONTENT_WIDTH = A4[0] - 2 * MARGIN - 12
CONTENT_HEIGHT = A4[1] - 2 * MARGIN - 12


def _font_name() -> str:
    """사용자가 정한 글꼴 → 운영체제의 한글 글꼴 → 한국어 CID 글꼴 순서입니다."""
    configured = os.environ.get("REPORT_FONT_PATH") or os.environ.get("ReportFontPath")
    candidates = [Path(configured).expanduser()] if configured else [
        Path("/System/Library/Fonts/Supplemental/AppleGothic.ttf"),
        Path("C:/Windows/Fonts/malgun.ttf"),
        Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),
    ]
    path = next((candidate for candidate in candidates if candidate.is_file()), None)
    if configured and path is None:
        raise ValueError(f"REPORT_FONT_PATH의 글꼴 파일을 찾을 수 없습니다: {configured}")
    if path is not None:
        pdfmetrics.registerFont(TTFont("ReportKorean", str(path)))
        return "ReportKorean"
    warnings.warn("한글 TTF가 없어 CID 글꼴을 사용합니다. 뷰어에 따라 한글이 보이지 않을 수 있으므로 REPORT_FONT_PATH에 로컬 한글 TTF 경로를 지정하세요.", RuntimeWarning, stacklevel=2)
    pdfmetrics.registerFont(UnicodeCIDFont("HYSMyeongJo-Medium"))
    return "HYSMyeongJo-Medium"


def _blocks(markdown: str) -> list[tuple[int, str]]:
    """제목은 (제목 단계, 내용), 일반 문단은 (0, 내용)으로 나눕니다."""
    blocks, paragraph = [], []
    for line in markdown.splitlines() + [""]:
        heading = re.match(r"^(#{1,3})\s+(.+?)\s*$", line)
        if heading or not line.strip():
            if paragraph:
                blocks.append((0, " ".join(paragraph)))
                paragraph = []
            if heading:
                blocks.append((len(heading[1]), heading[2]))
        else:
            paragraph.append(line.strip())
    return blocks


def export_report(report: Report, output_dir: Path) -> dict[str, str]:
    """SUMMARY와 5쪽 제한을 확인한 뒤에만 report.md, report.pdf를 저장합니다."""
    blocks = _blocks(report["markdown"])
    headings = [(level, text) for level, text in blocks if level]
    if not blocks or blocks[0] != (1, "SUMMARY") or not headings or headings[-1] != (1, "REFERENCE"):
        raise ValueError("보고서는 # SUMMARY로 시작하고 마지막 제목이 # REFERENCE여야 합니다.")
    summary_end = next((i for i in range(1, len(blocks)) if blocks[i][0]), len(blocks))
    summary_text = " ".join(text for _, text in blocks[1:summary_end])
    if not report["summary"].strip() or " ".join(report["summary"].split()) != " ".join(summary_text.split()):
        raise ValueError("report.summary와 Markdown의 SUMMARY 본문이 같아야 합니다.")

    font = _font_name()
    styles = {
        0: ParagraphStyle("Body", fontName=font, fontSize=10.5, leading=16, spaceAfter=8, wordWrap="CJK"),
        1: ParagraphStyle("Section", fontName=font, fontSize=15, leading=21, spaceBefore=10, spaceAfter=8, keepWithNext=True, wordWrap="CJK"),
        2: ParagraphStyle("Subsection", fontName=font, fontSize=12, leading=18, spaceBefore=8, spaceAfter=6, keepWithNext=True, wordWrap="CJK"),
        3: ParagraphStyle("Detail", fontName=font, fontSize=11, leading=17, spaceBefore=6, spaceAfter=5, keepWithNext=True, wordWrap="CJK"),
    }
    paragraphs = [Paragraph(escape(text), styles[level]) for level, text in blocks]
    # 실제 PDF와 같은 문단·폭으로 SUMMARY 제목과 본문 높이를 측정합니다.
    summary_height = sum(p.wrap(CONTENT_WIDTH, CONTENT_HEIGHT)[1] + p.getSpaceBefore() + p.getSpaceAfter() for p in paragraphs[:summary_end])
    if summary_height > CONTENT_HEIGHT / 2:
        raise ValueError("SUMMARY가 반 쪽을 넘습니다. 내용을 줄인 뒤 다시 저장하세요.")

    def page_footer(canvas, document):
        canvas.saveState()
        canvas.setFont(font, 8)
        label = "연습용 예제 - 실제 투자평가 아님" if report["is_example"] else "투자평가 보고서"
        canvas.drawString(MARGIN, 27, label)
        canvas.drawRightString(A4[0] - MARGIN, 27, str(document.page))
        canvas.restoreState()

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    # 검사 전에는 임시 이름으로만 생성합니다. 실패해도 기존 정상 결과는 유지됩니다.
    with TemporaryDirectory(prefix=".report-", dir=output_dir) as temporary:
        temporary = Path(temporary)
        pdf_path, markdown_path = temporary / "report.pdf", temporary / "report.md"
        document = SimpleDocTemplate(str(pdf_path), pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
                                     topMargin=MARGIN, bottomMargin=MARGIN, title="AI 스타트업 투자평가")
        try:
            document.build(paragraphs, onFirstPage=page_footer, onLaterPages=page_footer)
        except LayoutError as error:
            raise ValueError("PDF 문단이 페이지에 배치되지 않습니다. 긴 문단을 나누세요.") from error
        with pdf_path.open("rb") as stream:
            page_count = len(PdfReader(stream).pages)
        if page_count > 5:
            raise ValueError(f"보고서가 {page_count}쪽입니다. SUMMARY와 REFERENCE를 포함해 5쪽 이하여야 합니다.")
        markdown_path.write_text(report["markdown"], encoding="utf-8")
        pdf_path.replace(output_dir / "report.pdf")
        markdown_path.replace(output_dir / "report.md")
    return {"markdown": str(output_dir / "report.md"), "pdf": str(output_dir / "report.pdf")}
