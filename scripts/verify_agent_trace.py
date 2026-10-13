"""LangSmith에 저장된 노드 수와 로컬 계획을 대조합니다. 원문·키는 내보내지 않습니다."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    from dotenv import load_dotenv
    from langsmith import Client
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--env-file', type=Path, default=Path('.env'))
    args = parser.parse_args()
    load_dotenv(args.env_file, override=False)
    folder = args.run_dir
    state = json.loads((folder / 'state.json').read_text())
    history = folder / 'execution-segments.json'
    traces = ([segment['trace'] for segment in json.loads(history.read_text())]
              if history.exists() else [json.loads((folder / 'trace.json').read_text())])
    client = Client()
    groups = []
    report_versions = []
    for trace in traces:
        root = client.read_run(trace['run_id'])
        children = list(client.list_runs(trace_id=trace['run_id'], limit=2000))
        counts = Counter(run.name for run in children)
        nodes = [{'name': run.name, 'id': str(run.id), 'parent_run_id': str(run.parent_run_id),
                  'start_time': run.start_time.isoformat(),
                  'end_time': run.end_time.isoformat() if run.end_time else None,
                  'error': bool(run.error)} for run in children
                 if run.name in {'planner', 'research_worker', 'synthesizer', 'judge_node', 'rework', 'finish'}]
        for run in children:
            if run.name not in {'synthesizer', 'judge_node'} or not isinstance(run.outputs, dict):
                continue
            report_versions.append({'run_id': str(run.id), 'name': run.name,
                                    'start_time': run.start_time.isoformat(),
                                    'output': {key: run.outputs[key] for key in
                                               ('report', 'evaluation', 'feedback', 'route', 'step_count')
                                               if key in run.outputs}})
        boundaries = [(timestamp, delta) for node in nodes
                      if node['name'] == 'research_worker' and node['end_time']
                      for timestamp, delta in ((node['start_time'], 1), (node['end_time'], -1))]
        concurrent = peak = 0
        for _, delta in sorted(boundaries):
            concurrent += delta
            peak = max(peak, concurrent)
        groups.append({'run_id': trace['run_id'], 'url': client.get_run_url(run=root),
                       'root_finished': root.end_time is not None, 'root_error': bool(root.error),
                       'node_counts': dict(counts), 'max_concurrent_workers': peak, 'nodes': nodes})
    result = {'trace_id': state['trace_id'], 'planned_tasks': len(state['plan']),
              'local_result_count': len(state['results']), 'status': state['status'], 'traces': groups}
    (folder / 'trace-verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    (folder / 'report-versions.json').write_text(json.dumps(
        sorted(report_versions, key=lambda item: item['start_time']),
        ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'planned_tasks': result['planned_tasks'], 'status': result['status'],
                      'traces': [{'run_id': group['run_id'], 'counts': {key: value for key, value in group['node_counts'].items()
                                if key in {'planner', 'research_worker', 'synthesizer', 'judge_node', 'rework', 'finish'}}}
                                 for group in groups]}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
