import argparse
import json
from datetime import datetime
from pathlib import Path

from common import ROOT, Runtime, save_json, settings
from prepared_data import DEFAULT_REQUEST, prepare


def main():
    parser = argparse.ArgumentParser(description='국내 Physical AI 스타트업 투자 분석')
    parser.add_argument('mode', choices=['demo', 'live', 'report', 'regrade'])
    parser.add_argument('--output', type=Path)
    parser.add_argument('--request', default=DEFAULT_REQUEST)
    parser.add_argument('--max-candidates', type=int, default=20)
    parser.add_argument('--records', type=Path)
    parser.add_argument('--source-run', type=Path, help='재채점할 기존 실제 실행 폴더입니다.')
    parser.add_argument('--all-hold', action='store_true')
    parser.add_argument('--max-cost-usd', type=float, default=2.0)
    parser.add_argument('--resume-from', type=Path, help='자료 수집이 끝난 실행 폴더에서 분석을 이어갑니다.')
    parser.add_argument('--reuse-corpus', type=Path, help='저장된 원문을 재사용하면서 후보 추출부터 다시 수행합니다.')
    parser.add_argument('--recheck-eligibility', action='store_true', help='재개 시 저장 자료로 기업 자격을 다시 확인합니다.')
    parser.add_argument('--refresh-data', action='store_true', help='저장 자료 대신 문서·후보를 새로 수집합니다.')
    args = parser.parse_args()
    if args.refresh_data and (args.mode != 'live' or args.resume_from or args.reuse_corpus):
        parser.error('--refresh-data는 live 기본 실행에서만 사용합니다.')
    if not 1 <= args.max_candidates <= 20:
        parser.error('--max-candidates는 1~20입니다.')
    if not 0 < args.max_cost_usd <= 20:
        parser.error('--max-cost-usd는 0 초과 20 이하입니다.')
    if args.resume_from and args.reuse_corpus:
        parser.error('--resume-from과 --reuse-corpus는 함께 사용할 수 없습니다.')
    if args.recheck_eligibility and not args.resume_from:
        parser.error('--recheck-eligibility는 --resume-from과 함께 사용합니다.')
    output = (args.output or ROOT / 'output' / f'{args.mode}-{datetime.now():%Y%m%d-%H%M%S}').resolve()
    output.mkdir(parents=True, exist_ok=True)
    if args.mode == 'live' and ((output / 'cost.json').exists() or (args.refresh_data and any(output.iterdir()))):
        parser.error('기존 실행의 결과 보존을 위해 새 --output 폴더를 지정하세요. 분석 재개는 --resume-from으로 지정합니다.')
    config = settings()
    config['max_candidates'] = args.max_candidates
    config['max_cost_usd'] = args.max_cost_usd
    config['refresh_data'] = args.refresh_data
    if args.mode == 'regrade':
        if not args.source_run:
            parser.error('regrade에는 --source-run 폴더가 필요합니다.')
        from regrade import regrade_run
        result = regrade_run(args.source_run, output)
        save_json(output / 'settings.json', config)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    save_json(output / 'settings.json', config)
    if args.mode == 'report':
        if not args.records:
            parser.error('report에는 --records 경로가 필요합니다.')
        from agents.report import create_report
        records = json.loads(args.records.read_text(encoding='utf-8'))
        summary_path = args.records.parent / 'run_summary.json'
        metadata = json.loads(summary_path.read_text(encoding='utf-8')) if summary_path.exists() else {'stop_reason': 'candidates_exhausted', 'demo': False}
        result = create_report(records, output, metadata)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    from workflow import build_graph
    if args.mode == 'demo':
        from demo import DemoRuntime
        runtime = DemoRuntime(config, output, all_hold=args.all_hold)
    else:
        runtime = Runtime(config, output)
        if not args.resume_from and not args.reuse_corpus:
            runtime.prepare = lambda request: prepare(runtime, request)
        if args.resume_from or args.reuse_corpus:
            import shutil
            from rag import Corpus
            previous = (args.resume_from or args.reuse_corpus).resolve()
            previous_cost = previous / 'cost.json'
            if previous_cost.exists():
                cost = json.loads(previous_cost.read_text(encoding='utf-8'))
                runtime.spent_usd = float(cost['estimated_spent_usd']) + float(cost.get('reserved_usd', 0))
                runtime.carried_cost_from = str(previous)
                if runtime.spent_usd >= runtime.cost_limit:
                    parser.error('이전 실행이 API 비용 한도를 소진했습니다. API 호출 없이 저장 결과를 확인하세요.')
                runtime._budget_file()
            shutil.copytree(previous / 'corpus', output / 'corpus')
            if args.resume_from:
                candidates = json.loads((previous / 'candidates.json').read_text(encoding='utf-8'))[:config['max_candidates']]
                sources = json.loads((output / 'corpus/sources.json').read_text(encoding='utf-8'))
                runtime.corpus = Corpus(sources, config, ROOT / '.cache')
                for filename in ['candidates.json', 'excluded_candidates.json', 'unresolved_candidates.json', 'discovery_diagnostics.json']:
                    if (previous / filename).exists():
                        shutil.copy2(previous / filename, output / filename)
                save_json(output / 'candidates.json', candidates)
                def resume_prepared(request):
                    current = candidates
                    excluded = json.loads((previous / 'excluded_candidates.json').read_text()) if (previous / 'excluded_candidates.json').exists() else []
                    if args.recheck_eligibility:
                        from agents.discovery import requalify
                        current, newly_excluded = requalify(runtime, candidates)
                        excluded += newly_excluded
                        save_json(output / 'candidates.json', current)
                        save_json(output / 'excluded_candidates.json', excluded)
                    return {'candidate_list': current, 'doc_pages': len(sources), 'page_cap': 200,
                    'prepared': {'corpus': str(output / 'corpus'), 'resumed_from': str(previous),
                        'excluded': excluded,
                        'unresolved': json.loads((previous / 'unresolved_candidates.json').read_text()) if (previous / 'unresolved_candidates.json').exists() else []}}
                runtime.prepare = resume_prepared
                if not args.recheck_eligibility:
                    runtime.resume_dir = previous
    graph = build_graph(runtime)
    (output / 'graph.mmd').write_text(graph.get_graph().draw_mermaid(), encoding='utf-8')
    state = {'request': args.request}
    for event in graph.stream(state, config={'recursion_limit': 5 * config['max_candidates'] + 10}, stream_mode='updates'):
        for node, update in event.items():
            state.update(update)
            save_json(output / 'state.json', state)
            print(f'완료: {node}', flush=True)
    save_json(output / 'state.json', state)
    if state.get('report_error'):
        raise RuntimeError('분석 기록은 저장되었지만 PDF 생성 실패: ' + state['report_error'])
    print(f"평가 {len(state['records'])}개 / 추천 {len(state['passed_records'])}개 / 조건부 {len(state.get('conditional_records', []))}개 / 자료 {state['doc_pages']}쪽")
    print(state['report']['pdf_path'])


if __name__ == '__main__':
    main()
