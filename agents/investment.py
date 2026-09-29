"""D 담당: 분석 근거를 확인하고 투자 판단과 이유를 정리합니다."""
from shared import Investment, State


def run(state: State) -> dict:
    """D 담당 파일입니다. 입력은 앞선 분석 결과, 출력은 investment입니다.

    TODO: company_info·technology·market_competition과 실제 근거를 검토해
    팀이 정한 기준으로 점수를 계산하고 판단하세요. LLM 판단도 근거를 확인하세요.
    """
    company = state["company"]
    result: Investment = {
        "decision": "hold",
        "reason": f"[연습용] {company['name']}의 실제 자료·실적·투자조건이 미확인이므로 보류합니다.",
        "score": None,
        "sources": [],
        "is_example": True,
    }
    return {"investment": result}
