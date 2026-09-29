# 수업 예제를 보면서 과제 구현하기

이 문서는 각자 받은 수업 자료를 찾아보는 안내서입니다. 수업 PDF와 예제 원본은 이 공개 저장소에 재배포하지 않습니다.
기준은 [교수님 과제 안내](https://actually-war-1ea.notion.site/AI-1cf7f4c86693800e9e11fa490ed1a2ff)와 [RAG Pipeline 수업](https://actually-war-1ea.notion.site/RAG-Pipeline-1b67f4c8669381ecbf5dcda906ae38b3)입니다.
아래 수업 예제를 교수님 과제의 6단계 흐름에 맞게 조합합니다.

## 먼저 함께 볼 파일

1. `project.json`: 팀이 고른 회사·도메인·분석 기준일·후보 목록을 확인합니다. 회사는 바꿀 수 있습니다.
2. `evaluation.json`: 점수 기준과 판단 조건을 함께 정합니다. 투자평가 점수와 수업 채점표는 다른 것입니다.
3. `data/example.json`과 `start.ipynb`: 가상 입력과 데모 흐름을 읽습니다. 실제 기업의 사실이나 분석 결과로 사용하지 않습니다.
4. `agents/state.py`: 각 함수가 받아서 넘길 공통 작업 기록을 맞춥니다. 필드 이름을 각자 다르게 만들지 않습니다.
5. `app.py`: 담당 함수가 어떤 순서와 조건으로 연결되는지 확인합니다.

**현재는 일반 함수를 노드로 연결한 시작 데모입니다. 실제 문서 검색·오픈 임베딩·RAG·LLM 분석은 구현 전입니다.**
데모가 끝까지 실행되거나 파일이 생성돼도 실제 멀티에이전트와 Agentic RAG가 완성된 것은 아닙니다.

## 강의 PDF에서 찾는 위치

PDF 이름은 `4) 생성형AI_6.RAG Pipeline 설계 및 구축_배기주.pdf`입니다.
아래 숫자는 **PDF 뷰어 페이지**입니다. 슬라이드 하단 번호는 1 작습니다. 예: 뷰어 26쪽 = 하단 25쪽.

| 볼 내용 | 뷰어 페이지 | 쉬운 뜻 |
| --- | --- | --- |
| 전체 RAG 흐름 | 26–28 | 문서를 준비하고, 질문에 맞는 근거를 찾아 답변하기 |
| Loader / Splitter | 29–33, 40–41 | PDF를 읽고 작은 조각으로 나누며 출처·페이지를 보존하기 |
| Embedding | 45, 48–49 | 글의 의미를 검색 가능한 숫자로 바꾸기, 모델 선정 근거 세우기 |
| Vector Store / Retriever | 50–51, 62–65 | 문서 조각을 저장하고 관련 근거를 찾아오기 |
| Prompt / LLM / Chain | 79–84 | 찾은 근거와 질문을 묶어 답변 생성까지 연결하기 |
| 검색·답변 평가 | 85–89 | 정답 근거를 찾았는지와 답변이 타당한지를 따로 검사하기 |
| Agentic RAG | 123–131 | 필요한 도구를 고르고, 근거가 부족하면 질문을 고쳐 다시 검색하기 |
| State / Node / Edge | 142–147 | 공통 작업 기록 / 작업 함수 / 실행 순서와 갈림길 |

## 담당별로 볼 예제와 구현할 파일

아래 예제 경로는 각자 받은 수업 자료의 `ai-service/` 아래 기준입니다. 예제 전체를 복사하기보다 필요한 셀의 입력·처리·출력을 이해하고 옮깁니다.

| 역할 | 먼저 볼 수업 예제 | 우리 저장소에서 할 일 |
| --- | --- | --- |
| A — 자료·회사 | `langchain-v1/10-DocumentLoader/01-PDFLoader.ipynb`, `langchain-v1/11-TextSplitter/01-RecursiveCharacterTextSplitter.ipynb` | 자료 추출·분할과 출처·페이지 관리를 만들고 `agents/company.py`에 회사·팀 분석 연결 |
| B — 임베딩·RAG·기술 | `langchain-v1/13-VectorStore/01-FAISS.ipynb`, `langchain-v1/14-Retriever/01-VectorStoreRetriever.ipynb`, `langchain-v1/14-Retriever/10-Retriever-Evaluation.ipynb` | 오픈 임베딩·검색 함수를 만들고 `agents/technology.py`에서 실제 근거를 사용. 다른 담당자도 호출할 검색 입출력 공유 |
| C — 시장·경쟁 | `langgraph-v1/20-RAG/01-NaiveRAG.ipynb`, `langgraph-v1/20-RAG/03-WebSearch.ipynb` | `agents/market.py`, `agents/competition.py`에서 시장 범위·고객·대안을 출처와 함께 분석 |
| D — 투자 판단·보고서 내용 | `langgraph-v1/20-RAG/02-RelevanceCheck.ipynb`, `langgraph-v1/10-Agent/11-Multi-ReportAgent.ipynb` | `agents/evaluation.py`에 근거 검사·점수·보류 판단 구현. `agents/report.py`에 들어갈 본문 구성과 판단 근거를 E와 합의 |
| E — 그래프·PDF 통합 | `langgraph-v1/00-Basic/02-State.ipynb`, `langgraph-v1/00-Basic/03-Graph.ipynb`, `langgraph-v1/10-Agent/11-Multi-ReportAgent.ipynb` | `agents/state.py`, `app.py`에서 상태·분기·종료를 연결하고 `agents/report.py`에서 D의 내용을 PDF로 출력 |

**B·D·E는 `langgraph-v1/20-RAG/13-AgenticRAG.ipynb`를 함께 봅니다.**
이 예제의 검색 도구 호출, 검색 문서 평가, 질문 수정 흐름을 과제에 연결하는 것이 Agentic RAG 요건을 위한 핵심 완성 단계입니다.
`01-NaiveRAG`의 고정 검색·답변 흐름을 만든 뒤, `02-RelevanceCheck`의 검사와 `13-AgenticRAG`의 판단에 따른 도구 사용·재검색으로 확장합니다.
`03-WebSearch`는 외부 검색 연결 참고입니다. 모든 후보와 재검색으로 추가한 문서도 전체 200쪽 한도에 함께 집계합니다.

B의 오픈 임베딩 예제는 `langchain-v1/14-Retriever/04b-BGE-M3.ipynb`를 참고합니다. 반복 임베딩을 줄이는 캐시는 `langchain-v1/12-Embedding/02-CacheBackedEmbeddings.ipynb`에서 보되, 그 안의 모델도 팀이 선정한 오픈 임베딩으로 바꿉니다.

## 5명이 기다리지 않고 만드는 순서

1. 공통 상태, 함수 입출력, 평가 기준, 버전과 작은 예제 입력을 먼저 합의합니다.
2. A는 예제 PDF, B는 예제 문서 조각, C는 예제 검색 결과, D는 예제 분석 결과, E는 모의 노드를 써서 동시에 개발합니다.
3. 로직이 모두 끝나기 전에 한 번 연결합니다. 이후 A의 실제 문서 → B의 검색 → A·B·C의 분석 → D의 판단 → E의 출력으로 교체합니다.
4. 검색 근거가 부족하면 최대 1회 재검색하고, 계속 부족하면 보류하도록 구현·검증합니다. 이 횟수는 팀의 설계이며 강의 지정값은 아닙니다.
5. 첫 후보 보류 후 다른 후보 평가, 후보 소진 후 보고서 생성까지 확인합니다. 실행 순서가 있다고 개발까지 차례로 기다릴 필요는 없습니다.

## 그대로 가져오면 안 되는 부분

- 수업의 OpenAI 임베딩 예시는 과제에 그대로 사용하지 않습니다. **오픈 임베딩 후보**를 고르고 한국어·전문 용어·실행 환경·검색 품질로 검증합니다.
- 예제의 API 키, 문서 경로, 라이브러리 버전은 각자 환경에 맞춥니다. 원문 URL과 페이지가 최종 주장까지 연결되는지도 확인합니다.
- `11-Multi-ReportAgent`의 역할 분담·내용 합치기 흐름을 참고하되, 이미지 생성과 Word 출력은 그대로 따라 할 필수 항목이 아닙니다. 과제 출력은 PDF입니다.
- Self-RAG, Corrective RAG, Adaptive RAG, GraphRAG, 감독자 구조, 이미지 생성, Ragas는 이번 기본 구현 범위의 필수 항목이 아닙니다.
- 검색 평가는 고정 질문·정답 근거와 Hit Rate@K·MRR부터 확인할 수 있습니다. 라이브러리를 실행한 것만으로 평가를 마쳤다고 쓰지 않습니다.

## 제출 전 함께 확인

- [ ] 실제 공개 문서 총 200쪽 이하, 오픈 임베딩, 최소 1개 실제 RAG, 멀티에이전트와 조건에 따른 Agentic RAG 동작을 확인했다.
- [ ] 모의 결과와 실제 실행 결과를 구분하고, 근거·점수·보고서 인용을 각 담당자가 확인했다.
- [ ] 보고서는 5쪽 이하이며 첫 SUMMARY는 0.5쪽 이하, 끝 REFERENCE에는 실제 인용 자료만 넣었다.
- [ ] 각자 README 자기 파트를 작성하고, 다른 팀원이 README만으로 실행했다. 10분 발표에서 PM/PL 대신 실제 기여를 설명한다.
- [ ] DAY3 10:00 설계 제출, 15:00 개발 제출과 [전체 체크리스트](assignment-checklist.md)를 확인했다.
