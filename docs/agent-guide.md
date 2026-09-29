# 내 역할을 구현하는 순서

1. README의 환경 설정을 마치고 `python main.py`로 예제를 확인합니다.
2. 개인 브랜치를 만들고 `agents/`에서 맡은 파일 하나를 엽니다.
3. `run(state)`의 예제 부분을 실제 구현으로 바꿉니다. 다른 네 파일은 그대로 둬도 됩니다.
4. 내 역할만 실행해 결과를 확인한 뒤 전체 연결을 확인하고 PR을 올립니다.

## 공통 약속

`state`는 지금까지 모은 정보를 담은 딕셔너리입니다. 형식은 `shared.py`를 기준으로 합니다.
함수는 **자기 결과 키 하나만 담은 딕셔너리**를 반환합니다. 받은 `state`를 직접 고치지 않습니다.
예를 들어 기술 담당자는 다음 형식을 유지합니다.

```python
from shared import State

def run(state: State) -> dict:
    company = state["company"]
    # 여기에 문서 검색·분석을 구현합니다.
    return {"technology": {
        "summary": f"{company['name']}의 기술 분석 예제",
        "sources": [],
        "uncertainties": ["실제 자료 확인 전입니다."],
        "is_example": True,
    }}
```

| 담당 | 사용할 주요 입력 | 반환 키와 내용 |
| --- | --- | --- |
| A. 기업 | `company`, `domain` | `company_info`: 기업 정보·출처·불확실한 점 |
| B. 기술 | `company`, `company_info` | `technology`: 기술 분석·출처·불확실한 점 |
| C. 시장·경쟁사 | 위 정보와 `technology` | `market_competition`: 시장·경쟁사 분석·출처·불확실한 점 |
| D. 투자 판단 | 위 세 분석 결과 | `investment`: `decision`, `reason`, `score`, `sources`, `is_example` |
| E. 보고서 본문 전체 | 현재 분석 결과와 `history` | `report`: `summary`, `markdown`, `is_example` |

앞의 세 분석은 모두 `summary`, `sources`, `uncertainties`, `is_example`을 넣습니다.
출처 한 건은 `{"title": "문서 제목", "url": "실제 출처 주소", "page": 3}` 형식입니다. 페이지가 없으면 `null`(Python에서는 `None`)로 둡니다.
게시일은 선택 항목 `published_at`에 문자열로 기록할 수 있습니다. 모르면 `None`으로 두거나 생략합니다.
투자 결정은 `invest` 또는 `hold`만 씁니다. `score`는 팀 기준의 0~100점이며 미확인이면 `None`입니다.
예제를 실제 근거로 바꾸기 전에는 `is_example=True`를 유지하고, 확인하지 못한 사실이나 출처를 만들지 않습니다.
실제 회사 정보는 `companies.json`의 `is_example`을 `false`로, 내 함수의 실제 분석 구현을 마쳤다면 반환값의 `is_example`을 `False`로 바꿉니다.
앞 단계에 예제가 남아 있으면 `main.py`가 결과를 다시 연습용으로 표시합니다. 내 파일만 완성해도 단독 개발은 가능하지만 전체 분석의 완성은 아닙니다.
후보 순서 변경과 기록 누적은 `main.py`가 맡습니다. 기업 담당자는 선택된 기업을 조사하면 됩니다.
보고서 담당자는 본문만 반환합니다. PDF 저장은 `export_outputs.py`가 맡으므로 이미지 생성·Word 변환은 필수가 아닙니다.
보고서 `markdown`의 첫 제목은 `# SUMMARY`, 마지막 제목은 `# REFERENCE`이며 `report.summary`는 SUMMARY 본문과 같아야 합니다.
공통 PDF 저장기는 기본 제목·문단만 지원합니다. 보고서 본문에 표·이미지를 넣지 마세요.

## 앞 담당자를 기다리지 않고 시험하기

```bash
python main.py --agent technology
python main.py --agent investment
python main.py --agent report
```

