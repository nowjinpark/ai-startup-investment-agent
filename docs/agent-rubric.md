# 과제 평가기준과 확인 근거

[Multi-Agent Orchestration 실습 안내](https://actually-war-1ea.notion.site/Multi-Agent-Orchestration-3d57f4c866938020a992fcc97e942ee6)의 평가표는 총 **100점**입니다. 배점은 공식 항목이며 자체 채점이나 만점 보장이 아닙니다. 구현 의도와 실제 검증을 구분합니다.

## 공식 평가표 대응

| 평가항목 | 배점 | 구현·설명 위치 | 제출에 필요한 실제 증거 | 상태 |
|---|---:|---|---|---|
| 패턴 적용 정합성 | 20 | README Overview·Agents·Architecture, orchestration/ | 코드 구조도와 Orchestrator의 계획·Worker 실행·결과 취합 trace | 코드 구조도와 실제 Plan → Send → 취합·평가 흐름 확인 |
| 동적 동작 실증 | 20 | Plan·Send·조건부 분기 | 입력별 계획·작업/경로 차이, 품질 미달 후 재처리 trace | 5개 기업/1개 기업의 계획 차이, 선택 재조사, v3 재작성·한도 종료 확인 |
| State Schema 설계 | 20 | orchestration/state.py, README State Schema | 일곱 설계 기준과 병합·상관·재개·종료 검사 | 일곱 기준·단위 검사·실제 중단 재개 확인 |
| 품질 평가 노드 | 15 | Evaluator와 Gate | 근거성·중립성·편향·충실성 판정, 피드백과 개선 전후 | 최종 네 기준 승인, v3 재작성·선택 재조사·한도 종료를 별도로 확인 |
| 코드 구조 및 모듈 분리 | 5 | app.py, orchestration/, prompts/, agents/·rag.py | 실행·상태·역할·지시문·검색·보고서 책임 구분 | 실행·상태·역할·지시문·검색·출력 책임을 파일별로 대조 |
| 실행 결과 재현성 | 10 | README Usage·Tech Stack, 실행 기록 | 환경·모델·자료·입력·명령·재개, 실제 LangSmith 이미지 | 설치 버전·자료/코드 해시·실제 호출·별도 프로세스 재개 보존 |
| Output - 보고서 | 10 | [평가 PDF](../submission/Agent_evaluation_report.pdf)·[기업 분석](../submission/final/report.md) | 네 관점, 장단점·출처·미확인, 동적 실행·평가, 최대 10장 | 6쪽 평가 PDF와 기업별 결과를 분리해 보존 |
| 합계 | 100 | | | 실제 채점은 평가자가 수행 |

## README 샘플 대조

샘플은 정답이 아니라 조별 설계 근거에 맞게 바꾸는 참고 형식입니다. 제목만 넣는 것으로 완료하지 않고 실제 내용과 실행을 확인합니다.

| 샘플 항목 | 현재 내용 | 최종 확인 |
|---|---|---|
| Subject | 기존 Physical AI 투자 분석 확장 | 새 주제로 바뀌지 않았는지 |
| Overview Objective | 근거와 한계를 비교할 보고서 | 입력·출력·범위가 구체적인지 |
| Overview Pattern 선정 이유 | 독립 조사의 계획·병렬 처리 | Supervisor 대안과 선택 이유를 설명하는지 |
| Overview 동적 처리 | Plan·Send·재조사/재작성 | 실제 입력별 차이를 보여주는지 |
| Selected Technologies | SW·HW 구성 요소가 다른 기업과 이유 | 근거 없는 기술·투자 우위 주장이 없는지 |
| Features | PDF·네 관점·확증편향 방지·평가 | 구현이 설명과 일치하는지 |
| Tech Stack | LangGraph·Generator/Judge·FAISS·BGE-M3 | 실제 모델 ID·버전·Hit Rate@K/MRR 실측 기록 |
| Agents | 계획·조사·작성·평가 역할과 코드 Gate | 입력·출력·책임이 명확한지 |
| State Schema | 일곱 기준과 필드·병합 규칙 | 아래 일곱 항목의 실제 증거 |
| Architecture | 코드 구조도 이미지와 Mermaid | 구조도 시각 확인 완료. graph.mmd·실제 LangSmith 경로는 따로 확인 |
| Directory Structure | data·agents·prompts·outputs·app.py·README | 최종 파일·경로와 일치 |
| Usage | 설치·환경·live·resume·report | 명령과 결과 재현 확인 |
| Contributors | 동일 다섯 팀원의 개인 역할, AI 지원 범위 | PM/PL만 쓰지 않고 새 기여는 사실만 추가 |
| References | 과제·PDF·수업 코드·원문 | 자료 출처와 구현 참고 구분 |

## State 일곱 기준

| 기준 | 필드·정책 | 확인할 검사 | 상태 |
|---|---|---|---|
| 제어 vs 페이로드 분리 | results/report와 revision/route/status | Worker 부분 반환과 전달 범위 | Worker는 결과만 반환하고 다음 경로는 Gate가 결정 |
| 관측성 위치 | trace_id/node_status/last_error·외부 로그 | 실패 작업의 입력과 회차 추적 | events의 노드·결정·이유·상관 ID 검사, LangSmith 대조 |
| 지속성 비용 | 원문 파일, 출처 ID·요약 | 원문 보존과 State 크기 | 원문 전체를 State에 넣지 않는 검사 통과, 원문·검수 출력 별도 보존 |
| 상관 | trace_id/task_id/revision | 기업·작업·회차 정합성 | 다른 기업 결과 거절 검사와 선택 재조사 회차 확인 |
| 재개·복구 | checkpoint·완료 결과·기존 비용 | 프로세스 중단 후 재개·중복 방지 | SQLite 재개 검사 및 실제 계획 후 중단·새 프로세스 승인 |
| 동시 처리 | merge_results reducer | 도착 순서 독립, 최신 회차, 충돌 거절 | 순서·반복 병합·동일 회차 충돌 검사 통과, 실제 trace 시간의 최대 동시 실행 3개 |
| 종료 보장 | max_revisions·step_count·fallback | 한도·오류·품질 미달 종료 | v3 수정 한도 fallback 및 Worker 실패·계획 오류·비용 한도 검사 |

## 품질 평가

| 기준 | 확인할 질문 | 미달 시 처리 |
|---|---|---|
| 근거성 | 주장과 원문이 같은 회사·시점·실적을 말하는가? | 해당 작업 재조사 또는 근거에 맞는 재작성 |
| 중립성 | 과장 없이 장점·위험·한계를 설명하는가? | 자료가 충분하면 보고서 재작성 |
| 편향 | 유리한 자료만 골랐거나 미확인을 유리하게 해석했는가? | 누락 근거 재조사 또는 해석 재작성 |
| 충실성 | 요청한 기업·네 관점·비교·한계가 포함됐는가? | 누락 원인에 따라 재조사/재작성 |

코드 필수 검사와 품질 판정이 충돌하면 코드 검사가 우선입니다. 반복 한도 뒤에는 미달 사유가 있는 결과를 저장합니다. API 실패·자료 부족·품질 미달·정상 통과를 같은 성공 상태로 묶지 않습니다.

## 확인된 증빙

- **원문 범위:** 교재 171쪽 추출 텍스트 전체와 주요 13쪽 이미지, 노션의 접힌 State·README·평가표, 연결된 RAG 과제 페이지를 확인했습니다. [과제 설계 문서](agent-assignment.md#원문-확인-범위)에 범위를 적었습니다.
- **최종 실행:** [요약](../submission/final/execution-summary.json), [계획·판정·분기](../submission/final/events.jsonl), [호출 모델·토큰](../submission/final/llm_usage.json), [보고서](../submission/final/report.md)를 같은 실행으로 연결합니다.
- **재개:** [실행 구간](../submission/resume-proof/execution-segments.json)에 같은 trace_id의 계획 후 중단과 다른 프로세스의 승인 결과를 보관했습니다. 대기 시간을 제외한 구간 시간·누적 비용을 구분합니다.
- **검색:** [15문항 결과](../submission/retrieval-evaluation.json)의 Hit Rate@4 1.0, MRR@4 0.9555556(표시 0.956). 기존 질문·같은 코퍼스의 재현 결과이며 독립적인 품질 평가로 확대하지 않습니다.
- **환경:** [환경 정보](../submission/environment.json), [전체 설치 버전](../submission/environment-lock.txt), 실행별 `run-config.json`의 자료·구현 해시를 보관했습니다.
- **테스트:** [347 passed, 1 skipped, 4 subtests passed](../submission/test-results.txt), 6.05초. 생략은 선택형 네트워크 수집 검사, 경고 3개는 FAISS SWIG deprecation입니다.
- **구조와 추적:** [코드 구조도](../submission/architecture.png)와 [실제 LangSmith 캡처·run ID 안내](../submission/trace-guide.md)를 구분했습니다.
- **v3 실패 회귀 검증:** [별도 안내](../submission/rework-regression/README.md)에 rewrite → research → fallback과 실제 보고서 세 판·평가 세 건을 보관했습니다. 오류가 있는 과거 결과이며 최종 성공이나 투자 판단의 근거로 쓰지 않습니다.

`gpt-4.1-mini`와 `gpt-4.1`은 요청에 사용한 모델 별칭입니다. 날짜별 응답 스냅샷으로 고정됐다고 주장하지 않습니다. temperature 0이어도 새 실행은 달라질 수 있습니다. 보존한 입력·환경·출력으로 당시 결과를 확인하고 보고서를 다시 만드는 재현 범위를 명시했습니다.

| 증빙 | 저장 위치와 해석 |
|---|---|
| 실행 식별·입력·자료 기준일 | 각 실행의 `run-config.json`, `execution-summary.json` |
| 동적 계획 | `state.json`의 계획·이유·관점·질의·완료 조건, `events.jsonl`의 실제 분기 |
| 평가·개선 전후 | `report-versions.json`의 실제 작성·평가 출력과 `raw/`의 검수·선택 기록 |
| 운영 | `llm_usage.json`의 호출·토큰, 실행 요약의 시간, `cost.json`의 추정 비용. 실제 청구액과 구분 |
| LangSmith | 실행별 `trace.json`·`trace-verification.json`과 실제 캡처 5장, 화면별 확인 내용은 추적 안내에 명시 |
| 과제 결과 | [평가 보고서](../submission/Agent_evaluation_report.pdf), [기업별 분석](../submission/final/report.md) |
| 공개 코드 | [agent-orchestration 브랜치](https://github.com/nowjinpark/ai-startup-investment-agent/tree/agent-orchestration) |

## 해석할 때 주의할 범위

테스트 통과, LLM 품질 승인, 교수님의 과제 점수, 실제 투자 적합성은 서로 다른 판단입니다. 이번 대응표는 **100점 배점 전체의 구현·증빙 위치**를 제시하며 자체 만점 판정이 아닙니다. 특히 최종 분석에도 원문 자체의 오류·홍보 편향·노후화와 최신 기업 자격·유료 계약·독립 성능의 미확인 사항이 남습니다.

개인 역할은 기존 다섯 팀원의 실제 분담을 이어 표시하고, 새 구현·문서·실행 검증에 Codex를 사용했다고 명시했습니다. 확인하지 않은 새 개인 기여를 만들어 넣지 않았습니다. 저장소와 제출 파일의 준비는 수업 채널에 실제로 제출했다는 뜻이 아닙니다.
