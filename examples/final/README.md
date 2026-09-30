# 최종 보고서와 재현 자료

실제 자동 실행을 Codex로 원문 대조·교정한 결과입니다. 팀의 독립 검토가 끝난 것으로 표시하지 않습니다.

- `investment-report.pdf`: 제출 보고서
- `records.json`, `run_summary.json`: API 없이 보고서를 재생성하는 입력
- `source_review.json`: 원문 대조 및 수정 전후·사유
- `supplemental_review.json`: 시장·경쟁 공식 자료 보완 내역
- `regrade_provenance.json`: 재채점 설정·입력 해시
- `retrieval_evaluation.json`: 소규모 검색 회귀 검사

공개 입력의 출처 본문은 인용한 부분만 보관합니다. 원문 해시는 최초 수집 자료의 값이며 발췌문 해시가 아닙니다. 164쪽 원문은 별도 준비 자료 ZIP에 있습니다.

```bash
./.venv/bin/python main.py report --records examples/final/records.json
```