`data/test_state.json`에 앞 단계의 예제 결과가 모두 있습니다. 담당 이름만 바꾸면 각 역할을 실행합니다.
결과는 `outputs/역할명.json`에 저장되며 원래 입력 파일은 바뀌지 않습니다. `report`는 Markdown·PDF도 저장합니다.
다른 상황을 시험하려면 이 파일을 복사해 `data/my_test_state.json` 등을 만들고 필요한 입력을 수정합니다.

```bash
python main.py --agent technology --state data/my_test_state.json --output outputs/my-test
python main.py
```

기본 실행은 API 키 없이 돌아갑니다. 실제 모델·검색을 연결한 뒤에는 내가 바꾼 함수의 호출 비용이 발생할 수 있습니다.
실제 연동에 필요한 패키지만 추가하고 `requirements.txt` 변경은 팀에 공유합니다. 모듈을 불러올 때 API 호출·모델 다운로드를 실행하지 마세요.

## 수업 예제에서 참고할 부분

아래는 수업 배포 폴더 기준입니다. 원본 노트북 전체를 복사하지 말고 필요한 부분을 읽어 내 함수에 적용합니다.

| 담당 | 참고 예제 | 가져올 아이디어 |
| --- | --- | --- |
| 모두 | `langgraph-v1/00-Basic/02-State.ipynb`, `langgraph-v1/00-Basic/03-Graph.ipynb` | State와 노드 연결 |
| RAG 담당 | `langgraph-v1/20-RAG/13-AgenticRAG.ipynb` | 검색·평가·다시 검색하는 흐름 |
| 기업 | `langchain-v1/10-DocumentLoader/01-PDFLoader.ipynb` | PDF 읽기와 페이지 출처 보존 |
| 기술 | `langchain-v1/11-TextSplitter/01-RecursiveCharacterTextSplitter.ipynb`, `langchain-v1/13-VectorStore/01-FAISS.ipynb`, 위 `13-AgenticRAG.ipynb` | 청크 분할·벡터 검색·검색 결과 평가 |
| RAG 담당 | `langchain-v1/14-Retriever/04b-BGE-M3.ipynb` | 오픈소스 임베딩 사용 방식 |
| RAG 담당 | `langchain-v1/14-Retriever/10-Retriever-Evaluation.ipynb` | Hit Rate@K·MRR 측정 |
| 시장·경쟁사 | `langgraph-v1/20-RAG/03-WebSearch.ipynb` | 웹 검색과 자료 날짜·출처 확인 |
| 투자 | `langgraph-v1/20-RAG/02-RelevanceCheck.ipynb` | 명확한 평가 기준과 구조화된 판단 |
| 보고서 | `langgraph-v1/10-Agent/11-Multi-ReportAgent.ipynb` | 분석 결과를 본문으로 종합하는 부분 |

## PR 전에 확인할 것

- 내 함수가 자기 키 하나만 반환하고, 예제 입력과 실제 입력에서 모두 실행되는지 확인합니다.
- 내 함수 단독 실행 후 `python main.py`로 다른 역할과 연결되는지 확인합니다.
- 투자 기준과 보류 이유, 실제 출처, 검색 결과와 답변의 일치 여부는 사람이 확인합니다.
- 탐색·기술·시장 중 최소 하나에 Agentic RAG를 구현하고, 오픈소스 임베딩과 선택 이유를 남깁니다.
- 검색에 넣는 자료는 문서 개수와 관계없이 전체 200쪽 이하로 관리합니다.
- PDF는 5쪽 이하인지, Summary가 반 쪽 이하인지, Reference가 실제 출처인지 확인합니다.
- Hit Rate@K와 MRR을 실제 검색 자료로 측정하고 README의 미측정 값을 갱신합니다.
- 자기 역할 파일과 필요한 프롬프트·자료 출처를 PR에 담고 조원이 검토한 뒤 병합합니다.
- 공통 State·실행 순서를 바꾸려면 `shared.py`·`main.py`를 수정하기 전에 팀과 합의합니다.

CI는 다섯 역할을 예제 함수로 바꿔 연결과 형식을 검사합니다. CI 성공만으로 실제 검색·모델 답변 품질이 검증되지는 않습니다.
