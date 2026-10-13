from copy import deepcopy
import json

import pytest

from orchestration.service import CRITERIA, LiveService
from orchestration.state import VIEW_LABELS, VIEWS


COMPANY = {'company_id': 'co-a', 'name': '연습기업', 'overview': '현장용 로봇'}
SOURCE = {'source_id': 'S-one', 'company_id': 'co-a', 'doc_type': 'technology',
          'title': '기업 공식 소개', 'url': 'https://example.com/product',
          'published_at': '2026-09-01', 'collected_at': '2026-09-30', 'original_page': 1,
          'text': '회사 공식 소개에 따르면 고객 현장에서 로봇을 시험하고 있습니다. 독립 검증 결과는 제시하지 않았습니다.'}
QUOTE = '고객 현장에서 로봇을 시험하고 있습니다.'
TASK = {'task_id': 'task-01', 'company_id': 'co-a', 'views': list(VIEWS),
        'question': '현장 로봇 적용 근거는?', 'queries': ['현장 사용', '고객 구매', '운영 조건'],
        'reason': '서로 연결된 현장 근거를 함께 확인', 'done_condition': '네 관점 확인 또는 부족 명시'}


class MockCorpus:
    def __init__(self, empty=False, error=None):
        self.sources = {'S-one': deepcopy(SOURCE)}
        self.calls = []
        self.empty = empty
        self.error = error

    def retrieve(self, query, company_id, doc_type, k):
        self.calls.append((query, company_id, doc_type, k))
        if self.error:
            raise self.error
        return [] if self.empty else [{**SOURCE, 'chunk_id': 'S-one:c1'}]

    def source_pages(self, chunks):
        return [self.sources[sid] for sid in dict.fromkeys(c['source_id'] for c in chunks)]


class MockRuntime:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def ask(self, schema, instructions, payload, **kwargs):
        self.calls.append({'schema': schema.__name__, 'payload': payload, **kwargs})
        if schema.__name__ == 'GroundingReview' and schema.__name__ not in self.responses:
            return {'checks': [{'index': c['index'], 'supported': True, 'corrected_text': c['text'],
                                'reason': '테스트에서 원문과 일치하는 것으로 판정', 'evidence_indices': [0],
                                'suitable_views': [c['view']]}
                               for c in payload['claims']]}
        response = self.responses[schema.__name__]
        if isinstance(response, Exception):
            raise response
        return deepcopy(response)


def finding(view='technology', quote=QUOTE, sid='S-one'):
    text = '회사 소개에서 고객 현장 시험을 제시합니다.' if view in {'market', 'stakeholders'} else '회사 소개에서 현장 시험을 제시합니다.'
    return {'view': view, 'text': text,
            'evidence': [{'source_id': sid, 'quote': quote}]}


def research_response(findings=None):
    return {'summary': '현장 시험 근거를 확인했습니다.',
            'findings': findings if findings is not None else [finding(v) for v in VIEWS],
            'limitations': ['기업 공식 소개이며 독립 검증은 추가 확인이 필요합니다.']}


def report_response():
    return {'summary': '공식 소개에 현장 시험이 제시되어 있습니다 [S-one].',
            'selections': [{'company_id': 'co-a', 'view': view, 'finding_ids': [f'task-01:{index}'],
                            'condition_codes': []} for index, view in enumerate(VIEWS)],
            'companies': [{'company_id': 'co-a', 'overview': '회사 소개는 현장 시험을 제시합니다 [S-one].',
                           **{v: '회사 소개에 현장 시험이 제시됩니다 [S-one].' for v in VIEWS},
                           'investment_view': '별도의 투자 적격성 확인이 필요합니다.',
                           'risks': ['독립 검증 자료가 부족합니다.'],
                           'unknowns': ['현재 매출은 확인 필요합니다.']}],
            'comparison': '같은 조건의 비교 근거가 부족합니다.', 'limitations': []}


def evaluation_response(passed=True, action='approve', retries=None):
    return {'criteria': [{'criterion': c, 'passed': passed, 'reason': '원문과 범위를 검토했습니다.'}
                         for c in CRITERIA], 'action': action, 'feedback': '검토 결과입니다.',
            'retry_task_ids': retries or []}


def service(tmp_path, corpus=None, responses=None):
    runtime = MockRuntime(responses or {'Research': research_response(), 'Report': report_response(),
                                        'Evaluation': evaluation_response()})
    return LiveService(runtime, corpus or MockCorpus(), [COMPANY], tmp_path)


def complete_state(s):
    result = s.research(TASK, 0, '')
    state = {'request': '네 관점으로 검토', 'companies': [COMPANY], 'plan': [TASK],
             'revision': 0, 'results': {'task-01': result}}
    state['report'] = s.synthesize(state)
    return state


