import hashlib
import json
import shutil
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

from common import ROOT, rubric, save_json
from workflow import build_graph


def migrate_analysis(analysis, role):
    if role not in ('technology', 'market'):
        raise ValueError('기술 또는 시장 분석만 재채점할 수 있습니다.')
    rules = rubric()
    old_version = analysis.get('rubric_version')
    if old_version not in ('2.0', rules['version']):
        raise ValueError('지원하지 않는 평가기준입니다. 근거 분석을 먼저 확인하세요.')
    result = deepcopy(analysis)
    active = {r['id'] for r in rules['criteria'] if r['owner'] == role}
    if old_version == '2.0':
        archived = json.loads((ROOT / 'docs/archive/rubric-v2.json').read_text())
        old = {r['id']: r for r in archived['criteria']}
        for rule in rules['criteria']:
            for key in ('owner', 'field', 'rule', 'values', 'allowed', 'high', 'medium',
                        'minimum', 'integer', 'alternative_categories', 'evidence_requirements', 'unit'):
                if old[rule['id']].get(key) != rule.get(key):
                    raise ValueError('남겨 둔 항목의 채점 규칙도 변경되었습니다. 단순 재채점할 수 없습니다.')
        if role == 'technology':
            result['qualitative_findings'] = [f for f in result['findings'] if f['criterion_id'] in (4, 5, 9)]
    result['findings'] = [f for f in result['findings'] if f['criterion_id'] in active]
    result['missing'] = [f"{f['criterion_id']}번: {f['reason']}" for f in result['findings'] if f['status'] != 'verified']
    result['summary'] = ' '.join(f['reason'] for f in result['findings'] if f['status'] == 'verified') or '확인 가능한 평가 근거가 부족합니다.'
    result['rubric_version'] = rules['version']
    result['regraded_from_version'] = old_version
    return result


def regrade_run(source_run, output_dir):
    source, output = Path(source_run).resolve(), Path(output_dir).resolve()
    if source == output or source in output.parents:
        raise ValueError('원본 실행 폴더 밖의 새 출력 폴더를 지정하세요.')
    if (output / 'records.json').exists():
        raise ValueError('기존 재채점 결과를 보존하기 위해 새 출력 폴더를 지정하세요.')
    load = lambda name: json.loads((source / name).read_text(encoding='utf-8'))
    candidates = load('candidates.json')
    if load('run_summary.json').get('demo'):
        raise ValueError('실제 결과 재채점에는 실제 실행 기록을 지정하세요.')
    sources = load('corpus/sources.json')
    if not 1 <= len(sources) <= 200:
        raise ValueError('원문 자료는 1~200쪽이어야 합니다.')
    migrated, origin = {}, []
    for candidate in candidates:
        cid = candidate['company_id']
        for role in ('technology', 'market'):
            relative = f'analyses/{cid}-{role}.json'
            analysis = load(relative)
            if analysis.get('company_id') != cid:
                raise ValueError('분석 기록의 기업 ID가 다릅니다.')
            migrated[relative] = migrate_analysis(analysis, role)
            origin.append({'file': relative, 'sha256': hashlib.sha256((source / relative).read_bytes()).hexdigest()})
    output.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source / 'corpus', output / 'corpus', dirs_exist_ok=True)
    for file in ('candidates.json', 'excluded_candidates.json', 'unresolved_candidates.json', 'source_review.json'):
        if (source / file).exists():
            shutil.copy2(source / file, output / file)
    for file, value in migrated.items():
        save_json(output / file, value)
    prepared = {'candidate_list': candidates, 'doc_pages': len(sources), 'page_cap': 200,
                'prepared': {'excluded': load('excluded_candidates.json') if (source / 'excluded_candidates.json').exists() else [],
                             'unresolved': load('unresolved_candidates.json') if (source / 'unresolved_candidates.json').exists() else []}}
    def no_api(*args, **kwargs):
        raise RuntimeError('저장 근거 재채점에서는 API를 호출하지 않습니다.')
    runtime = SimpleNamespace(output_dir=output, resume_dir=output, offline_evaluation=True, demo=False,
                              corpus=SimpleNamespace(history=[]), prepare=lambda request: prepared, ask=no_api, search=no_api)
    graph = build_graph(runtime)
    (output / 'graph.mmd').write_text(graph.get_graph().draw_mermaid())
    state = {'request': '저장된 실제 근거에 평가기준 3.0 적용'}
    for event in graph.stream(state, config={'recursion_limit': 5 * len(candidates) + 10}, stream_mode='updates'):
        for node, update in event.items():
            state.update(update)
            save_json(output / 'state.json', state)
    save_json(output / 'regrade_provenance.json', {'source_run': source.name, 'rules': rubric(), 'original_analyses': origin,
              'new_api_calls': 0, 'new_api_cost_usd': 0, 'new_documents': 0,
              'evaluated_count': len(state['records']), 'unassessed_count': len(candidates) - len(state['records']),
              'method': '기존 원문·분석 근거는 유지하고 제외 항목 제거 및 점수·분기만 재계산'})
    if state.get('report_error'):
        raise ValueError(state['report_error'])
    save_json(output / 'report.json', state['report'])
    return {**state['report'], 'evaluated': len(state['records']), 'passed': len(state['passed_records']),
            'conditional': len(state['conditional_records']), 'api_cost_usd': 0}
