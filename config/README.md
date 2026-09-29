# 회사·도메인 교체

`project.json`은 실제 분석 구현을 위한 설정 계약입니다. 회사와 도메인은 아직 미선정이며,
현재 `--mode demo`는 이 파일 대신 `fixtures/demo_candidates.json`을 사용합니다.
`--mode live`는 명시적으로 미구현 오류를 냅니다. 설정 변경만으로 실제 RAG가 완성되지는 않습니다.

선정 후 다음 값을 채우고 담당 E가 실제 파이프라인에 연결합니다.

```json
{
  "domain": "Energy",
  "as_of_date": "YYYY-MM-DD",
  "candidates": [
    {"id": "company-a", "name": "선정 기업 A", "domain": "Energy", "eligibility": "unverified"},
    {"id": "company-b", "name": "다음 후보 B", "domain": "Energy", "eligibility": "unverified"}
  ]
}
```

- 허용 도메인: Agriculture (AgTech), Energy, Healthcare AI, Physical AI / Robotics, Semiconductor.
- 기업 자격은 근거를 조사한 뒤에만 eligible로 변경합니다.
- 자료는 `data/sources.json`에서 candidate_id로 연결합니다.
- 변경한 회사의 자료만 검색하도록 candidate_id 필터를 적용합니다.
- 평가 항목별 0~5점 정의도 도메인에 맞춰 팀이 합의합니다.
- `evaluation.json`의 가중치와 임계값은 데모 평가 코드에서도 읽습니다.
- 기준 변경 시 전 후보에 동일하게 적용하고 테스트·설계 문서를 함께 갱신합니다.
