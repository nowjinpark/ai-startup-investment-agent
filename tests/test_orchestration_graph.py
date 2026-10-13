"""가짜 LLM으로 제어 흐름을 검증합니다. 실제 모델 성능 평가는 아닙니다."""
import json
from copy import deepcopy
import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from orchestration.graph import build_graph, EventLog, validate_plan, gate
from orchestration.state import VIEWS, merge_results


def initial(companies=1, revisions=2):
    return {'companies': [{'company_id': f'c{i}', 'name': f'기업{i}'} for i in range(companies)],
            'request': '검토', 'trace_id': 'test-thread', 'revision': 0, 'max_revisions': revisions,
            'step_count': 0, 'node_status': {}, 'results': {}, 'status': 'running', 'feedback': ''}


class FakeService:
    def __init__(self, *, split=False, actions=(), fail_ids=()):
        self.split, self.actions, self.fail_ids = split, list(actions), set(fail_ids)
        self.calls, self.writes = [], 0

    def plan(self, state):
        tasks = []
        for company in state['companies']:
            groups = [list(VIEWS[:2]), list(VIEWS[2:])] if self.split else [list(VIEWS)]
            for i, views in enumerate(groups):
                tasks.append({'task_id': f'{company["company_id"]}-{i}', 'company_id': company['company_id'],
                              'views': views, 'question': '질문', 'queries': ['검색'], 'reason': '독립 조사',
                              'done_condition': '근거와 부족한 점 확인'})
        return {'reason': '요청과 기업에 맞춘 계획', 'tasks': tasks}

    def research(self, task, revision, feedback):
        self.calls.append((task['task_id'], revision))
        if task['task_id'] in self.fail_ids:
            raise TimeoutError('테스트 오류')
        return {'task_id': task['task_id'], 'revision': revision, 'company_id': task['company_id'],
                'views': task['views'], 'status': 'ok', 'summary': '결과', 'findings': [],
                'limitations': [], 'raw_path': '', 'error': ''}

    def synthesize(self, state):
        self.writes += 1
        return '# SUMMARY\n\n검토 결과입니다.\n\n## REFERENCE\n\n자료입니다.\n'

    def evaluate(self, state):
        action = self.actions.pop(0) if self.actions else 'approve'
        return {'criteria': [{'criterion': criterion, 'passed': action == 'approve', 'reason': '검사'}
                             for criterion in ('groundedness', 'neutrality', 'bias', 'coverage')],
                'action': action, 'feedback': '검토 의견', 'retry_task_ids': ['c0-0'],
                'deterministic_errors': []}


@pytest.mark.parametrize('count,split,expected', [(1, False, 1), (2, True, 4), (5, False, 5)])
def test_fanout_follows_validated_plan(tmp_path, count, split, expected):
    service = FakeService(split=split)
    result = build_graph(service, EventLog(tmp_path)).invoke(initial(count), {'max_concurrency': 3})
    assert len(service.calls) == expected
    assert len(result['results']) == expected
    assert result['status'] == 'approved'
    assert result['pending_task_ids'] == []
    assert service.writes == 1  # fan-in 뒤에 작성은 한 번


def test_research_only_targeted_failed_quality_task(tmp_path):
    service = FakeService(split=True, actions=['research', 'approve'])
    result = build_graph(service, EventLog(tmp_path)).invoke(initial(2))
    assert result['revision'] == 1
    assert service.calls.count(('c0-0', 1)) == 1
    assert len(service.calls) == 5
    assert len(result['results']) == 4
    assert result['status'] == 'approved'


def test_rewrite_does_not_repeat_research(tmp_path):
    service = FakeService(actions=['rewrite', 'approve'])
    result = build_graph(service, EventLog(tmp_path)).invoke(initial())
    assert len(service.calls) == 1 and service.writes == 2
    assert result['status'] == 'approved'


def test_failed_worker_keeps_other_results_and_terminates(tmp_path):
    service = FakeService(fail_ids=['c0-0'])
    result = build_graph(service, EventLog(tmp_path)).invoke(initial(2, revisions=1))
    assert result['status'] == 'fallback'  # Judge가 approve여도 실패 작업을 숨기지 않음
    assert result['results']['c1-0']['status'] == 'ok'
    assert service.calls.count(('c0-0', 0)) == 2
    assert service.calls.count(('c0-0', 1)) == 2
    assert result['step_count'] <= 16
    assert '품질 통과를 확인하지 못해' in result['report']


