import argparse
import json
from pathlib import Path

from agents import discovery, investment, market_competition, report, technology
from common import ROOT, Runtime, save_json, settings
from rag import Corpus
from prepared_data import DEFAULT_REQUEST, prepare


def main():
    parser = argparse.ArgumentParser(description='담당 에이전트만 실행합니다.')
    parser.add_argument('agent', choices=['discovery', 'technology', 'market', 'investment', 'report'])
    parser.add_argument('--run', type=Path, default=ROOT / 'output/demo')
    parser.add_argument('--index', type=int, default=0)
    parser.add_argument('--demo', action='store_true')
    parser.add_argument('--refresh-data', action='store_true', help='탐색 문서·후보를 새로 수집합니다.')
    args = parser.parse_args()
    if args.refresh_data and (args.agent != 'discovery' or args.demo):
        parser.error('--refresh-data는 실제 discovery 실행에서만 사용합니다.')
    folder = args.run.resolve()
    output = folder / f'part-{args.agent}'
    config = settings()
    config['refresh_data'] = args.refresh_data
    if args.refresh_data and output.exists():
        parser.error('새 수집은 새 --run 폴더를 지정하세요.')
    if args.demo:
        from demo import DemoRuntime
        runtime = DemoRuntime(config, output)
        state = runtime.prepare(config['domain'])
    else:
        runtime = Runtime(config, output)
        state = {}
    if args.agent == 'discovery':
        result = state if args.demo else prepare(runtime, DEFAULT_REQUEST)
    elif args.agent == 'report':
        records = json.loads((folder / 'records.json').read_text(encoding='utf-8'))
        metadata = json.loads((folder / 'run_summary.json').read_text(encoding='utf-8'))
        result = report.create_report(records, output, metadata)
    else:
        candidates = state.get('candidate_list') if args.demo else json.loads((folder / 'candidates.json').read_text(encoding='utf-8'))
        if not 0 <= args.index < len(candidates):
            parser.error('후보 번호는 0부터 시작합니다. candidates.json의 기업 수를 확인해 주세요.')
        candidate = candidates[args.index]
        cid, round_id = candidate['company_id'], args.index + 1
        if args.agent == 'investment':
            analyses = folder / 'analyses'
            tech = json.loads((analyses / f'{cid}-technology.json').read_text(encoding='utf-8'))
            market = json.loads((analyses / f'{cid}-market.json').read_text(encoding='utf-8'))
            if not args.demo:
                from evidence_audit import audit
                # 같은 실행의 일부 에이전트를 다시 돌려도 사용한 비용을 초기화하지 않습니다.
                spent = []
                for cost_file in [folder / 'cost.json', output / 'cost.json']:
                    if cost_file.exists():
                        cost = json.loads(cost_file.read_text(encoding='utf-8'))
                        spent.append(float(cost['estimated_spent_usd']) + float(cost.get('reserved_usd', 0)))
                if spent:
                    runtime.spent_usd = max(spent)
                    runtime.carried_cost_from = str(folder)
                    runtime._budget_file()
                tech, market = audit(runtime, candidate, tech, market)
                for role, analysis in [('technology', tech), ('market', market)]:
                    save_json(output / 'analyses' / f'{cid}-{role}.json', analysis)
            result = investment.evaluate(candidate, tech, market, round_id)
        else:
            if not args.demo:
                sources = json.loads((folder / 'corpus/sources.json').read_text(encoding='utf-8'))
                runtime.corpus = Corpus(sources, config, ROOT / '.cache')
            function = technology.run if args.agent == 'technology' else market_competition.run
            result = function(runtime, candidate, round_id)
    save_json(output / 'result.json', result)
    print(output / 'result.json')


if __name__ == '__main__':
    main()