def test_research_limits_queries_and_keeps_full_source_outside_state(tmp_path):
    s = service(tmp_path)
    task = {**TASK, 'queries': ['질문1', '질문2', '질문3', '질문4']}
    result = s.research(task, 1, '고객과 투자자를 구분')
    assert len(s.corpus.calls) == 3
    assert all(call[1] == 'co-a' and call[3] == 4 for call in s.corpus.calls)
    assert result['status'] == 'ok'
    assert 'sources' not in result and 'chunks' not in result
    raw = json.loads(open(result['raw_path'], encoding='utf-8').read())
    assert raw['sources'][0]['text'] == SOURCE['text']
    assert raw['feedback'] == '고객과 투자자를 구분'


def test_worker_drops_fabricated_quotes_wrong_scope_and_bounds_claims(tmp_path):
    findings = [finding(quote='없는 수치가 실제로 확인됐습니다.'), finding(sid='S-fake')]
    findings += [finding() for _ in range(16)]
    s = service(tmp_path, responses={'Research': research_response(findings)})
    result = s.research(TASK, 0, '')
    assert len(result['findings']) == 12
    assert all(f['evidence'][0]['quote'] == QUOTE for f in result['findings'])
    assert result['rejected_finding_count'] == 2
    assert any('인용 검증에 실패' in text for text in result['limitations'])
    raw = json.loads(open(result['raw_path'], encoding='utf-8').read())
    assert len(raw['response']['findings']) == 18


def test_no_documents_avoids_model_call_and_marks_missing_views(tmp_path):
    s = service(tmp_path, corpus=MockCorpus(empty=True))
    result = s.research(TASK, 0, '')
    assert result['status'] == 'ok' and result['findings'] == []
    assert s.runtime.calls == []
    assert '자료 부재는 사실 부재' in result['limitations'][0]


def test_retrieval_failure_is_separate_and_does_not_expose_exception_secret(tmp_path):
    s = service(tmp_path, corpus=MockCorpus(error=RuntimeError('SECRET-KEY-must-not-appear')))
    result = s.research(TASK, 0, '')
    assert result['status'] == 'failed' and result['error'] == 'RuntimeError'
    assert 'SECRET-KEY' not in json.dumps(result)
    assert 'SECRET-KEY' not in open(result['raw_path'], encoding='utf-8').read()


def test_research_cannot_cite_a_different_company_even_if_corpus_returns_it(tmp_path):
    class WrongCompanyCorpus(MockCorpus):
        def retrieve(self, *args, **kwargs):
            return [{**SOURCE, 'company_id': 'co-other', 'chunk_id': 'wrong:c1'}]
    s = service(tmp_path, corpus=WrongCompanyCorpus())
    result = s.research(TASK, 0, '')
    assert result['findings'] == [] and s.runtime.calls == []


def test_render_keeps_four_views_and_references_only_used_sources(tmp_path):
    report = report_response()
    report['companies'][0]['market'] = '세계에서 가장 우수한 회사입니다 [S-invented].'
    s = service(tmp_path, responses={'Research': research_response(), 'Report': report})
    state = complete_state(s)
    rendered = state['report']
    assert rendered.startswith('## SUMMARY')
    assert all(f'**{label}**' in rendered for label in VIEW_LABELS.values())
    assert 'S-invented' not in rendered and '가장 우수' not in rendered
    assert rendered.split('## REFERENCE')[1].count('[S-one]') == 1
    assert s._check(state) == []


def test_missing_company_response_still_renders_honest_complete_structure(tmp_path):
    report = report_response()
    report['companies'] = []
    s = service(tmp_path, responses={'Research': research_response(), 'Report': report})
    state = complete_state(s)
    assert '## 연습기업' in state['report']
    assert all(f'**{label}**' in state['report'] for label in VIEW_LABELS.values())
    assert '자격이 미확인인 조건부 검토' in state['report']


def test_hybrid_judge_overrides_unjustified_approval_and_uses_separate_model(tmp_path):
    s = service(tmp_path)
    state = complete_state(s)
    state['report'] = state['report'].replace('[S-one]', '[S-fake]', 1)
    result = s.evaluate(state)
    assert result['action'] == 'rewrite'
    assert next(c for c in result['criteria'] if c['criterion'] == 'groundedness')['passed'] is False
    assert result['deterministic_errors']
    assert s.runtime.calls[-1]['model'] == 'gpt-4.1'
    assert s.runtime.calls[0]['model'] == 'gpt-4.1-mini'


def test_duplicate_judge_criteria_cannot_approve(tmp_path):
    response = evaluation_response()
    response['criteria'][1] = deepcopy(response['criteria'][0])
    s = service(tmp_path, responses={'Research': research_response(), 'Report': report_response(), 'Evaluation': response})
    result = s.evaluate(complete_state(s))
    assert result['action'] != 'approve'
    assert len(result['criteria']) == 4
    assert {c['criterion'] for c in result['criteria'] if not c['passed']} == {'groundedness', 'neutrality'}


