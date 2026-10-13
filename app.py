"""AI Agent 과제 실행: python app.py live / resume / report."""
import argparse
import hashlib
import json
import os
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_COMPANIES = '로보아르테,로보콘,리옵스,비욘드허니컴,엔닷라이트'
DEFAULT_REQUEST = ('기존 RAG의 조건부 검토 후보를 기술 성숙도, 시장성, 이해관계자, 도메인 적용성으로 '
                   '다시 검토해 주세요. 기업별 강점·리스크·추가 확인사항을 근거와 함께 정리하고, '
                   '자료로 입증하지 못한 우열이나 투자 확정 추천은 하지 마세요. '
                   '작업은 기업과 관점의 독립성에 맞춰 나누거나 묶어 주세요.')


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def load_prepared(folder):
    """자료 손상이나 누락을 유료 재수집으로 조용히 대체하지 않습니다."""
    from prepared_data import _validate
    manifest = read_json(folder / 'manifest.json')
    if not manifest.get('complete') or manifest.get('demo'):
        raise ValueError('실제 준비 자료가 필요합니다.')
    for filename in ('corpus/sources.json', 'candidates.json'):
        actual = hashlib.sha256((folder / filename).read_bytes()).hexdigest()
        if actual != manifest['hashes'][filename]:
            raise ValueError('자료 해시 불일치: ' + filename)
    sources, candidates = _validate(folder)
    if len(sources) != manifest['page_count'] or len(candidates) != manifest['candidate_count']:
        raise ValueError('자료 개수가 manifest와 다릅니다.')
    return manifest, sources, candidates


def compact_company(company):
    # 후보 탐색 결과에서 원문·긴 인용을 제외한 실행 입력만 공유합니다.
    return {key: company.get(key, '') for key in ('company_id', 'name', 'overview', 'website')} | {
        'eligibility': {key: value.get('status', 'unknown')
                        for key, value in company.get('eligibility', {}).items() if isinstance(value, dict)}}


def implementation_hashes():
    files = [ROOT / name for name in ('app.py', 'common.py', 'rag.py', 'requirements.txt', 'config/settings.json')]
    files += sorted((ROOT / 'orchestration').glob('*.py'))
    files += sorted((ROOT / 'prompts/orchestration').glob('*.txt'))
    return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}


def restore_runtime_history(runtime, folder):
    """재개 전 비용·성공·실패 이력을 복원하고 호출 번호를 이어갑니다."""
    old_cost = read_json(folder / 'cost.json') if (folder / 'cost.json').exists() else {}
    runtime.spent_usd = old_cost.get('estimated_spent_usd', 0) + old_cost.get('reserved_usd', 0)
    runtime.carried_cost_from = str(folder / 'cost.json')
    runtime.metrics = read_json(folder / 'llm_usage.json') if (folder / 'llm_usage.json').exists() else []
    runtime.failures = read_json(folder / 'llm_errors.json') if (folder / 'llm_errors.json').exists() else []
    completed_ids = [int(path.name.split('-')[0]) for path in (folder / 'responses').glob('*.json')]
    failed_ids = [int(error['call_id']) for error in runtime.failures]
    runtime._call_id = max([0, *completed_ids, *failed_ids])


