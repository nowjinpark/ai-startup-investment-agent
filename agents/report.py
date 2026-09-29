"""E 담당 — 박진원: 보고서 본문을 만듭니다. PDF 저장은 공통 도구 export_outputs.py가 맡습니다."""
from shared import Report, State


def run(state: State) -> dict:
    """박진원 담당 파일입니다. 입력은 state['history'], 결과는 report에 저장됩니다.

    TODO: 실제 판단·근거와 각 담당자의 RAG/LLM 분석을 받아 보고서 본문을 완성하세요.
    이 함수는 보고서 내용만 만듭니다. 현재 출력은 실제 투자 분석이 아닌 예제입니다.
    """
    history = state.get("history", [])
    invested = [r["company"]["name"] for r in history if r["investment"]["decision"] == "invest"]
    held = [r for r in history if r["investment"]["decision"] == "hold"]
    reasons = " / ".join(r["investment"]["reason"] for r in held) or "해당 없음"
    summary = f"[연습용 판단] 후보 {len(history)}곳 중 투자 검토 {len(invested)}곳, 보류 {len(held)}곳입니다. 투자 검토 후보: {', '.join(invested) or '없음'}. 보류 이유: {reasons} 실제 투자 결론은 아니며, 근거와 미확인 정보는 후보별 본문에 표시합니다."
    lines = ["# SUMMARY", "", summary, "", "# 후보별 분석", ""]
    references = []
    for record in history:
        lines += [f"## {record['company']['name']}", ""]
        for key, label in [("company_info", "회사·팀"), ("technology", "기술·제품"), ("market_competition", "시장·경쟁")]:
            analysis = record[key]
            lines += [f"{label}: {analysis['summary']}", "미확인: " + "; ".join(analysis["uncertainties"]), ""]
            for source in analysis["sources"]:
                if source not in references:
                    references.append(source)
                lines += [f"{label} 근거: [{references.index(source) + 1}]", ""]
        investment = record["investment"]
        decision = "투자 검토" if investment["decision"] == "invest" else "보류"
        score = "미산정" if investment["score"] is None else str(investment["score"])
        lines += [f"판단: {decision} / 점수: {score}", f"판단 근거: {investment['reason']}", ""]
        for source in investment["sources"]:
            if source not in references:
                references.append(source)
            lines += [f"판단 출처: [{references.index(source) + 1}]", ""]
    lines += ["# 한계", "", "현재는 고정 예제입니다. 실제 자료·RAG·LLM 분석과 투자 기준 검증이 필요합니다.", "", "# REFERENCE", ""]
    for number, source in enumerate(references, 1):
        page = "" if source["page"] is None else f" / {source['page']}쪽"
        published = f" / 발행일: {source['published_at']}" if source.get("published_at") else ""
        lines += [f"[{number}] {source['title']} / {source['url']}{page}{published}", ""]
    if not references:
        lines += ["실제 인용 자료가 없습니다. 예제에 허위 출처를 추가하지 않았습니다."]
    result: Report = {"summary": summary, "markdown": "\n".join(lines), "is_example": True}
    return {"report": result}