def test_failed_worker_requests_only_actual_failed_task(tmp_path):
    s = service(tmp_path)
    state = complete_state(s)
    state['results']['task-01'].update(status='failed', error='TimeoutError')
    result = s.evaluate(state)
    assert result['action'] == 'research'
    assert result['retry_task_ids'] == ['task-01']


def test_judge_filters_nonexistent_research_tasks(tmp_path):
    response = evaluation_response(False, 'research', ['task-nonexistent'])
    s = service(tmp_path, responses={'Research': research_response(), 'Report': report_response(), 'Evaluation': response})
    result = s.evaluate(complete_state(s))
    assert result['retry_task_ids'] == ['task-01']
    contexts = s.runtime.calls[-1]['payload']['source_contexts']
    assert QUOTE in contexts[0]['excerpts'][0]


def test_all_criteria_and_checks_pass_approves(tmp_path):
    s = service(tmp_path)
    result = s.evaluate(complete_state(s))
    assert result['action'] == 'approve' and result['retry_task_ids'] == []
    assert result['deterministic_errors'] == []


def test_plan_uses_structured_contract_and_provided_companies(tmp_path):
    s = service(tmp_path, responses={'Plan': {'reason': '현장 관점 연결', 'tasks': [TASK]}})
    result = s.plan({'request': '제품 적용을 검토', 'companies': [COMPANY]})
    assert result['tasks'][0]['views'] == list(VIEWS)
    assert s.runtime.calls[0]['payload']['companies'][0]['company_id'] == 'co-a'


def test_segment_ids_preserve_line_breaks_and_restore_actual_source(tmp_path):
    from common import evidence_segments, resolve_segments

    class SegmentRuntime(MockRuntime):
        def ask(self, schema, instructions, payload, **kwargs):
            if schema.__name__ == 'GroundingReview':
                return super().ask(schema, instructions, payload, **kwargs)
            assert schema.__name__ == 'Research'
            assert 'segments' in instructions and 'id 하나' in instructions
            prepared, units = evidence_segments(payload)
            segment = prepared['sources'][0]['segments'][0]
            response = research_response([finding(v, segment['id']) for v in VIEWS])
            return resolve_segments(response, units)

    corpus = MockCorpus()
    source = {**SOURCE, 'text': '고객 현장에서\n로봇을 시험하고 있습니다.\n독립 검증은 별도 확인이 필요합니다.'}
    corpus.sources['S-one'] = source
    corpus.retrieve = lambda *args, **kwargs: [{**source, 'chunk_id': 'S-one:c1'}]
    s = LiveService(SegmentRuntime({}), corpus, [COMPANY], tmp_path)
    result = s.research(TASK, 0, '')
    assert len(result['findings']) == 4
    assert result['missing_views'] == [] and result['rejected_finding_count'] == 0
    assert all(f['evidence'][0]['quote'] == source['text'] for f in result['findings'])


def test_citation_rejection_cannot_be_approved_as_missing_information(tmp_path):
    findings = [finding(v, '원문에는 없는 인용을 만들었습니다.') for v in VIEWS]
    s = service(tmp_path, responses={'Research': research_response(findings),
                                     'Report': report_response(), 'Evaluation': evaluation_response()})
    state = complete_state(s)
    worker = state['results']['task-01']
    assert worker['retrieved_chunk_count'] > 0
    assert worker['proposed_finding_count'] == worker['rejected_finding_count'] == 4
    assert set(worker['missing_views']) == set(VIEWS)
    assert worker['evidence_status'] == 'citation_rejected'
    evaluation = s.evaluate(state)
    assert evaluation['action'] == 'research' and evaluation['retry_task_ids'] == ['task-01']
    assert next(c for c in evaluation['criteria'] if c['criterion'] == 'coverage')['passed'] is False


def test_uncertainty_word_does_not_allow_uncited_facts_in_summary_or_comparison(tmp_path):
    response = report_response()
    response['summary'] = '연습기업은 고객 900곳을 확보했지만 추가 확인이 필요합니다.'
    response['comparison'] = '연습기업의 매출은 경쟁사보다 20배 높지만 독립 검증이 필요합니다.'
    response['companies'][0]['overview'] = '세계 유일 기업이지만 확인 필요합니다.'
    s = service(tmp_path, responses={'Research': research_response(), 'Report': response})
    state = complete_state(s)
    assert '900곳' not in state['report'] and '20배' not in state['report'] and '세계 유일' not in state['report']
    summary = state['report'].split('## 연습기업')[0]
    comparison = state['report'].split('## 비교와 한계')[1].split('## REFERENCE')[0]
    assert '연습기업' in summary and '조건부' in summary
    assert '[S-one]' in comparison and '같은 조건' in comparison


