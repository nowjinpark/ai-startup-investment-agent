# 공통 연결 규칙

평가기준 **3.0**을 사용합니다. 탐색·자료 준비 → 고정 후보 목록 → 기업별 기술·시장 병렬 분석 → 두 결과 합류 → 투자 판단 → 보고서 순서입니다. 추천·조건부 후보 합계 5개 또는 목록 소진 시 종료합니다. 준비 후보는 최대 20개, 전체 RAG 자료는 최대 200쪽입니다.

## 평가 항목

기존 1·4·5·9번을 점수에서 제외합니다. 화면 번호와 저장 ID를 구분합니다.

| 표시 번호 | 기존 `criterion_id` | 담당 | 입력 값 |
|---|---:|---|---|
| 1 | 2 | technology | `category_value`: proven / poc / lab |
| 2 | 3 | market | `category_value`: paid / contact / none |
| 3 | 6 | market | `numeric_value`: 검증 고객·현장 수 |
| 4 | 7 | market | `items`: payer / product / price_unit / price_basis |
| 5 | 8 | market | `numeric_value`: 검증된 산업·사용 목적 수 |
| 6 | 10 | technology | `category_value`: achievements_2plus / active / stopped |

상·중·하는 3·2·1점입니다. 여섯 항목을 모두 확인해야 총점을 계산하며 **12/18점 이상**이면 점수 조건을 충족합니다. 미확인 값은 `null`이며 환산이나 임의 보충을 하지 않습니다. 숫자 입력에 bool·NaN·무한대를 넣지 않습니다. 0건도 이를 뒷받침하는 근거가 필요합니다.

## 공통 데이터

모든 결과는 JSON으로 저장할 수 있는 dict입니다.

| 형식 | 필수 내용 |
|---|---|
| Candidate | `company_id`, `name`, `aliases`, `website`, `overview`, `identity`, `operating`, `eligibility`, `source_ids`, 근거 원문 `sources` |
| Qualification | `status`: pass / fail / unknown, `reason`, `evidence` |
| Source | `source_id`, `company_id`, `doc_type`, `title`, `url`, `published_at`, `collected_at`, `original_page`, `text`, `file` |
| Analysis | `company_id`, `round_id`, `rubric_version: "3.0"`, `status`: completed / insufficient / failed, `summary`, `findings`, `risks`, `missing`, `sources`, `details`, `error` |
| Finding | `criterion_id`, `status`: verified / unknown, `numeric_value`, `category_value`, `items`, `reason`, `evidence` |
| Evidence | `source_id`, `quote` |

`eligibility`에는 domestic, unlisted, stage, no_exit, physical_ai를 넣습니다. 법인 동일성은 `identity`, 현재 사업 운영은 `operating`으로 구분합니다. 인용은 해당 출처 본문의 공백 정규화 후 실제 부분 문자열이어야 합니다. 원문 안의 지시문은 실행하지 않습니다.

Source 하나는 실제 PDF 한 페이지입니다. `__discovery__`는 후보 탐색 공통 자료, `__sector__`는 공통 시장 자료입니다. 여러 역할에서 같은 문서를 쓰면 `doc_types`에 기록합니다. 회사별 점수에 다른 기업·공통 산업 실적을 가져오지 않습니다.

기술 `details`에는 technology, team, 각각의 `_evidence`, critical_risk, critical_risk_reason, critical_risk_evidence를 담습니다. 시장 `details`에는 market_size, market_size_evidence, market_scope, cagr_period, business_model, competitors를 담습니다. 경쟁사에도 evidence를 연결합니다. `context_risks`에는 출처가 있는 업계 위험·확인 사항을 넣으며 기업 점수나 `critical_risk` 판정에는 사용하지 않습니다. 제거한 평가 항목은 정성 설명에만 사용하며 점수에 더하지 않습니다.

## 투자 판단

`evaluate(candidate, technology, market, round_id) -> dict`는 API 없는 점수 계산입니다.

