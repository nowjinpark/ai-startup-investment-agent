"""실제 실행 결과로 10쪽 이내 제출 PDF를 만듭니다.

사용법: python reporting/agent_submission.py --run-dir outputs/실행 --output outputs/평가보고서.pdf
본문은 state.json의 report를 보존하고, 실행 부록만 REFERENCE 앞에 넣습니다.
분량을 맞추려고 내용을 삭제하거나 글자를 자동으로 줄이지 않습니다.
"""
from __future__ import annotations

import argparse
import html
import json
import os
from pathlib import Path
import re
import tempfile

from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle

MAX_PAGES = 10
BODY_SIZE = 10.1
PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN = 38
# SimpleDocTemplate의 frame은 좌우에 6pt씩 내부 여백을 둡니다.
CONTENT_WIDTH = PAGE_WIDTH - 2 * MARGIN - 12


class ReportTooLongError(ValueError):
    """원문을 보존한 보고서가 제출 분량을 넘었습니다."""


def _read_json(path: Path, default=None):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise ValueError(f"실행 자료를 읽을 수 없습니다: {path.name}: {exc}") from exc


def _read_events(path: Path) -> list[dict]:
    if not path.exists():
        return []
    events = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except ValueError as exc:
            raise ValueError(f"events.jsonl {line_number}행이 올바른 JSON이 아닙니다") from exc
        if not isinstance(item, dict):
            raise ValueError(f"events.jsonl {line_number}행은 객체여야 합니다")
        events.append(item)
    return events


def _register_fonts(root: Path):
    candidates = [root / "assets", Path(__file__).resolve().parents[1] / "assets"]
    folder = next((p for p in candidates if (p / "NanumGothic-Regular.ttf").is_file()
                   and (p / "NanumGothic-Bold.ttf").is_file()), None)
    if folder is None:
        raise FileNotFoundError("assets/NanumGothic-Regular.ttf와 NanumGothic-Bold.ttf가 필요합니다")
    for name, filename in [("AgentReport", "NanumGothic-Regular.ttf"),
                           ("AgentReportBold", "NanumGothic-Bold.ttf")]:
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, str(folder / filename)))
    pdfmetrics.registerFontFamily("AgentReport", normal="AgentReport", bold="AgentReportBold",
                                  italic="AgentReport", boldItalic="AgentReportBold")


def _styles():
    base = dict(fontName="AgentReport", fontSize=BODY_SIZE, leading=14.2,
                wordWrap="CJK", splitLongWords=True, textColor=colors.black, spaceAfter=4)
    return {
        "body": ParagraphStyle("body", **base),
        "table": ParagraphStyle("table", **{**base, "leading": 13.4, "spaceAfter": 0}),
        "h1": ParagraphStyle("h1", fontName="AgentReportBold", fontSize=16, leading=21,
                             spaceBefore=8, spaceAfter=8, keepWithNext=True, wordWrap="CJK"),
        "h2": ParagraphStyle("h2", fontName="AgentReportBold", fontSize=12.4, leading=17,
                             spaceBefore=10, spaceAfter=6, keepWithNext=True, wordWrap="CJK"),
        "h3": ParagraphStyle("h3", fontName="AgentReportBold", fontSize=10.8, leading=15,
                             spaceBefore=7, spaceAfter=4, keepWithNext=True, wordWrap="CJK"),
    }


def _inline(text: str) -> str:
    """임의 HTML은 실행하지 않고, Markdown의 링크·굵게·코드만 표현합니다."""
    text = text.replace("\u2011", "-").replace("\r", "")
    # 링크 목적지도 PDF 본문에 보존하므로 출력물만으로 출처를 확인할 수 있습니다.
    text = re.sub(r"\[([^\]]+)\]\((https?://[^\s)]+)\)",
                  lambda m: m.group(2) if m.group(1) == m.group(2)
                  else f"{m.group(1)} ({m.group(2)})", text)
    escaped = html.escape(text, quote=False)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", escaped)
    escaped = re.sub(r"`([^`]+)`", r"\1", escaped)
    return escaped


def _paragraph(text: str, styles, name="body"):
    return Paragraph(_inline(str(text)), styles[name])