def test_lack_of_evidence_cannot_become_an_early_stage_claim(tmp_path):
    unsupported = finding('technology')
    unsupported['text'] = '자료가 부족하므로 기술 성숙도는 실증 초기 단계로 보입니다.'
    response = research_response([unsupported])
    response['limitations'] = ['기술 성숙도는 초기 단계이며 시장이 특정 산업에 국한되어 있습니다.']
    s = service(tmp_path, responses={'Research': response})
    result = s.research(TASK, 0, '')
    assert result['findings'] == [] and result['rejected_finding_count'] == 1
    assert '초기 단계' not in ' '.join(result['limitations'])
    assert '국한' not in ' '.join(result['limitations'])


def test_launch_date_cannot_be_used_as_customer_count_date(tmp_path):
    source = {**SOURCE, 'text': '상용화: 2024년 3월, 회사·언론 보도 기준 국내 고객 100곳 이상.'}
    corpus = MockCorpus()
    corpus.sources['S-one'] = source
    corpus.retrieve = lambda *args, **kwargs: [{**source, 'chunk_id': 'S-one:c1'}]
    claim = finding('market', source['text'])
    claim['text'] = '2024년 3월 기준 국내 고객 100곳을 확보했습니다.'
    s = service(tmp_path, corpus=corpus, responses={'Research': research_response([claim])})
    result = s.research(TASK, 0, '')
    assert result['findings'] == [] and result['rejected_views'] == ['market']
    raw = json.loads(open(result['raw_path'], encoding='utf-8').read())
    assert '집계일' in raw['rejected_findings'][0]['reason']


def test_source_claims_and_specific_checks_and_reference_metadata_are_visible(tmp_path):
    response = report_response()
    response['companies'][0]['technology'] = '누적 오차가 1mm라고 소개합니다 [S-one].'
    s = service(tmp_path, responses={'Research': research_response(), 'Report': response})
    state = complete_state(s)
    assert '누적 오차' not in state['report']  # Writer의 새 주장은 유효한 source_id가 있어도 버립니다.
    assert '회사 소개에서 현장 시험을 제시합니다.' in state['report']
    assert '시장 규모' in state['report'] and '핵심 팀원' in state['report']
    assert '자격이 미확인인 조건부 검토' in state['report']
    refs = state['report'].split('## REFERENCE')[1]
    assert '저자 정보 미수집' in refs and 'example.com' in refs and '발행일 2026-09-01' in refs


def test_citation_on_last_sentence_does_not_cover_uncited_first_fact(tmp_path):
    s = service(tmp_path)
    assert s._paragraph('고객이 900곳입니다. 회사 자료는 시험을 설명합니다 [S-one].', {'S-one'}, '검증 실패') == '검증 실패'


def grounding_check(text, index=0, supported=True, indices=None, views=None):
    return {'index': index, 'supported': supported, 'corrected_text': text,
            'reason': '계획·완료 및 실제 지원 인용을 원문과 대조했습니다.',
            'evidence_indices': ([0] if supported else []) if indices is None else indices,
            'suitable_views': list(VIEWS) if views is None else views}


def test_semantic_review_repairs_plan_without_altering_quote_and_saves_reason(tmp_path):
    source = {**SOURCE, 'text': '이달 실증을 위해 테스트베드 구축에 착수했고 다른 공장으로 넓힐 계획이다.'}
    corpus = MockCorpus()
    corpus.sources['S-one'] = source
    corpus.retrieve = lambda *args, **kwargs: [{**source, 'chunk_id': 'S-one:c1'}]
    claim = finding('application', source['text'])
    claim['text'] = '테스트베드를 구축해 여러 공장에 적용 중입니다.'
    corrected = '해당 기사는 테스트베드 구축에 착수했다고 보도합니다.'
    s = service(tmp_path, corpus, {'Research': research_response([claim]),
        'GroundingReview': {'checks': [grounding_check(corrected)]}})
    result = s.research(TASK, 0, '')
    assert result['grounding_status'] == 'reviewed' and result['grounding_corrected_count'] == 1
    assert result['findings'][0]['text'].endswith('테스트베드 구축에 착수했다고 보도합니다.')
    assert result['findings'][0]['evidence'][0]['quote'] == source['text']
    raw = json.loads(open(result['raw_path'], encoding='utf-8').read())
    assert raw['response']['findings'][0]['text'] == claim['text']
    assert raw['grounding_review']['checks'][0]['reason']
    review_call = s.runtime.calls[-1]
    assert review_call['schema'] == 'GroundingReview' and review_call['model'] == 'gpt-4.1'
    assert source['text'] in review_call['payload']['claims'][0]['evidence'][0]['context']


def test_semantic_rejection_with_missing_view_requests_research(tmp_path):
    s = service(tmp_path, responses={'Research': research_response([finding()]),
        'GroundingReview': {'checks': [grounding_check('', supported=False)]},
        'Report': report_response(), 'Evaluation': evaluation_response()})
    state = complete_state(s)
    worker = state['results']['task-01']
    assert worker['findings'] == [] and worker['rejected_views'] == ['technology']
    evaluation = s.evaluate(state)
    assert evaluation['action'] == 'research'
    assert evaluation['retry_task_ids'] == ['task-01']


