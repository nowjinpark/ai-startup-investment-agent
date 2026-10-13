"""계획, 동적 병렬 조사, 작성, 평가와 제한된 재작업을 연결합니다."""
import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

from langgraph.graph import StateGraph, START, END
from langgraph.types import Send

from .state import AgentState, Plan, VIEWS

MAX_TASKS = 20
MAX_CONTROL_STEPS = 16


class EventLog:
    """결정의 이유는 State에 계속 쌓지 않고 외부 로그로 남깁니다."""
    def __init__(self, folder):
        self.path = Path(folder) / 'events.jsonl'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()

    def write(self, state, node, decision, reason, **details):
        record = {'trace_id': state['trace_id'], 'node': node, 'decision': decision,
                  'reason': reason, 'ts': datetime.now(timezone.utc).isoformat(), **details}
        with self.lock, self.path.open('a', encoding='utf-8') as file:
            file.write(json.dumps(record, ensure_ascii=False) + '\n')


def validate_plan(plan, companies):
    parsed = Plan.model_validate(plan).model_dump()
    tasks = parsed['tasks']
    if not 1 <= len(tasks) <= MAX_TASKS:
        raise ValueError('조사 작업은 1~20개여야 합니다.')
    allowed = {company['company_id'] for company in companies}
    coverage = {company_id: set() for company_id in allowed}
    seen = set()
    for task in tasks:
        key = task['task_id']
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', key) or key in seen:
            raise ValueError('작업 ID가 잘못되었거나 중복됩니다.')
        seen.add(key)
        if task['company_id'] not in allowed or not task['views']:
            raise ValueError('계획이 요청 범위를 벗어났습니다.')
        if len(set(task['views'])) != len(task['views']):
            raise ValueError('한 작업의 관점이 중복됩니다.')
        if coverage[task['company_id']] & set(task['views']):
            raise ValueError('같은 기업의 관점이 여러 작업에 중복 배정됐습니다.')
        if not 1 <= len(task['queries']) <= 3:
            raise ValueError('작업별 검색 질문은 1~3개여야 합니다.')
        if any(not task[field].strip() for field in ('question', 'reason', 'done_condition')):
            raise ValueError('조사 목적·이유·완료 기준이 필요합니다.')
        coverage[task['company_id']].update(task['views'])
    if any(views != set(VIEWS) for views in coverage.values()):
        raise ValueError('모든 기업의 네 관점이 계획에 포함되어야 합니다.')
    return parsed


def gate(state):
    """LLM의 판단을 읽되, 종료 결정은 부작용 없는 함수로 통제합니다."""
    evaluation = state.get('evaluation', {})
    criteria = evaluation.get('criteria', [])
    results = state.get('results', {})
    planned = {task['task_id'] for task in state.get('plan', [])}
    failed = (not planned or planned != set(results)
              or any(result.get('status') != 'ok' for result in results.values()))
    expected = {'groundedness', 'neutrality', 'bias', 'coverage'}
    passed = (len(criteria) == 4 and {item.get('criterion') for item in criteria} == expected
              and all(item.get('passed') is True for item in criteria)
              and not evaluation.get('deterministic_errors') and not failed)
    if passed and evaluation.get('action') == 'approve':
        return 'approve'
    if state.get('last_error') == 'BudgetExceeded':
        return 'fallback'
    if state['revision'] >= state['max_revisions'] or state['step_count'] >= MAX_CONTROL_STEPS:
        return 'fallback'
    if failed or evaluation.get('action') == 'research':
        return 'research'
    return 'rewrite'