def test_persistent_resume_does_not_replan(tmp_path):
    path = str(tmp_path / 'checkpoint.sqlite')
    config = {'configurable': {'thread_id': 'test-thread'}}
    service = FakeService(split=True)
    with SqliteSaver.from_conn_string(path) as saver:
        graph = build_graph(service, EventLog(tmp_path), saver, interrupt_after=['planner'])
        graph.invoke(initial(), config)
        assert graph.get_state(config).next
    class ResumeService(FakeService):
        def plan(self, state):
            raise AssertionError('복구 시 계획을 반복하면 안 됩니다.')
    resumed = ResumeService()
    with SqliteSaver.from_conn_string(path) as saver:
        graph = build_graph(resumed, EventLog(tmp_path), saver)
        result = graph.invoke(None, config)
    assert result['status'] == 'approved' and len(resumed.calls) == 2


def test_invalid_plan_does_not_start_workers(tmp_path):
    service = FakeService()
    service.plan = lambda state: {'reason': '잘못된 대상', 'tasks': []}
    result = build_graph(service, EventLog(tmp_path)).invoke(initial())
    assert result['status'] == 'fallback' and not service.calls


def test_missing_views_are_replanned_with_company_specific_feedback(tmp_path):
    class CorrectingPlanner(FakeService):
        def __init__(self):
            super().__init__()
            self.planning_inputs = []

        def plan(self, state):
            self.planning_inputs.append(deepcopy(state))
            plan = super().plan(state)
            if not state.get('planning_feedback'):
                plan['tasks'][0]['views'] = ['technology', 'application']
                plan['tasks'][1]['views'] = ['market']
            else:
                feedback = state['planning_feedback']
                missing = json.loads(feedback[feedback.index('{'):])
                assert missing == {'c0': ['market', 'stakeholders'],
                                   'c1': ['technology', 'stakeholders', 'application']}
                plan['tasks'][0]['question'] = '피드백을 확인한 모델이 다시 정한 질문'
            return plan

    service = CorrectingPlanner()
    state = initial(2)
    result = build_graph(service, EventLog(tmp_path)).invoke(state)
    assert result['status'] == 'approved' and len(service.planning_inputs) == 2
    assert len(service.calls) == 2  # 잘못된 첫 계획은 실행되지 않습니다.
    assert result['plan'][0]['question'] == '피드백을 확인한 모델이 다시 정한 질문'
    assert 'planning_feedback' not in state and 'planning_feedback' not in result
    events = [json.loads(line) for line in (tmp_path / 'events.jsonl').read_text().splitlines()]
    retry = next(event for event in events if event['decision'] == 'retry')
    assert retry['validation_feedback'] == service.planning_inputs[1]['planning_feedback']


@pytest.mark.parametrize('change', ['duplicate', 'outsider', 'missing_view', 'unsafe_id', 'many_queries'])
def test_plan_scope_contract(change):
    state = initial()
    plan = FakeService().plan(state)
    task = plan['tasks'][0]
    if change == 'duplicate': plan['tasks'].append(deepcopy(task))
    if change == 'outsider': task['company_id'] = 'not-requested'
    if change == 'missing_view': task['views'] = ['market']
    if change == 'unsafe_id': task['task_id'] = '../../secret'
    if change == 'many_queries': task['queries'] = ['query'] * 4
    with pytest.raises(ValueError): validate_plan(plan, state['companies'])


def test_reducer_idempotency_order_and_conflict():
    old = {'a': {'revision': 0, 'value': 'old'}}
    new = {'a': {'revision': 1, 'value': 'new'}}
    assert merge_results(old, new) == merge_results(new, old) == new
    assert merge_results(new, new) == new
    with pytest.raises(ValueError): merge_results(old, {'a': {'revision': 0, 'value': 'conflict'}})


def test_observability_contains_decision_reason_and_correlation(tmp_path):
    state = build_graph(FakeService(), EventLog(tmp_path)).invoke(initial())
    events = [json.loads(line) for line in (tmp_path / 'events.jsonl').read_text().splitlines()]
    assert all(event['trace_id'] == state['trace_id'] and event['reason'] and event['decision'] for event in events)
    assert 'events' not in state and 'raw_documents' not in state


def test_gate_cannot_approve_missing_planned_result():
    service = FakeService()
    state = initial(revisions=0)
    state['plan'] = service.plan(state)['tasks']
    state['evaluation'] = service.evaluate(state)
    assert gate(state) == 'fallback'


def test_result_from_another_company_is_not_accepted(tmp_path):
    class MixedService(FakeService):
        def research(self, task, revision, feedback):
            result = super().research(task, revision, feedback)
            result['company_id'] = 'another-company'
            return result
    result = build_graph(MixedService(), EventLog(tmp_path)).invoke(initial(revisions=0))
    assert result['status'] == 'fallback'
    assert result['results']['c0-0']['error'] == 'ValueError'