@pytest.mark.parametrize('checks', [[], [grounding_check(QUOTE), grounding_check(QUOTE)],
                                  [grounding_check(QUOTE, indices=[7])],
                                  [grounding_check(QUOTE, indices=[])]])
def test_semantic_review_missing_duplicate_or_invalid_index_fails_closed(tmp_path, checks):
    s = service(tmp_path, responses={'Research': research_response([finding()]),
                                     'GroundingReview': {'checks': checks}})
    worker = s.research(TASK, 0, '')
    assert worker['status'] == 'failed' and worker['findings'] == []
    assert worker['grounding_status'] == 'execution_failed'


def test_review_failure_does_not_publish_unreviewed_findings(tmp_path):
    s = service(tmp_path, responses={'Research': research_response(),
                                     'GroundingReview': TimeoutError('private provider details')})
    worker = s.research(TASK, 0, '')
    assert worker['status'] == 'failed' and worker['findings'] == []
    assert 'private provider' not in open(worker['raw_path'], encoding='utf-8').read()


def test_supported_check_still_cannot_keep_promotional_or_uncited_number(tmp_path):
    for text in ['회사 소개는 독보적 기술을 설명합니다.', '대표는 2027년 상장을 목표로 말했습니다.']:
        s = service(tmp_path, responses={'Research': research_response([finding()]),
            'GroundingReview': {'checks': [grounding_check(text)]}})
        worker = s.research(TASK, 0, '')
        assert worker['findings'] == [] and worker['rejected_finding_count'] == 1


def test_reviewer_selects_only_actual_supporting_quote(tmp_path):
    text = '대표는 2027년 상장을 목표로 언급했다.'
    source2 = {**SOURCE, 'source_id': 'S-two', 'text': text}
    corpus = MockCorpus()
    corpus.sources['S-two'] = source2
    corpus.retrieve = lambda *args, **kwargs: [{**SOURCE, 'chunk_id': 'c1'}, {**source2, 'chunk_id': 'c2'}]
    claim = finding()
    claim['evidence'].append({'source_id': 'S-two', 'quote': text})
    correct = '해당 기사는 대표의 2027년 상장 목표를 보도합니다.'
    s = service(tmp_path, corpus, {'Research': research_response([claim]),
        'GroundingReview': {'checks': [grounding_check(correct, indices=[1])]}})
    worker = s.research(TASK, 0, '')
    assert [e['source_id'] for e in worker['findings'][0]['evidence']] == ['S-two']


def test_report_writer_cannot_reintroduce_changed_facts_with_valid_citation(tmp_path):
    report = report_response()
    false = '회사는 테스트베드를 구축하고 공장 100곳에 납품했습니다 [S-one].'
    report.update(summary=false, comparison=false, limitations=[false])
    report['companies'][0].update(overview=false, investment_view=false, risks=[false],
                                  **{view: false for view in VIEWS})
    s = service(tmp_path, responses={'Research': research_response(), 'Report': report})
    state = complete_state(s)
    assert '100곳' not in state['report'] and '구축하고' not in state['report']
    assert '현장 시험을 제시합니다' in state['report']
    assert s._check(state) == []


def test_numeric_source_claim_gets_explicit_measurement_attribution(tmp_path):
    source = {**SOURCE, 'text': '회사 측은 누적 오차가 1mm라고 설명한다.'}
    corpus = MockCorpus()
    corpus.sources['S-one'] = source
    corpus.retrieve = lambda *args, **kwargs: [{**source, 'chunk_id': 'S-one:c1'}]
    claim = finding('technology', source['text'])
    claim['text'] = '회사 발표는 누적 오차가 1mm라고 설명합니다.'
    s = service(tmp_path, corpus, {'Research': research_response([claim]), 'Report': report_response()})
    state = complete_state(s)
    assert '회사 발표 기준·독립 실측 아님' in state['results']['task-01']['findings'][0]['text']
    assert '회사 발표 기준·독립 실측 아님' in state['report']


def test_five_company_summary_stays_under_400_without_copying_whole_summary_to_comparison(tmp_path):
    s = service(tmp_path)
    state = complete_state(s)
    results = []
    companies = []
    for index in range(5):
        company = {**COMPANY, 'company_id': f'co-{index}', 'name': f'검토 대상 기업{index}'}
        companies.append(company)
        worker = deepcopy(state['results']['task-01'])
        worker['company_id'] = company['company_id']
        for claim in worker['findings']:
            claim['text'] = '공식 소개는 서로 다른 작업 조건의 현장 적용 계획을 설명하며 실증 착수와 완료 여부의 구분이 필요하다고 제시합니다.'
        results.append(worker)
    summary = s._summary_fallback(results, companies)
    assert len(summary) <= 400 and '5개 기업' in summary
    assert all(company['name'] in summary for company in companies)
    report = state['report']
    actual_summary = report.split('## SUMMARY')[1].split('## 연습기업')[0].strip()
    comparison = report.split('## 비교와 한계')[1].split('## REFERENCE')[0]
    assert len(actual_summary) <= 400 and actual_summary not in comparison


