import time

from langgraph.graph import END, START, StateGraph

from agents import discovery, investment, market_competition, report, technology
from common import save_json, rubric
from models import GraphState


def build_graph(runtime):
    def discover(state):
        prepared = runtime.prepare(state['request']) if hasattr(runtime, 'prepare') else discovery.run(runtime, state['request'])
        return {**prepared, 'candidate_index': 0, 'round_id': 0, 'records': [], 'passed_records': [], 'conditional_records': [], 'candidate_records': [],
                'has_next': bool(prepared['candidate_list']), 'error': None}

    def select(state):
        index = state['candidate_index']
        return {'candidate': state['candidate_list'][index], 'round_id': index + 1,
                'technology': {}, 'market': {}, 'investment': {}}

    def analyze(state, role, function):
        started = time.perf_counter()
        path = runtime.output_dir / 'analyses' / f"{state['candidate']['company_id']}-{role}.json"
        path.parent.mkdir(exist_ok=True)
        try:
            old_path = getattr(runtime, 'resume_dir', runtime.output_dir) / 'analyses' / path.name
            result = None
            if old_path.exists():
                import json
                saved = json.loads(old_path.read_text(encoding='utf-8'))
                if (saved.get('rubric_version') == rubric().get('version') and saved.get('status') == 'completed'
                        and saved.get('company_id') == state['candidate']['company_id']):
                    result = {**saved, 'round_id': state['round_id']}
            if result is None:
                result = function(runtime, state['candidate'], state['round_id'])
        except Exception as error:
            result = {'company_id': state['candidate']['company_id'], 'round_id': state['round_id'],
                      'status': 'failed', 'summary': '', 'findings': [], 'sources': [], 'details': {},
                      'risks': [], 'missing': [f'{role} 분석 실패'], 'error': type(error).__name__}
        result['seconds'] = round(time.perf_counter() - started, 3)
        save_json(path, result)
        return {role: result}

    def judge(state):
        tech, market = state['technology'], state['market']
        if not getattr(runtime, 'demo', False) and not getattr(runtime, 'offline_evaluation', False):
            from evidence_audit import audit
            tech, market = audit(runtime, state['candidate'], tech, market)
            for role, analysis in [('technology', tech), ('market', market)]:
                save_json(runtime.output_dir / 'analyses' / f"{state['candidate']['company_id']}-{role}.json", analysis)
        result = investment.evaluate(state['candidate'], tech, market, state['round_id'])
        records = state['records'] + [result]
        passed = state['passed_records'] + ([result] if result['decision'] == 'pass' else [])
        conditional = state.get('conditional_records', []) + ([result] if result['decision'] == 'conditional' else [])
        shortlisted = passed + conditional
        index = state['candidate_index'] + 1
        stop = 'five_candidates' if len(shortlisted) >= 5 else 'candidates_exhausted' if index >= len(state['candidate_list']) else ''
        save_json(runtime.output_dir / 'records.json', records)
        return {'technology': tech, 'market': market, 'investment': result, 'records': records, 'passed_records': passed,
                'conditional_records': conditional, 'candidate_records': shortlisted,
                'candidate_index': index, 'has_next': index < len(state['candidate_list']), 'stop_reason': stop}

    def make_report(state):
        stop = state.get('stop_reason') or 'no_candidates'
        metadata = {'candidate_count': len(state['candidate_list']), 'evaluated_count': len(state['records']),
                    'stop_reason': stop, 'page_count': state['doc_pages'], 'demo': getattr(runtime, 'demo', False),
                    'excluded': state.get('prepared', {}).get('excluded', []),
                    'unresolved': state.get('prepared', {}).get('unresolved', []),
                    'rubric_version': rubric().get('version'), 'score_scale': rubric()['maximum_score'],
                    'criterion_count': len(rubric()['criteria']), 'pass_score': rubric()['pass_score'],
                    'execution_mode': 'saved_evidence_regrade' if getattr(runtime, 'offline_evaluation', False) else 'demo' if getattr(runtime, 'demo', False) else 'live',
                    'confirmed_count': len(state['passed_records']), 'conditional_count': len(state.get('conditional_records', []))}
        ranked = sorted(state['passed_records'], key=lambda r: (-r['total_score'], r['name']))[:5]
        ranked_candidates = sorted(state.get('candidate_records', state['passed_records']), key=lambda r: (-r['total_score'], r['name']))[:5]
        save_json(runtime.output_dir / 'ranked_candidates.json', ranked_candidates)
        save_json(runtime.output_dir / 'run_summary.json', metadata)
        save_json(runtime.output_dir / 'ranked_passed.json', ranked)
        save_json(runtime.output_dir / 'retrieval_log.json', runtime.corpus.history)
        try:
            result = report.create_report(state['records'], runtime.output_dir, metadata)
            return {'report': result, 'ranked_passed': ranked, 'ranked_candidates': ranked_candidates, 'report_error': None, 'stop_reason': stop}
        except Exception as error:
            return {'report': {}, 'ranked_passed': ranked, 'ranked_candidates': ranked_candidates, 'report_error': str(error), 'stop_reason': stop}

    graph = StateGraph(GraphState)
    graph.add_node('discovery', discover)
    graph.add_node('select_candidate', select)
    graph.add_node('technology_analysis', lambda s: analyze(s, 'technology', technology.run))
    graph.add_node('market_analysis', lambda s: analyze(s, 'market', market_competition.run))
    graph.add_node('investment_decision', judge)
    graph.add_node('report_generation', make_report)
    graph.add_edge(START, 'discovery')
    graph.add_conditional_edges('discovery', lambda s: 'select' if s['has_next'] else 'report',
                               {'select': 'select_candidate', 'report': 'report_generation'})
    graph.add_edge('select_candidate', 'technology_analysis')
    graph.add_edge('select_candidate', 'market_analysis')
    # 두 분석의 완료를 기다리는 AND 합류입니다.
    graph.add_edge(['technology_analysis', 'market_analysis'], 'investment_decision')
    graph.add_conditional_edges('investment_decision', lambda s: 'report' if s['stop_reason'] else 'next',
                               {'report': 'report_generation', 'next': 'select_candidate'})
    graph.add_edge('report_generation', END)
    return graph.compile()