def execute(args):
    from dotenv import load_dotenv
    load_dotenv(args.env_file or ROOT / '.env', override=False)
    os.environ['LANGSMITH_PROJECT'] = 'skala-physical-ai-orchestration'
    os.environ['LANGSMITH_TRACING'] = 'false' if args.no_trace else 'true'
    if not os.getenv('OPENAI_API_KEY'):
        raise ValueError('.env 또는 --env-file에 OPENAI_API_KEY가 필요합니다.')
    if not args.no_trace and not os.getenv('LANGSMITH_API_KEY'):
        raise ValueError('제출용 실행은 LANGSMITH_API_KEY가 필요합니다. 로컬 확인만 하려면 --no-trace를 사용하세요.')
    from common import Runtime
    from rag import Corpus
    from orchestration.graph import build_graph, EventLog
    from orchestration.service import LiveService
    from langgraph.checkpoint.sqlite import SqliteSaver

    folder = args.output.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    resume = args.command == 'resume'
    if not resume and (folder / 'run-config.json').exists():
        raise ValueError('기존 실행을 덮어쓰지 않습니다. 다른 --output 또는 resume을 사용하세요.')
    manifest, sources, candidates = load_prepared(args.data.resolve())
    config = read_json(ROOT / 'config/settings.json') | {'max_cost_usd': args.max_cost_usd}
    runtime = Runtime(config, folder)
    if resume:
        saved = read_json(folder / 'run-config.json')
        if saved['data_hashes'] != manifest['hashes']:
            raise ValueError('중단한 실행과 준비 자료가 다릅니다.')
        if saved.get('implementation_hashes') != implementation_hashes():
            raise ValueError('중단 후 실행 코드가 바뀌었습니다. 원래 코드를 복원하거나 새 실행 폴더를 사용하세요.')
        if args.max_cost_usd != saved['max_cost_usd']:
            raise ValueError('resume의 비용 한도는 원래 실행과 같아야 합니다.')
        restore_runtime_history(runtime, folder)
        initial = None
    else:
        names = [name.strip() for name in args.companies.split(',') if name.strip()]
        by_name = {company['name']: company for company in candidates}
        if not 1 <= len(names) <= 5 or len(set(names)) != len(names) or any(name not in by_name for name in names):
            raise ValueError('준비 후보 중 서로 다른 기업 1~5개를 선택하세요.')
        initial = {'request': args.request, 'companies': [compact_company(by_name[name]) for name in names],
                   'trace_id': str(uuid.uuid4()), 'revision': 0, 'max_revisions': args.max_revisions,
                   'step_count': 0, 'node_status': {}, 'last_error': '', 'feedback': '',
                   'results': {}, 'plan': [], 'pending_task_ids': [], 'report': '', 'status': 'running'}
        saved = {'trace_id': initial['trace_id'], 'request': args.request, 'companies': names,
                 'data_hashes': manifest['hashes'], 'max_cost_usd': args.max_cost_usd,
                 'max_revisions': args.max_revisions, 'pattern': 'Orchestrator-Workers',
                 'implementation_hashes': implementation_hashes(),
                 'corpus_pages': len(sources), 'source_run': manifest['source_run']}
        save_json(folder / 'run-config.json', saved)
    print(f'실제 자료 {len(sources)}쪽 / 대상 {len(saved["companies"])}개 기업 / 원문 재수집 없음', flush=True)
    start = time.perf_counter()
    corpus = Corpus(sources, config, ROOT / '.cache')
    service = LiveService(runtime, corpus, candidates, folder)
    event_log = EventLog(folder)
    trace_run_id = str(uuid.uuid4())
    execution_config = {'configurable': {'thread_id': saved['trace_id']},
                        'max_concurrency': 3, 'recursion_limit': 60,
                        'run_id': uuid.UUID(trace_run_id),
                        'metadata': {'trace_id': saved['trace_id'], 'pattern': 'Orchestrator-Workers',
                                     'company_count': len(saved['companies']), 'resumed': resume},
                        'tags': ['skala', 'agent-assignment', 'live']}
    with SqliteSaver.from_conn_string(str(folder / 'checkpoints.sqlite')) as checkpointer:
        graph = build_graph(service, event_log, checkpointer,
                            interrupt_after=['planner'] if args.pause_after_plan else None)
        (folder / 'graph.mmd').write_text(graph.get_graph().draw_mermaid(), encoding='utf-8')
        if resume and not graph.get_state(execution_config).next:
            raise ValueError('이미 종료된 실행입니다. 저장 보고서는 report 명령으로 다시 만드세요.')
        for value in graph.stream(initial, execution_config, stream_mode='values'):
            save_json(folder / 'state.json', value)
        snapshot = graph.get_state(execution_config)
        state = dict(snapshot.values)
        pending = bool(snapshot.next)
    (folder / 'report.md').write_text(state.get('report', ''), encoding='utf-8')
    previous_retrieval = read_json(folder / 'retrieval.json') if resume and (folder / 'retrieval.json').exists() else []
    save_json(folder / 'retrieval.json', previous_retrieval + corpus.history)
    segments = read_json(folder / 'execution-segments.json') if (folder / 'execution-segments.json').exists() else []
    segment_seconds = round(time.perf_counter() - start, 3)
    summary = {'trace_id': saved['trace_id'], 'run_id': trace_run_id, 'status': 'paused' if pending else state['status'],
               'elapsed_seconds': round(segment_seconds + sum(s['segment_seconds'] for s in segments), 3),
               'segment_seconds': segment_seconds, 'company_count': len(saved['companies']),
               'task_count': len(state.get('plan', [])), 'revision': state.get('revision', 0),
               'step_count': state.get('step_count', 0), 'corpus_pages': len(sources),
               'result_count': len(state.get('results', {})), 'llm_calls': len(runtime.metrics),
               'estimated_cost_usd': round(runtime.spent_usd, 6), 'resumed': resume}
    save_json(folder / 'execution-summary.json', summary)
    trace = {'trace_id': saved['trace_id'], 'run_id': trace_run_id,
             'project': os.environ['LANGSMITH_PROJECT'], 'enabled': not args.no_trace, 'verified': False}
    if not args.no_trace:
        try:
            from langchain_core.tracers.langchain import wait_for_all_tracers
            from langsmith import Client
            wait_for_all_tracers()
            client = Client()
            run = client.read_run(trace_run_id)
            trace.update(url=client.get_run_url(run=run), verified=True)
        except Exception as error:
            trace['error'] = type(error).__name__
    save_json(folder / 'trace.json', trace)
    segments.append({**summary, 'trace': trace})
    save_json(folder / 'execution-segments.json', segments)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if pending:
        print('계획 뒤에 일시 중단했습니다. 같은 --output의 resume으로 이어갈 수 있습니다.')
    else:
        from reporting.agent_submission import build_report
        build_report(folder, folder / 'evaluation-report.pdf', repo_root=ROOT)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['live', 'resume', 'report'])
    parser.add_argument('--output', type=Path, default=ROOT / 'outputs/agent-final')
    parser.add_argument('--data', type=Path, default=ROOT / 'data/prepared')
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--companies', default=DEFAULT_COMPANIES)
    parser.add_argument('--request', default=DEFAULT_REQUEST)
    parser.add_argument('--max-cost-usd', type=float, default=3.0)
    parser.add_argument('--max-revisions', type=int, choices=range(0, 4), default=2)
    parser.add_argument('--pause-after-plan', action='store_true')
    parser.add_argument('--no-trace', action='store_true')
    args = parser.parse_args()
    if not 0 < args.max_cost_usd <= 10:
        parser.error('--max-cost-usd는 0 초과 10 이하여야 합니다.')
    if args.command == 'report':
        from reporting.agent_submission import build_report
        build_report(args.output, args.output / 'evaluation-report.pdf', repo_root=ROOT)
    else:
        execute(args)


if __name__ == '__main__':
    main()