def _table(rows: list[list[str]], styles):
    columns = max(map(len, rows))
    if columns == 0:
        return Spacer(1, 1)
    rows = [row + [""] * (columns - len(row)) for row in rows]
    # 지나치게 넓은 비교표도 모든 열을 읽을 수 있게 행별 문장으로 풀어 씁니다.
    # 값은 생략하지 않으며 표 내용의 순서는 유지합니다.
    if columns > 5:
        headings = rows[0]
        output = []
        for row in rows[1:]:
            output.append(_paragraph(" | ".join(f"{key}: {value}" for key, value in zip(headings, row)), styles))
        return output
    widths = [CONTENT_WIDTH / columns] * columns
    if columns == 2:
        widths = [CONTENT_WIDTH * .26, CONTENT_WIDTH * .74]
    cells = [[_paragraph(value, styles, "table") for value in row] for row in rows]
    result = LongTable(cells, colWidths=widths, repeatRows=1, splitByRow=1, splitInRow=1,
                       hAlign="LEFT")
    result.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
        ("LINEBELOW", (0, 0), (-1, 0), .7, colors.black),
        ("LINEBELOW", (0, 1), (-1, -1), .25, colors.HexColor("#bbbbbb")),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return result


def _is_separator(line: str) -> bool:
    cells = line.strip().strip("|").split("|")
    return bool(cells) and all(re.fullmatch(r"\s*:?-{3,}:?\s*", cell) for cell in cells)


def _markdown(markdown: str, styles) -> list:
    """본문을 생략하지 않는 작은 Markdown 렌더러입니다."""
    lines, story, paragraph = markdown.splitlines(), [], []

    def flush():
        if paragraph:
            story.append(_paragraph(" ".join(paragraph), styles))
            paragraph.clear()

    i, in_code = 0, False
    while i < len(lines):
        line = lines[i].rstrip()
        if line.lstrip().startswith("```"):
            flush()
            in_code = not in_code
            i += 1
            continue
        if in_code:
            flush()
            story.append(_paragraph(line or " ", styles))
        elif not line.strip():
            flush()
        elif "|" in line and i + 1 < len(lines) and _is_separator(lines[i + 1]):
            flush()
            rows = [[x.strip() for x in line.strip().strip("|").split("|")]]
            i += 2
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                rows.append([x.strip() for x in lines[i].strip().strip("|").split("|")])
                i += 1
            table = _table(rows, styles)
            story.extend(table if isinstance(table, list) else [table])
            story.append(Spacer(1, 5))
            continue
        elif re.match(r"^#{1,6}\s+", line):
            flush()
            heading = re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", line)
            title = heading.group(2)
            level = "h1" if title.upper() in {"SUMMARY", "REFERENCE"} else "h2" if len(heading.group(1)) <= 2 else "h3"
            story.append(_paragraph(title, styles, level))
        elif re.match(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)", line):
            flush()
            story.append(_paragraph(re.sub(r"^\s*[-*+]\s+", "• ", line), styles))
        elif re.fullmatch(r"\s*(?:---+|___+|\*\*\*+)\s*", line):
            flush()
            story.append(Spacer(1, 5))
        else:
            paragraph.append(line.lstrip("> ") if line.startswith(">") else line)
        i += 1
    flush()
    return story


def _split_report(report: str) -> tuple[str, str]:
    summary = re.search(r"(?im)^#{1,6}\s+SUMMARY\s*#*\s*$", report)
    reference = list(re.finditer(r"(?im)^#{1,6}\s+REFERENCE\s*#*\s*$", report))
    if summary is None or not reference:
        raise ValueError("state.report에는 SUMMARY와 REFERENCE Markdown 제목이 필요합니다")
    if report[:summary.start()].strip():
        raise ValueError("첫 본문은 SUMMARY여야 합니다. SUMMARY 앞 내용을 확인해 주세요")
    last = reference[-1]
    if last.start() <= summary.end():
        raise ValueError("REFERENCE는 SUMMARY와 기업 평가 뒤에 있어야 합니다")
    if not report[summary.end():last.start()].strip() or not report[last.end():].strip():
        raise ValueError("SUMMARY 본문과 REFERENCE 출처 내용이 비어 있으면 안 됩니다")
    if re.search(r"(?m)^#{1,2}\s+", report[last.end():]):
        raise ValueError("REFERENCE 뒤에 별도 본문 섹션이 있습니다. REFERENCE를 마지막으로 배치해 주세요")
    return report[:last.start()].strip(), report[last.start():].strip()


