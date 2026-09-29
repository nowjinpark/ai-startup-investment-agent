"""C 담당: 시장과 경쟁사를 함께 분석합니다."""
from shared import Analysis, State


def run(state: State) -> dict:
    """C 담당 파일입니다. 입력은 state['company'], 결과는 market_competition입니다.

    TODO: 아래 예제를 실제 검색 결과를 사용하는 LLM 분석으로 교체하세요.
    시장 범위·자료 시점·고객 문제·경쟁 대안을 근거와 함께 설명하세요.
    """
    company = state["company"]
    result: Analysis = {
        "summary": f"[연습용] {company['name']}의 시장·경쟁 분석을 넣는 자리입니다.",
        "sources": [],
        "uncertainties": ["시장 규모, 고객 수요, 경쟁우위, 시장·규제·경쟁 리스크는 미확인입니다."],
        "is_example": True,
    }
    return {"market_competition": result}