def test_old_results_without_semantic_review_cannot_be_approved(tmp_path):
    s = service(tmp_path)
    state = complete_state(s)
    del state['results']['task-01']['grounding_status']
    evaluation = s.evaluate(state)
    assert evaluation['action'] == 'research' and evaluation['retry_task_ids'] == ['task-01']


def test_source_type_uses_official_domain_and_distinguishes_analysis_from_newsroom(tmp_path):
    s = service(tmp_path)
    company = {**COMPANY, 'website': 'https://ndotlight.com/ko'}
    official = {**SOURCE, 'url': 'https://ndotlight.com/ko/newsroom/story'}
    blog = {**SOURCE, 'url': 'https://doinghun.com/startup-analysis'}
    lookalike = {**SOURCE, 'url': 'https://fake-ndotlight.com/ko/newsroom/story'}
    assert s._source_info(official, company)['source_kind'] == '회사 뉴스룸 발표'
    assert s._source_info(blog, company)['source_kind'] == '외부 분석글'
    assert not s._source_info(lookalike, company)['official_domain_match']
    text = s._source_sentence('공식 소개는 핵심 기술을 소개합니다.', blog, company)
    assert text.startswith('외부 분석글(doinghun.com)') and '공식 소개' not in text
    text = s._source_sentence('공동 창업자의 역할을 소개합니다.', official, company)
    assert text.startswith('회사 뉴스룸 발표(ndotlight.com)')


def test_grounding_payload_contains_source_url_and_official_website(tmp_path):
    s = service(tmp_path)
    s.candidates['co-a']['website'] = 'https://example.com/'
    s.research(TASK, 0, '')
    review = next(call for call in s.runtime.calls if call['schema'] == 'GroundingReview')
    evidence = review['payload']['claims'][0]['evidence'][0]
    assert evidence['url'] == SOURCE['url']
    assert evidence['publisher'] == 'example.com' and evidence['official_domain_match']
    assert review['payload']['company_website'] == 'https://example.com/'


def test_true_but_view_inappropriate_award_is_not_counted_as_market(tmp_path):
    claim = finding('market')
    check = grounding_check('현장 시험을 설명합니다.', views=[])
    s = service(tmp_path, responses={'Research': research_response([claim]),
                                     'GroundingReview': {'checks': [check]}})
    worker = s.research(TASK, 0, '')
    assert worker['findings'] == [] and 'market' in worker['missing_views']
    assert worker['meaning_rejected_count'] == 1


def test_conditional_comment_cannot_become_internalization_completed(tmp_path):
    source = {**SOURCE, 'text': '센서와 AI를 내재화해 경제성을 만들 수 있는지가 핵심이다.'}
    corpus = MockCorpus()
    corpus.sources['S-one'] = source
    corpus.retrieve = lambda *args, **kwargs: [{**source, 'chunk_id': 'one'}]
    claim = finding('technology', source['text'])
    check = grounding_check('센서와 AI를 내재화했다고 설명합니다.')
    s = service(tmp_path, corpus, {'Research': research_response([claim]),
                                  'GroundingReview': {'checks': [check]}})
    worker = s.research(TASK, 0, '')
    assert worker['findings'] == [] and worker['meaning_rejected_count'] == 1


def test_writer_selects_later_fact_and_reuses_only_approved_cross_view(tmp_path):
    s = service(tmp_path)
    state = complete_state(s)
    extra = {**finding('application'), 'text': '외부 자료에 따르면, 고객 프로젝트에 공급사로 참여합니다.',
             'suitable_views': ['market', 'application']}
    state['results']['task-01']['findings'].append(extra)
    response = report_response()
    response['selections'][1]['finding_ids'] = ['task-01:4']
    s.runtime.responses['Report'] = response
    state['report'] = s.synthesize(state)
    market = state['report'].split('**시장성**')[1].split('**이해관계자**')[0]
    assert '고객 프로젝트' in market and '현장 시험' not in market
    assert s._check(state) == []
    # 기술 관점에는 적합하다고 검수되지 않았으므로 같은 ID라도 사용할 수 없습니다.
    response['selections'][0]['finding_ids'] = ['task-01:4']
    s.runtime.responses['Report'] = response
    state['report'] = s.synthesize(state)
    technology = state['report'].split('**기술 성숙도**')[1].split('**시장성**')[0]
    assert '고객 프로젝트' not in technology and '현장 시험' in technology
    assert s._check(state) == []


