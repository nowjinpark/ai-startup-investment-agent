# 제출 전 보완 검토

2026-10-13, 기존 v10 실행을 보존하고 Codex 지원으로 공개 자료와 이전 팀 기록을 추가 대조했다. 기업별 판단, 선정 자격, 팀 기여 설명을 보완한 결과다.

- [report.md](report.md): 최종 PDF의 기업 분석 본문. 기존 네 관점·원문 근거를 유지하고 시장·경쟁·팀·판단을 보완했다.
- [eligibility.md](eligibility.md): 공식 연혁·투자사·공시를 대조한 선정 근거와 날짜, 확인 한계. 로보콘은 투자 후보 편입 보류, 나머지는 조건부 검토다.
- [contributions.md](contributions.md): 기존 개인 담당과 재사용 범위, 기록으로 확인한 실제 활동. 새 개인 구현 실적을 추정하지 않았다.
- [market-context.md](market-context.md): 시장 배경 통계와 기업별 직접 시장을 구분한 범위·산정 방법.
- [source-inventory.json](source-inventory.json): 본문에서 사용한 원문 ID·URL·날짜·저장 위치. 추가 웹 자료의 확인 범위는 [additional-sources.json](additional-sources.json)에 있다.
- [coverage-map.json](coverage-map.json): 기존 20개 관점·15개 인용 ID와 공통으로 정리한 조건의 대응.
- [review-manifest.json](review-manifest.json): 원 실행 ID와 원문·검토본·관련 파일의 해시.

`../final/`의 State·보고서·평가·실행 수치는 변경하지 않았다. v10 자동 Judge의 `approved`는 그 원문에 대한 판정이다. 이 보완 문안을 같은 실행이 자동으로 생성·승인했다고 해석하지 않는다. 그래프 구조·실행 코드·원 자료 164쪽도 유지했다.

저장소 루트에서 다음 명령으로 보완 PDF를 다시 만든다. API 호출은 발생하지 않는다.

```bash
./.venv/bin/python reporting/agent_submission.py \
  --run-dir submission/final --review-dir submission/reviewed \
  --output submission/Agent_evaluation_report.pdf
```

보완 내용을 빼고 원 실행의 PDF를 재생성하려면 `--review-dir`을 생략하고 별도 출력 파일명을 사용한다. 원 실행과 검토본의 식별 정보가 다르면 생성기가 중단한다. 제출본 전체 형식·파일 대응은 `python scripts/check_submission.py`로 확인한다.