def build_graph(service, event_log, checkpointer=None, interrupt_after=None):
    def update(state, node, **values):
        return {'step_count': state.get('step_count', 0) + 1,
                'node_status': {**state.get('node_status', {}), node: 'done'}, **values}

    def planner(state):
        try:
            for attempt in (1, 2):
                try:
                    plan = validate_plan(service.plan(state), state['companies'])
                    break
                except ValueError:
                    if attempt == 2:
                        raise
                    event_log.write(state, 'planner', 'retry', '계획 형식·범위 검증에 실패해 한 번 다시 계획합니다.')
            event_log.write(state, 'planner', 'fan_out', plan['reason'],
                            task_count=len(plan['tasks']), tasks=plan['tasks'])
            return update(state, 'planner', plan=plan['tasks'], plan_reason=plan['reason'],
                          pending_task_ids=[task['task_id'] for task in plan['tasks']],
                          status='running', last_error='')
        except Exception as error:
            kind = type(error).__name__
            event_log.write(state, 'planner', 'fallback', '계획 수립 또는 범위 검증 실패', error=kind)
            return update(state, 'planner', plan=[], pending_task_ids=[], status='fallback', last_error=kind)

    def dispatch(state):
        if state.get('status') == 'fallback':
            return 'finish'
        pending = set(state.get('pending_task_ids', []))
        tasks = [task for task in state['plan'] if task['task_id'] in pending]
        if not tasks:
            return 'synthesizer'
        # 각 Send는 계획의 작업 한 개만 받습니다. 관점별 고정 엣지가 아닙니다.
        return [Send('research_worker', {'task': task, 'revision': state['revision'],
                                        'feedback': state.get('feedback', ''),
                                        'trace_id': state['trace_id']}) for task in tasks]

    def research_worker(worker):
        task = worker['task']
        result = None
        for attempt in (1, 2):
            try:
                result = service.research(task, worker['revision'], worker['feedback'])
                if result.get('task_id') != task['task_id'] or result.get('revision') != worker['revision']:
                    raise ValueError('작업 결과 식별자가 요청과 다릅니다.')
                if result.get('company_id') != task['company_id'] or set(result.get('views', [])) != set(task['views']):
                    raise ValueError('작업 결과의 기업 또는 관점이 요청과 다릅니다.')
                if result.get('status') == 'ok':
                    break
            except Exception as error:
                result = {'task_id': task['task_id'], 'company_id': task['company_id'],
                          'views': task['views'], 'revision': worker['revision'], 'status': 'failed',
                          'summary': '', 'findings': [], 'limitations': ['조사 실행 실패로 확인 필요'],
                          'raw_path': '', 'error': type(error).__name__}
            if result.get('error') == 'BudgetExceeded':
                break
            event_log.write(worker, 'research_worker', 'retry' if attempt == 1 else 'continue',
                            '실패 작업은 한 번 재시도하고 다른 작업 결과는 유지합니다.',
                            task_id=task['task_id'], attempt=attempt, error=result.get('error', ''))
        event_log.write(worker, 'research_worker', result['status'], '작업 결과를 task_id로 병합합니다.',
                        task_id=task['task_id'], revision=worker['revision'], views=task['views'])
        return {'results': {task['task_id']: result}}

    def synthesizer(state):
        try:
            report = service.synthesize(state)
            event_log.write(state, 'synthesizer', 'evaluate', '병렬 결과와 원문 근거를 취합해 보고서를 작성했습니다.',
                            revision=state['revision'], result_count=len(state['results']))
            return update(state, 'synthesizer', report=report, last_error='', pending_task_ids=[])
        except Exception as error:
            kind = type(error).__name__
            event_log.write(state, 'synthesizer', 'fallback', '보고서 생성 실패', error=kind)
            return update(state, 'synthesizer', last_error=kind, status='fallback', pending_task_ids=[])

    def judge_node(state):
        if state.get('status') == 'fallback':
            return update(state, 'judge_node', route='fallback')
        try:
            evaluation = service.evaluate(state)
        except Exception as error:
            kind = type(error).__name__
            evaluation = {'criteria': [], 'action': 'rewrite', 'feedback': '품질 평가 호출 실패: ' + kind,
                          'retry_task_ids': [], 'deterministic_errors': ['judge_unavailable']}
            state = {**state, 'last_error': kind}
        next_state = {**state, 'evaluation': evaluation, 'step_count': state['step_count'] + 1}
        route = gate(next_state)
        event_log.write(state, 'judge_node', route, evaluation['feedback'],
                        revision=state['revision'], evaluation=evaluation)
        return update(state, 'judge_node', evaluation=evaluation, route=route,
                      feedback=evaluation['feedback'], last_error=state.get('last_error', ''))

    def rework(state):
        valid_ids = {task['task_id'] for task in state['plan']}
        requested = set(state.get('evaluation', {}).get('retry_task_ids', [])) & valid_ids
        failed = ({key for key, result in state['results'].items() if result['status'] != 'ok'}
                  | (valid_ids - set(state['results'])))
        pending = (requested | failed) if state['route'] == 'research' else set()
        # 평가자가 작업 ID를 주지 않았으면 기존 계획 중 전체를 다시 조사합니다.
        if state['route'] == 'research' and not pending:
            pending = valid_ids
        event_log.write(state, 'rework', state['route'], state['feedback'], pending_task_ids=sorted(pending))
        return update(state, 'rework', revision=state['revision'] + 1,
                      pending_task_ids=sorted(pending), last_error='')

    def finish(state):
        approved = state.get('route') == 'approve' and state.get('status') != 'fallback'
        status = 'approved' if approved else 'fallback'
        report = state.get('report', '')
        if not approved:
            notice = ('## 실행 한계\n\n품질 통과를 확인하지 못해 추가 검토가 필요합니다. '
                      + (state.get('feedback') or state.get('last_error') or '일부 조사 결과가 부족합니다.') + '\n\n')
            if report:
                marker = '## REFERENCE'
                report = report.replace(marker, notice + marker) if marker in report else report + '\n' + notice
            else:
                report = '# SUMMARY\n\n실행이 완료되지 않아 투자 판단을 제시하지 않습니다.\n\n' + notice + '## REFERENCE\n\n사용한 출처 없음.\n'
        event_log.write(state, 'finish', status, '품질 기준 통과' if approved else '한도 또는 오류로 제한 종료',
                        revision=state.get('revision', 0))
        return update(state, 'finish', status=status, report=report)

    graph = StateGraph(AgentState)
    for name, function in [('planner', planner), ('research_worker', research_worker),
                           ('synthesizer', synthesizer), ('judge_node', judge_node),
                           ('rework', rework), ('finish', finish)]:
        graph.add_node(name, function)
    graph.add_edge(START, 'planner')
    graph.add_conditional_edges('planner', dispatch, ['research_worker', 'synthesizer', 'finish'])
    graph.add_edge('research_worker', 'synthesizer')
    graph.add_edge('synthesizer', 'judge_node')
    graph.add_conditional_edges('judge_node', lambda state: state['route'],
                                {'approve': 'finish', 'fallback': 'finish',
                                 'research': 'rework', 'rewrite': 'rework'})
    graph.add_conditional_edges('rework', dispatch, ['research_worker', 'synthesizer', 'finish'])
    graph.add_edge('finish', END)
    return graph.compile(checkpointer=checkpointer, interrupt_after=interrupt_after, name='PhysicalAI_Orchestrator')