def test_rewrite_changes_selected_evidence_and_conditions_without_rewriting_fact(tmp_path):
    s = service(tmp_path)
    state = complete_state(s)
    old_report = state['report']
    response = report_response()
    response['selections'][1]['condition_codes'] = ['market_size']
    s.runtime.responses['Report'] = response
    state['feedback'] = '시장 규모와 독립 검증 조건을 보강하세요.'
    state['revision'] = 1
    state['report'] = s.synthesize(state)
    assert state['report'] != old_report
    application = state['report'].split('**도메인 적용성**')[1].split('**검토 의견')[0]
    assert '독립 성능 검증을 뜻하지 않습니다' in application
    market = state['report'].split('**시장성**')[1].split('**이해관계자**')[0]
    assert '시장 규모가 아니며' in market
    assert '회사 소개에서 고객 현장 시험을 제시합니다.' in market
    assert s.runtime.calls[-1]['payload']['previous_report'] == old_report
    assert s._check(state) == []


def test_judge_receives_only_facts_used_in_report(tmp_path):
    s = service(tmp_path)
    state = complete_state(s)
    unused = {**finding('market'), 'text': '출처 자료는 사용하지 않은 별도 고객 집계를 제시합니다.',
              'suitable_views': ['market']}
    state['results']['task-01']['findings'].append(unused)
    s.evaluate(state)
    sent = s.runtime.calls[-1]['payload']['findings'][0]['findings']
    assert unused not in sent
    assert len(sent) == 4


def test_view_hints_override_model_labels_without_changing_verified_facts(tmp_path):
    s = service(tmp_path)
    texts = [
        '외부 자료에 따르면, 트리닉스로 고정밀 3D 데이터를 제공합니다.',
        '외부 자료에 따르면, 엔비디아 옴니버스와 연동합니다.',
        '회사 뉴스룸에 따르면, 현대자동차와 LG전자에 학습 데이터를 공급합니다.',
        '회사 공식 자료에 따르면, 로봇이 아니라 좌표를 만드는 회사입니다.',
        '외부 자료에 따르면, 박희준 대표가 공장 확장 계획을 말했습니다.',
    ]
    findings = [{**finding(), 'text': text, 'suitable_views': ['market', 'stakeholders']}
                for text in texts]
    original = deepcopy(findings)
    catalog = s._catalog([{'task_id': 't', 'company_id': 'co-a', 'status': 'ok', 'findings': findings}])
    assert set(s._view_candidates(catalog, 'co-a', 'market')) == {'t:2'}
    assert set(s._view_candidates(catalog, 'co-a', 'stakeholders')) == {'t:4'}
    assert findings == original  # 원문 검수 사실과 저장된 모델 판정 자체는 바꾸지 않습니다.
    assert catalog['t:0']['suitable_views'] == []


def test_summary_contains_selected_market_result_and_every_company_under_400(tmp_path):
    s = service(tmp_path)
    names = ['로보아르테', '로보콘', '리옵스', '비욘드허니컴', '엔닷라이트']
    companies, results, selections = [], [], {}
    for index, name in enumerate(names):
        cid, task_id = f'co-{index}', f't-{index}'
        companies.append({'company_id': cid, 'name': name})
        text = '외부 자료에 따르면, 고객 기업에 로봇을 판매했다고 소개합니다.'
        selected = {**finding('market'), 'text': text, 'suitable_views': ['market']}
        ignored = {**finding('market'), 'text': '이 문장은 선택되지 않은 수출 실적입니다.', 'suitable_views': ['market']}
        results.append({'task_id': task_id, 'company_id': cid, 'status': 'ok', 'findings': [selected, ignored]})
        selections[(cid, 'market')] = {'finding_ids': [f'{task_id}:0']}
    summary = s._summary_fallback(results, companies, selections)
    assert len(summary) <= 400 and all(name in summary for name in names)
    assert text in summary and '[S-one]' in summary and '조건부' in summary
    assert '선택되지 않은' not in summary
    assert summary.count(text) in {1, 2}


def test_long_summary_fact_is_kept_whole_instead_of_cutting_its_claim(tmp_path):
    s = service(tmp_path)
    companies = [{'company_id': f'co-{i}', 'name': name} for i, name in enumerate(
        ['로보아르테', '로보콘', '리옵스', '비욘드허니컴', '엔닷라이트'])]
    text = '회사 뉴스룸 발표(ndotlight.com)에 따르면, 현대자동차와 LG전자 등 고객사의 프로젝트에 학습 데이터를 공급하는 역할로 참여한다고 설명합니다.'
    fact = {**finding('market'), 'text': text, 'suitable_views': ['market']}
    results = [{'task_id': 't', 'company_id': 'co-4', 'status': 'ok', 'findings': [fact]}]
    summary = s._summary_fallback(results, companies, {('co-4', 'market'): {'finding_ids': ['t:0']}})
    assert len(summary) <= 400 and text in summary and '[S-one]' in summary


