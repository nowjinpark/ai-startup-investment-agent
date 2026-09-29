"""B 담당: 오픈 임베딩·RAG를 만들고 기술 분석에 연결합니다."""
from shared import Analysis, State


def run(state: State) -> dict:
    """B 담당 파일입니다. 입력은 state['company'], 결과는 technology에 저장됩니다.

    TODO: 아래 예제를 오픈 임베딩·문서 검색·LLM 기술 분석으로 교체하세요.
    검색한 문서의 제목·URL·페이지를 sources에 실제로 기록하세요.
    """
    company = state["company"]
    result: Analysis = {
        "summary": f"[연습용] {company['name']}의 AI 기술·제품 분석을 넣는 자리입니다.",
        "sources": [],
        "uncertainties": ["실제 RAG가 없습니다. 기술 성능, 제품 수준, 기술 리스크는 미확인입니다."],
        "is_example": True,
    }
    return {"technology": result}
