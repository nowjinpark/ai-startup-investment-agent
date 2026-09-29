"""A 담당 — 박종찬: 사람이 고른 후보의 회사·팀 정보를 정리합니다."""
from shared import Analysis, State


def run(state: State) -> dict:
    """박종찬 담당 파일입니다. 입력은 state['company'], 결과는 company_info에 저장됩니다.

    TODO: 아래 예제 내용을 실제 자료 검색과 LLM 분석으로 교체하세요.
    회사 후보는 사람이 정해도 됩니다. 자동 회사 탐색은 필수가 아닙니다.
    """
    company = state["company"]
    result: Analysis = {
        "summary": f"[연습용] {company['name']}의 회사·팀 정보를 정리하는 자리입니다.",
        "sources": [],
        "uncertainties": ["사업 내용, 창업팀, 비상장·투자 단계·Exit 여부를 조사하지 않았습니다."],
        "is_example": True,
    }
    return {"company_info": result}