def test_date_formats_are_equivalent_but_decimal_and_timeline_changes_are_not():
    from orchestration.service import _inference_error
    assert _inference_error('2024년 11월 공급 계약을 체결했습니다.',
                            [{'quote': '공급 계약 2024.11.14'}]) is None
    assert _inference_error('오차는 1mm입니다.', [{'quote': '오차는 1.5mm입니다.'}])
    assert _inference_error('2024년 3월 기준 고객 100곳입니다.',
                            [{'quote': '상용화: 2024년 3월, 회사·언론 보도 기준 고객 100곳'}])
    assert _inference_error('2026년 2월 기준 고객 100곳에 공급했습니다.',
                            [{'quote': '2024년 3월 상용화, 2026년 2월 전자신문 인터뷰 기준 고객 100곳에 공급'}]) is None
    assert _inference_error('3년 연속 투자를 받았습니다.',
                            [{'quote': '3D 기업에 2021년, 2022년에 이어 세 번째 투자'}])


def test_verified_customer_supply_is_market_even_if_model_omitted_that_label(tmp_path):
    s = service(tmp_path)
    fact = {**finding('stakeholders'), 'text': '현대자동차와 LG전자 프로젝트에 데이터 공급사로 참여합니다.',
            'suitable_views': ['stakeholders', 'application']}
    catalog = s._catalog([{'task_id': 't', 'company_id': 'co-a', 'status': 'ok', 'findings': [fact]}])
    assert list(s._view_candidates(catalog, 'co-a', 'market')) == ['t:0']
    assert fact['suitable_views'] == ['stakeholders', 'application']


def test_generic_data_or_investor_funding_supply_is_not_a_market_fact(tmp_path):
    s = service(tmp_path)
    texts = [
        '트리닉스는 시뮬레이션용 3D 데이터를 공급합니다.',
        '투자자가 회사에 자금을 공급합니다.',
        '현대자동차와 LG전자에 학습 데이터를 공급합니다.',
        '현대자동차와 LG전자 프로젝트에 데이터 공급사로 참여합니다.',
    ]
    facts = [{**finding('application'), 'text': text, 'suitable_views': ['application']}
             for text in texts]
    catalog = s._catalog([{'task_id': 't', 'company_id': 'co-a', 'status': 'ok', 'findings': facts}])
    assert set(s._view_candidates(catalog, 'co-a', 'market')) == {'t:2', 't:3'}
    # 잘못된 모델 라벨도 일반 기능 설명을 시장 실적으로 바꾸지 않습니다.
    facts[0]['suitable_views'].append('market')
    assert not s._view_hint(facts[0], 'market')


def test_omitted_writer_slots_are_repaired_only_from_valid_candidates_and_audited(tmp_path):
    s = service(tmp_path, responses={'Research': research_response(), 'Report': {'selections': []}})
    state = complete_state(s)
    assert s._check(state) == []
    raw = json.loads((tmp_path / 'raw/report-0.json').read_text())
    assert raw['model_response']['selections'] == []
    assert len(raw['selections']) == len(raw['selection_repairs']) == 4
    empty = service(tmp_path / 'empty', corpus=MockCorpus(empty=True),
                    responses={'Report': {'selections': []}})
    no_evidence = complete_state(empty)
    assert any('적합한 사실 선택' in error for _, error in empty._check(no_evidence))


def test_missing_view_recovery_preserves_initial_rejection_and_new_review(tmp_path):
    class RecoveryRuntime(MockRuntime):
        def ask(self, schema, instructions, payload, **kwargs):
            if schema.__name__ == 'GroundingReview':
                self.calls.append({'schema': schema.__name__, 'payload': payload, **kwargs})
                if payload.get('recover_views'):
                    return {'checks': [grounding_check('고객 현장에서 로봇을 시험하고 있습니다.',
                                                      views=['technology'])]}
                return {'checks': [grounding_check('', supported=False, views=[])]}
            return super().ask(schema, instructions, payload, **kwargs)
    runtime = RecoveryRuntime({'Research': research_response([finding()])})
    s = LiveService(runtime, MockCorpus(), [COMPANY], tmp_path)
    worker = s.research({**TASK, 'views': ['technology']}, 0, '')
    assert worker['missing_views'] == [] and len(worker['findings']) == 1
    assert worker['findings'][0]['evidence'][0]['quote'] == QUOTE
    raw = json.loads(open(worker['raw_path'], encoding='utf-8').read())
    assert raw['grounding_review']['checks'][0]['supported'] is False
    assert raw['grounding_repair']['grounding_review']['checks'][0]['supported'] is True
    assert raw['grounding_repair']['accepted'][0]['evidence'][0]['quote'] == QUOTE
    assert raw['response']['findings'][0] == finding()