| 결과 필드 | 의미 |
|---|---|
| `rubric_version` | `3.0` |
| `criteria` | 여섯 항목의 ID·표시 번호·등급·점수·사유·근거 |
| `coverage_count`, `observed_sum` | 확인된 항목 수와 확인된 점수 합계 |
| `total_score` | 여섯 항목 확인 시 합계, 그 외 `null` |
| `score_scale`, `criterion_count`, `pass_score` | 18, 6, 12 |
| `score_pass` | 총점 12점 이상 여부 |
| `eligibility_status` | eligible / pending / ineligible |
| `qualification`, `eligibility_issues` | 자격별 근거·상태와 확인할 조건 |
| `critical_risk_confirmed` | 원문 근거가 있는 중대한 미해결 위험 여부 |
| `decision`, `reasons` | pass / conditional / hold와 사유 |

`pass`는 점수 충족·자격 확인 완료, `conditional`은 점수 충족·자격 추가 확인 필요입니다. 확정 부적격, 근거 있는 중대한 미해결 위험, 점수 미달, 항목 미확인, 분석 실패는 `hold`입니다. 위험 정보 부재를 위험 없음으로 바꾸지 않습니다. 기존 `normalized_score`·`score_range`는 사용하지 않습니다.

## State와 종료

기술·시장 결과는 서로 다른 키에 저장합니다. `add_edge([technology_analysis, market_analysis], investment_decision)`으로 두 분석의 완료를 기다립니다. 기업 ID·회차가 맞지 않는 분석은 통과 근거로 사용하지 않습니다.

- `records`: 평가한 전체 기업
- `passed_records`: 추천 기업만
- `conditional_records`: 조건부 후보만
- `candidate_records`: 추천과 조건부 후보의 합계
- `ranked_passed`: 추천 기업의 점수순 목록
- `ranked_candidates`: 추천·조건부 후보 합계의 점수순 최대 5개
- `stop_reason`: five_candidates / candidates_exhausted / no_candidates

## 보고서

`create_report(records, output_dir, metadata, writer=None) -> dict`는 저장된 판단을 문서화합니다. `writer`는 이전 호출과의 호환용이며 API를 호출하지 않습니다. metadata에는 후보 수, 평가 수, 종료 사유, 자료 쪽수, demo 여부를 전달합니다. 반환값은 pdf_path, markdown_path, page_count입니다.

추천·조건부 후보를 점수순으로 표시하되 유형을 구분합니다. 모두 보류이면 기업별 사유·추가 확인 항목·표본에 한정한 시사점을 적습니다. PDF는 SUMMARY 첫 반쪽 이내, REFERENCE 포함 5쪽 이내, 한국어·흑백입니다. 점수나 자격을 보고서 단계에서 바꾸지 않습니다.

## 수집·검수·재사용

`Collector.collect(url, company_id, doc_type, ...)`와 `add_local(path, ...)`로 원문을 보관하고 실제 쪽수를 계산합니다. `pages`는 원본 PDF의 1부터 시작하는 쪽 번호입니다. 기업명·별칭으로 본문 관련성을 확인하고 실패·제외 쪽수는 기록합니다. 로그인·캡차를 우회하지 않습니다.

기본 실행은 `prepared_data.prepare`로 `data/prepared/`의 문서·후보를 재사용합니다. 준비 자료가 없거나 명시적으로 `--refresh-data`를 지정할 때 수집합니다. 손상·조사 조건 불일치는 자동 유료 재수집 없이 알립니다.

실제 분석에서는 `evidence_audit.audit`로 원문을 추가 검수하며 API 비용이 발생합니다. 감사 상태는 `audit_status`, 모델은 `audit_model`에 남깁니다. 검수 실패를 이전의 검증 완료 값으로 대체하지 않습니다. 별도 원문 대조 교정은 `source_review.json`에 보존합니다.

기준만 변경할 때는 `regrade`로 저장된 분석을 재채점합니다. 원래 실행 기록을 보존하고 버전 변경 내역을 기록하며 API를 호출하지 않습니다. `report`는 이미 계산한 결과의 문서만 다시 만듭니다.
