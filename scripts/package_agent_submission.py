"""제출 ZIP을 만듭니다. 실행 결과는 보존하고 키·환경·캐시는 제외합니다."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BRANCH_URL = 'https://github.com/nowjinpark/ai-startup-investment-agent/tree/agent-orchestration'


def export_run(source, destination, *, include_raw=False):
    """공개 결과와 검증 기록만 복사합니다. checkpoint/응답 원문은 로컬에 남깁니다."""
    destination.mkdir(parents=True, exist_ok=True)
    manifest_path = destination / 'export-manifest.json'
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding='utf-8'))
        if previous['source_run'] != source.name:
            raise ValueError('서로 다른 실행을 같은 제출 폴더에 섞을 수 없습니다.')
    names = ('state.json', 'report.md', 'execution-summary.json', 'execution-segments.json',
             'run-config.json', 'trace.json', 'trace-verification.json', 'report-versions.json', 'events.jsonl',
             'llm_usage.json', 'cost.json', 'retrieval.json', 'graph.mmd')
    paths = [source / name for name in names]
    paths += sorted((source / 'raw').glob('evaluation-*.json'))
    if include_raw:
        paths += sorted((source / 'raw').rglob('*.json'))
    hashes = {}
    for path in paths:
        if not path.is_file():
            continue
        relative = path.relative_to(source)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        content = path.read_bytes()
        target.write_bytes(content)
        hashes[str(relative)] = hashlib.sha256(content).hexdigest()
    manifest_path.write_text(json.dumps({
        'source_run': source.name,
        'note': '실행 파일을 내용 변경 없이 복사했습니다. 원 실행 경로는 당시 기록이며 재실행 경로가 아닙니다.',
        'sha256': hashes,
    }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def package(destination):
    raw = subprocess.check_output(['git', 'ls-files', '-co', '--exclude-standard', '-z'], cwd=ROOT)
    files = sorted({ROOT / name.decode() for name in raw.split(b'\0') if name})
    files += sorted((ROOT / 'data/prepared').rglob('*'))
    files = [path for path in files if path.is_file() and not path.is_symlink()]
    for path in files:
        relative = path.relative_to(ROOT)
        if path.name.startswith('.env') and path.name != '.env.example':
            raise ValueError('환경 키 파일이 포함되어 있습니다: ' + str(relative))
        if any(part in {'.git', '.venv', '__pycache__', '.cache'} for part in relative.parts):
            raise ValueError('제외해야 할 내부 폴더입니다: ' + str(relative))
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise ValueError('기존 제출 ZIP을 덮어쓰지 않습니다.')
    with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('먼저_읽어주세요.txt',
            '울산 1반 | 김민정·김희윤·박종찬·박진원·이현우\n\n'
            '1. Agent_evaluation_report.pdf: 최종 평가 보고서\n'
            '2. GitHub_link.txt: 과제 브랜치 주소\n'
            '3. tracing-1.png부터 순서대로: 실제 LangSmith 화면\n'
            '   화면별 의미는 source/submission/trace-guide.md를 참고하세요.\n'
            '4. source/README.md: 설계, 실행 방법, 팀 역할\n'
            '5. source/docs/agent-rubric.md: 평가표 항목별 확인 위치\n\n'
            '재현할 때는 source 폴더에서 시작합니다. PDF 164쪽 준비 자료가 포함되어 있습니다.\n'
            'API 키는 포함하지 않았습니다. .env.example을 참고해 본인의 키를 설정하세요.\n'
            'submission/rework-regression은 실패 시 재처리·한도 종료를 확인한 이전 실행입니다.\n'
            '최종 결과와 구분해서 읽어주세요.\n')
        archive.writestr('GitHub_link.txt', BRANCH_URL + '\n')
        archive.write(ROOT / 'submission/Agent_evaluation_report.pdf', 'Agent_evaluation_report.pdf')
        for screenshot in sorted((ROOT / 'submission').glob('tracing-*.png')):
            archive.write(screenshot, screenshot.name)
        for path in files:
            archive.write(path, 'source/' + path.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(destination) as archive:
        if archive.testzip() is not None:
            raise ValueError('ZIP 파일 검사 실패')
    print(json.dumps({'zip': str(destination), 'bytes': destination.stat().st_size,
                      'source_files': len(files),
                      'sha256': hashlib.sha256(destination.read_bytes()).hexdigest()}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--final', type=Path, required=True)
    parser.add_argument('--resume', type=Path, required=True)
    parser.add_argument('--regression', type=Path, required=True)
    parser.add_argument('--zip', type=Path, required=True)
    args = parser.parse_args()
    export_run(args.final, ROOT / 'submission/final', include_raw=True)
    export_run(args.resume, ROOT / 'submission/resume-proof', include_raw=True)
    export_run(args.regression, ROOT / 'submission/rework-regression')
    (ROOT / 'submission/Agent_evaluation_report.pdf').write_bytes(
        (args.final / 'evaluation-report.pdf').read_bytes())
    package(args.zip)


if __name__ == '__main__':
    main()
