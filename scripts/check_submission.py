"""제출 파일 누락과 실행 기록의 서로 다른 값을 마지막에 확인합니다."""
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    from pypdf import PdfReader
    from PIL import Image
    folder = ROOT / 'submission/final'
    state = read(folder / 'state.json')
    summary = read(folder / 'execution-summary.json')
    assert summary['status'] == state['status'] == 'approved', '최종 실행이 통과 상태가 아닙니다.'
    tasks = {task['task_id'] for task in state['plan']}
    assert tasks == set(state['results']), '계획과 결과 작업 ID가 다릅니다.'
    criteria = state['evaluation']['criteria']
    assert {item['criterion'] for item in criteria} == {'groundedness', 'neutrality', 'bias', 'coverage'}
    assert len(criteria) == 4 and all(item['passed'] for item in criteria)
    assert not state['evaluation'].get('deterministic_errors')
    assert state['report'] == (folder / 'report.md').read_text(encoding='utf-8')
    assert state['report'].startswith('## SUMMARY')
    body, _, references = state['report'].partition('## REFERENCE')
    assert not re.search(r'^## ', references, re.MULTILINE)
    pattern = r'\[(S-[a-z0-9]+)\]'
    assert set(re.findall(pattern, body)) == set(re.findall(pattern, references))
    trace = read(folder / 'trace-verification.json')
    assert trace['planned_tasks'] == len(tasks) and trace['status'] == 'approved'
    assert all(group['root_finished'] and not group['root_error'] for group in trace['traces'])
    for exported in ('final', 'resume-proof', 'rework-regression'):
        base = ROOT / 'submission' / exported
        manifest = read(base / 'export-manifest.json')
        actual = {str(path.relative_to(base)) for path in base.rglob('*') if path.is_file()}
        assert actual - {'README.md', 'export-manifest.json'} == set(manifest['sha256']), exported
        for name, digest in manifest['sha256'].items():
            assert hashlib.sha256((base / name).read_bytes()).hexdigest() == digest, name
    resume = read(ROOT / 'submission/resume-proof/execution-segments.json')
    assert len(resume) == 2 and resume[0]['status'] == 'paused' and resume[1]['resumed']
    assert resume[0]['trace_id'] == resume[1]['trace_id']
    assert resume[1]['status'] == 'approved'
    final_config = read(folder / 'run-config.json')
    resume_config = read(ROOT / 'submission/resume-proof/run-config.json')
    assert final_config['implementation_hashes'] == resume_config['implementation_hashes']
    for name, digest in final_config['implementation_hashes'].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest, name
    for name, digest in final_config['data_hashes'].items():
        assert hashlib.sha256((ROOT / 'data/prepared' / name).read_bytes()).hexdigest() == digest, name
    resume_trace = read(ROOT / 'submission/resume-proof/trace-verification.json')['traces']
    assert len(resume_trace) == 2
    assert resume_trace[0]['node_counts'].get('planner') == 1
    assert resume_trace[1]['node_counts'].get('planner', 0) == 0
    assert all(group['root_finished'] and not group['root_error'] for group in resume_trace)
    pdf = PdfReader(ROOT / 'submission/Agent_evaluation_report.pdf')
    assert 1 <= len(pdf.pages) <= 10
    assert 'SUMMARY' in pdf.pages[0].extract_text()
    assert 'REFERENCE' in ''.join(page.extract_text() for page in pdf.pages)
    for number in range(1, 6):
        with Image.open(ROOT / f'submission/tracing-{number}.png') as picture:
            picture.verify()
    for name in ('README.md', 'docs/agent-assignment.md', 'docs/agent-rubric.md', 'submission/trace-guide.md'):
        assert 'TBD' not in (ROOT / name).read_text(encoding='utf-8'), name
    print(json.dumps({'status': 'passed', 'companies': len(state['companies']),
                      'tasks': len(tasks), 'quality_criteria': len(criteria),
                      'pdf_pages': len(pdf.pages), 'screenshots': 5,
                      'note': '형식·연결·파일 무결성 검사이며 사람의 내용 검토와 실제 채점 결과를 대신하지 않습니다.'},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