def _shown(value) -> str:
    if value is None:
        return "기록 없음"
    if isinstance(value, bool):
        return "예" if value else "아니오"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _first(mapping, *keys):
    if isinstance(mapping, dict):
        for key in keys:
            if mapping.get(key) is not None:
                return mapping[key]
    return None


def _appendix(state: dict, usage, trace, events: list[dict], execution, styles) -> list:
    story = [_paragraph("설계와 실행 검증", styles, "h2")]
    story.append(_paragraph(
        "Orchestrator-Workers로 입력에 맞는 조사 과제를 나누고 병렬 결과를 취합한 뒤 보고서를 작성합니다. "
        "평가 결과는 State에 기록하며, 조건 분기는 재조사·재작성·종료를 결정합니다. "
        "이는 교재의 계획·State·제어 전략·평가 분리 원칙을 적용한 구성입니다.", styles))
    plan = state.get("plan", [])
    results = state.get("results", {})
    completed = len(results) if isinstance(results, (dict, list)) else 0
    rows = [["항목", "실행 기록"],
            ["실행 식별자", _shown(state.get("trace_id"))],
            ["상태 / 경로", f"{_shown(state.get('status'))} / {_shown(state.get('route'))}"],
            ["기업 / 계획 / 결과", f"입력 기업 {len(state.get('companies', []))}개 / 계획 과제 {len(plan)}개 / 결과 키 {completed}개"],
            ["회차 / 한도", f"revision={_shown(state.get('revision'))}, max_revisions={_shown(state.get('max_revisions'))}, step_count={_shown(state.get('step_count'))}"],
            ["이벤트", f"events.jsonl에 {len(events)}건 기록" if events else "이벤트 기록 없음"],
            ["실행 추적", _shown(_first(trace, "url", "run_url", "trace_url", "langsmith_url"))],
            ["추적 검증", _shown(_first(trace, "verified"))],
            ["추적 ID", _shown(_first(trace, "run_id", "trace_id", "id"))]]
    if isinstance(trace, dict) and trace.get("error"):
        rows.append(["추적 오류", str(trace["error"])])
    if state.get("last_error"):
        rows.append(["마지막 오류", str(state["last_error"])])
    story.append(_table(rows, styles))
    if state.get("plan_reason"):
        story.append(_paragraph("계획 이유: " + str(state["plan_reason"]), styles))
    if plan:
        plan_rows = [["과제 / 기업", "조사 관점과 완료 기준"]]
        labels = {"technology": "기술 성숙도", "market": "시장성", "stakeholders": "이해관계자", "application": "도메인 적용성"}
        for task in plan:
            if not isinstance(task, dict):
                continue
            views = ", ".join(labels.get(v, str(v)) for v in task.get("views", []))
            plan_rows.append([f"{task.get('task_id', '')} / {task.get('company_id', '')}",
                              f"{views}. {task.get('done_condition') or task.get('question', '')}"])
        story.append(_table(plan_rows, styles))

    story.append(_paragraph("품질 평가와 재처리", styles, "h3"))
    evaluation = state.get("evaluation") or {}
    criteria = evaluation.get("criteria", []) if isinstance(evaluation, dict) else []
    if criteria:
        rows = [["기준 / 판정", "판정 이유"]]
        names = {"groundedness": "근거성", "neutrality": "중립성", "bias": "편향", "coverage": "범위 충족"}
        for item in criteria:
            rows.append([f"{names.get(item.get('criterion'), item.get('criterion', ''))} / "
                         f"{'통과' if item.get('passed') is True else '미통과' if item.get('passed') is False else '기록 없음'}",
                         str(item.get("reason", "기록 없음"))])
        story.append(_table(rows, styles))
    else:
        story.append(_paragraph("평가 기준별 판정이 저장되어 있지 않습니다.", styles))
    for label, value in [("평가자의 제안", evaluation.get("action") if isinstance(evaluation, dict) else None),
                         ("평가 피드백", evaluation.get("feedback") if isinstance(evaluation, dict) else None),
                         ("현재 피드백", state.get("feedback")),
                         ("코드 검증 오류", evaluation.get("deterministic_errors") if isinstance(evaluation, dict) else None),
                         ("남은 과제", state.get("pending_task_ids"))]:
        if value:
            story.append(_paragraph(f"{label}: {_shown(value)}", styles))
    decisions = [event for event in events if event.get("node") in {"judge_node", "prepare_retry", "finish"}
                 or event.get("decision") in {"retry", "research", "rewrite", "fallback"}]
    if decisions:
        rows = [["분기 / 노드", "실행 중 기록한 이유"]]
        for event in decisions:
            rows.append([f"{event.get('decision', '')} / {event.get('node', '')}",
                         str(event.get("reason", "기록 없음"))])
        story.append(_table(rows, styles))

    story.append(_paragraph("소요 시간과 사용량", styles, "h3"))
    usage_dict = usage if isinstance(usage, dict) else {}
    calls = usage if isinstance(usage, list) else usage_dict.get("calls", usage_dict.get("records", []))
    totals = usage_dict.get("totals", usage_dict.get("summary", usage_dict))
    metric_rows = [["지표", "실측 또는 저장값"]]
    duration = _first(execution, "elapsed_seconds", "elapsed_s", "duration_seconds", "duration_s", "latency_s")
    if duration is None:
        duration = _first(usage_dict, "elapsed_seconds", "elapsed_s", "duration_s", "latency_s")
    metric_rows.append(["실행 경과 시간", f"{duration}초" if duration is not None else "기록 없음"])
    call_count = len(calls) if isinstance(calls, list) and calls else _first(execution, "llm_calls")
    if call_count is None:
        call_count = _first(totals, "call_count", "calls", "total_calls")
    metric_rows.append(["LLM 호출", _shown(call_count)])
    for label, keys in [("입력 토큰", ("input_tokens", "prompt_tokens")),
                        ("출력 토큰", ("output_tokens", "completion_tokens")),
                        ("합계 토큰", ("total_tokens",)),
                        ("비용 USD", ("total_cost_usd", "cost_usd", "total_cost"))]:
        value = _first(totals, *keys)
        if value is None and isinstance(calls, list) and calls and label != "비용 USD":
            values = [_first(item.get("usage", item), *keys) for item in calls if isinstance(item, dict)]
            if len(values) == len(calls) and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values):
                value = sum(values)
        if label == "비용 USD" and value is None:
            value = _first(execution, "estimated_cost_usd")
            if value is not None:
                value = f"{value} (추정 비용; 실제 청구액과 다를 수 있음)"
        metric_rows.append([label, _shown(value)])
    story.append(_table(metric_rows, styles))
    if isinstance(execution, dict):
        for key in ("validation", "tests", "verification", "limitations", "stop_reason", "mode"):
            if execution.get(key) is not None:
                story.append(_paragraph(f"{key}: {_shown(execution[key])}", styles))
    story.append(_paragraph("재현 방법과 해석 한계", styles, "h3"))
    story.append(_paragraph(
        "같은 저장 실행의 state.json, llm_usage.json, trace.json, events.jsonl 및 execution-summary.json을 보관합니다. "
        "PDF 재생성은 python reporting/agent_submission.py --run-dir <실행 폴더> --output <보고서.pdf>로 수행합니다. "
        "모델과 실행 설정은 저장소 README.md 및 실행 파일을 확인합니다.", styles))
    snapshot = _first(execution, "corpus_snapshot", "corpus_as_of", "data_as_of")
    story.append(_paragraph(
        f"자료 시점: {_shown(snapshot) if snapshot is not None else '기존 RAG의 2026-09-30 확인 스냅샷을 기준으로 사용'}. "
        "과제 기준일은 2026-10-13입니다. 이 실행에서 최신성을 별도로 검증한 기록이 없다면 그 이후 변화를 반영했다고 보지 않습니다. "
        "기업이 공개하지 않은 지표는 미확인 항목으로 남기며, LLM 평가의 통과는 외부 사실의 완전한 검증이나 실제 투자 성과를 보장하지 않습니다.", styles))
    story.append(_paragraph(
        "수업 적용 근거: AI Agent 설계 및 구축 교재의 실제 PDF 59–79쪽(Goal·State·협업·평가), "
        "118–133쪽(State·reducer·병렬 처리), 145–155쪽(원본 보존·실행 평가), 160–169쪽(판정과 gate 분리·종료·복구). "
        "이 보고서의 품질 판정과 수업 과제 채점표의 최종 점수는 구분합니다.", styles))
    return story


