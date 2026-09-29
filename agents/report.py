"""명백히 표시한 가상기업 데모 보고서. 실제 제출 보고서는 팀이 구현·검증합니다."""
import json
import os
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, PageBreak
from pypdf import PdfReader

from agents.state import Evaluation, WorkflowState


def report(state: WorkflowState) -> dict:
    """6단계: 가상 예제 결과를 outputs/demo에 저장합니다."""
    output_dir = Path(__file__).resolve().parents[1] / "outputs" / "demo"
    return {"report_paths": write_reports(state["evaluations"], output_dir)}


def _font() -> str:
    configured = os.environ.get("REPORT_FONT_PATH")
    options = [configured] if configured else ["/System/Library/Fonts/Supplemental/AppleGothic.ttf"]
    for location in options:
        if location and Path(location).is_file():
            pdfmetrics.registerFont(TTFont("ReportKorean", location))
            return "ReportKorean"
    pdfmetrics.registerFont(UnicodeCIDFont("HYSMyeongJo-Medium"))
    return "HYSMyeongJo-Medium"


def write_reports(evaluations: list[Evaluation], output_dir: Path,
                  stem: str = "DEMO-report") -> dict[str, str]:
    if not evaluations or not all(item["is_demo"] for item in evaluations):
        raise ValueError("현재 출력기는 가상기업 demo 전용입니다. 실제 보고서 출력은 구현 후 연결하세요.")
    if len(evaluations) > 3:
        raise ValueError("데모 PDF는 최대 3개 후보를 지원합니다.")
    if Path(stem).name != stem:
        raise ValueError("stem에는 파일 이름만 지정하세요.")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {kind: output_dir / f"{stem}.{ext}" for kind, ext in
             [("json", "json"), ("markdown", "md"), ("pdf", "pdf")]}
    sources = {}
    for evaluation in evaluations:
        used_ids = {eid for score in evaluation["scores"].values()
                    for eid in score["evidence_ids"]}
        for analysis in evaluation["analyses"]:
            for evidence in analysis["evidence"]:
                if evidence["id"] in used_ids:
                    sources[(evidence["candidate_id"], evidence["id"])] = evidence

    warning = "DEMO ONLY - 가상기업 연결 테스트. 실제 투자 평가 또는 제출용 보고서가 아닙니다."
    summary = "분석 결과를 공통 형식으로 전달하고, 투자/보류 분기 후 보고서를 생성하는 흐름을 확인합니다."
    md = ["# SUMMARY", warning, summary]
    font = _font()
    body = ParagraphStyle("body", fontName=font, fontSize=10, leading=15,
                          wordWrap="CJK", spaceAfter=7)
    heading = ParagraphStyle("heading", parent=body, fontSize=16, leading=22,
                             textColor=colors.HexColor("#174C46"), spaceAfter=14)
    flow = []

    def add(text: str, title: bool = False):
        flow.append(Paragraph(escape(str(text)).replace("\n", "<br/>"), heading if title else body))

    add("SUMMARY", True)
    add(warning)
    add(summary)
    add("확인 대상: 함께 주고받는 정보 형식, 보류 시 다음 후보 이동, 전체 후보 종료, 파일 출력.")
    add("실제 RAG 검색·LLM 분석·모델 비교·기업 평가는 별도 구현 항목입니다.")
    for evaluation in evaluations:
        flow.append(PageBreak())
        name = evaluation["candidate"]["name"]
        add(name, True)
        decision = f"판단: {evaluation['decision']} / 근거 충족 비중: {evaluation['coverage']:.0%}"
        add(decision)
        add(evaluation["reason"])
        md.extend([f"\n## {name}", decision, evaluation["reason"]])
        for analysis in evaluation["analyses"]:
            line = f"{analysis['section']}: {analysis['summary']}"
            add(line)
            md.append(line)
        add("확인되지 않은 사항")
        missing = list(dict.fromkeys(x for a in evaluation["analyses"] for x in a["missing_information"]))
        add(" / ".join(missing) if missing else "데모 입력에서 추가 미확인 항목 없음")
        md.extend(missing)
        score_text = "; ".join(f"{key}: {value['value'] if value['value'] is not None else '미확인'}"
                               for key, value in evaluation["scores"].items())
        add(score_text)
        md.append(score_text)

    flow.append(PageBreak())
    add("REFERENCE", True)
    add("아래 항목은 연결 테스트용 가상 근거입니다. 실제 조사자료로 인용하면 안 됩니다.")
    md.append("\n# REFERENCE\n가상 근거: 실제 조사자료가 아닙니다.")
    for evidence in sources.values():
        line = f"[{evidence['candidate_id']}:{evidence['id']}] {evidence['title']} - {evidence['url']}"
        add(line)
        md.append(line)

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#64748B"))
        canvas.drawString(42, 26, "DEMO ONLY - Synthetic data / Not an investment report")
        canvas.drawRightString(A4[0] - 42, 26, str(doc.page))
        canvas.restoreState()

    SimpleDocTemplate(str(paths["pdf"]), pagesize=A4, rightMargin=42, leftMargin=42,
                      topMargin=44, bottomMargin=44).build(flow, onFirstPage=footer, onLaterPages=footer)
    if len(PdfReader(str(paths["pdf"])).pages) > 5:
        raise ValueError("데모 보고서가 5쪽을 초과했습니다. 문서 구성을 조정하세요.")
    paths["json"].write_text(json.dumps({"is_demo": True, "evaluations": evaluations},
                                     ensure_ascii=False, indent=2), encoding="utf-8")
    paths["markdown"].write_text("\n\n".join(md) + "\n", encoding="utf-8")
    return {kind: str(path.resolve()) for kind, path in paths.items()}