def build_report(run_dir, destination, *, repo_root=None) -> Path:
    """실행 폴더를 읽어 PDF를 만들고 경로를 반환합니다. 입력 파일은 변경하지 않습니다.

    실패 시 기존 destination을 보존합니다. 10쪽을 넘으면 내용을 줄이지 않고
    ReportTooLongError를 발생시키므로, 원문과 실행 설명을 검토한 뒤 다시 만들 수 있습니다.
    """
    run_dir, destination = Path(run_dir).resolve(), Path(destination).resolve()
    root = Path(repo_root).resolve() if repo_root else Path(__file__).resolve().parents[1]
    state = _read_json(run_dir / "state.json")
    if not isinstance(state, dict) or not isinstance(state.get("report"), str):
        raise ValueError("state.json의 report 문자열이 필요합니다")
    if destination.suffix.lower() != ".pdf":
        raise ValueError("출력 파일 확장자는 .pdf여야 합니다")
    body, references = _split_report(state["report"])
    usage = _read_json(run_dir / "llm_usage.json", {})
    trace = _read_json(run_dir / "trace.json", {})
    execution = _read_json(run_dir / "execution-summary.json", {})
    events = _read_events(run_dir / "events.jsonl")
    _register_fonts(root)
    styles = _styles()
    story = _markdown(body, styles)
    story.extend(_appendix(state, usage, trace, events, execution, styles))
    story.extend(_markdown(references, styles))
    destination.parent.mkdir(parents=True, exist_ok=True)

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont("AgentReport", 8.5)
        canvas.setFillColor(colors.HexColor("#444444"))
        canvas.drawString(MARGIN, 22, "Multi-Agent Orchestration · 실행 결과 기반 평가 보고서")
        canvas.drawRightString(PAGE_WIDTH - MARGIN, 22, str(document.page))
        canvas.restoreState()

    fd, temporary_name = tempfile.mkstemp(prefix=".agent-report-", suffix=".pdf", dir=destination.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        doc = SimpleDocTemplate(str(temporary), pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
                                topMargin=30, bottomMargin=38, title="AI 스타트업 멀티 에이전트 평가 보고서",
                                author="AI Agent 실습", allowSplitting=1)
        doc.build(story, onFirstPage=footer, onLaterPages=footer)
        reader = PdfReader(temporary)
        if len(reader.pages) > MAX_PAGES:
            raise ReportTooLongError(
                f"원문과 실행 설명을 보존한 PDF가 {len(reader.pages)}쪽으로 {MAX_PAGES}쪽을 초과합니다. "
                "내용을 삭제하거나 글자를 줄이지 않았습니다. report와 실행 설명을 검토해 주세요.")
        first, last = reader.pages[0].extract_text(), reader.pages[-1].extract_text()
        if "SUMMARY" not in first or "REFERENCE" not in "\n".join(p.extract_text() for p in reader.pages):
            raise ValueError("PDF의 SUMMARY 또는 REFERENCE를 확인할 수 없습니다")
        if not last.strip():
            raise ValueError("빈 마지막 페이지가 생성되었습니다")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def main():
    parser = argparse.ArgumentParser(description="실제 실행 기록으로 10쪽 이내 평가 PDF 생성")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(build_report(args.run_dir, args.output))


if __name__ == "__main__":
    main()
