import json
import time
from copy import deepcopy
from types import SimpleNamespace

import pytest

from agents import discovery
from common import settings


def source(name, role='company', owner=None, text=None, source_id=None):
    return {'source_id': source_id or 's-' + name, 'company_id': owner or discovery.company_id(name),
            'doc_type': role, 'doc_types': [role], 'title': name + ' 기업 소개', 'url': 'https://example.com/' + name,
            'text': text or f'{name}은 국내 자율주행 로봇을 개발하며 제조 현장 고객에게 제품을 공급합니다.'}


def hint(name, src=None):
    src = src or source(name, owner='__discovery__')
    return {'name': name, 'aliases': [], 'website': '', 'overview': src['text'],
            'evidence': [{'source_id': src['source_id'], 'quote': src['text']}]}


def unknown_result(_):
    return {'identity': discovery._unknown('동일 법인 확인 필요'),
            'eligibility': discovery._unknown_eligibility('추가 확인 필요'),
            'operating': discovery._unknown('현재 운영 확인 필요')}


def case(monkeypatch, tmp_path, seed_sources, extract, qualify=unknown_result, additions=None, own_by_name=None, max_candidates=20):
    queries, calls = [], []
    registry = {'seed_urls': [], 'common_sources': [],
                'discovery_queries': [{'query': '분야 ' + str(i)} for i in range(6)]}
    (tmp_path / 'config').mkdir()
    (tmp_path / 'config/sources.json').write_text(json.dumps(registry))
    monkeypatch.setattr(discovery, 'ROOT', tmp_path)

    class Collector:
        def __init__(self, *_):
            self.sources, self.errors = deepcopy(seed_sources), []
            self.per_source = 8

        @property
        def page_count(self):
            return len(self.sources)

        def collect(self, url, owner, role, **_):
            item = deepcopy((additions or {}).get(url))
            if item and item['source_id'] not in {s['source_id'] for s in self.sources}:
                self.sources.append(item)
                return [item]
            return []

        def links(self, *_args, **_kwargs):
            return []

        def export_pdf(self):
            return tmp_path / 'corpus/rag-documents.pdf'

        def _error(self, *args):
            self.errors.append(args)

    class Corpus:
        def __init__(self, runtime):
            self.runtime, self.history = runtime, []

        def evidence_for(self, queries, company_id, doc_type):
            assert doc_type is None  # 자격 확인은 역할에 관계없이 회사 자료 전체입니다.
            self.history.append({'question': queries[0], 'company_id': company_id, 'doc_type': doc_type})
            return discovery._own_sources(self.runtime, company_id)

        def source_pages(self, chunks):
            return chunks

    def ask(schema, instructions, payload):
        calls.append((schema.__name__, payload))
        if schema.__name__ == 'CandidateHints':
            return {'companies': extract(payload)}
        if schema.__name__ == 'EligibilityResult':
            return qualify(payload)
        return {'checks': [{'criterion_id': f['criterion_id'], 'supported': True, 'reason': '직접 근거 확인'} for f in payload['findings']]}

    def search(query, domains=None):
        queries.append(query)
        return [{'url': url, 'title': '추가 기업'} for url in (additions or {})] if query == '분야 0' else []

    def prepare(runtime, candidate, quota):
        name = candidate['name']
        own = deepcopy(own_by_name.get(name, []) if own_by_name is not None else [source(name, source_id='own-' + name)])
        runtime.collector.sources.extend(own[:quota])
        return own[:quota]

    monkeypatch.setattr(discovery, 'Collector', Collector)
    monkeypatch.setattr(discovery, '_add_local', lambda _: None)
    monkeypatch.setattr(discovery, '_prepare_company', prepare)
    monkeypatch.setattr(discovery, '_index', lambda rt: setattr(rt, 'corpus', Corpus(rt)))
    config = {**settings(), 'max_candidates': max_candidates, 'candidate_no_new_rounds': 3}
    runtime = SimpleNamespace(config=config, output_dir=tmp_path, corpus=None, ask=ask, search=search)
    output = discovery.run(runtime, '국내 Physical AI 로봇')
    return output, runtime, calls, queries


def test_reads_all_batches_and_reaches_twenty_beyond_first_eight_chunks(monkeypatch, tmp_path):
    seeds = [source(f'제어{i}로봇', owner='__discovery__') for i in range(20)]
    output, runtime, calls, _ = case(monkeypatch, tmp_path, seeds,
        lambda p: [hint(s['title'].removesuffix(' 기업 소개'), s) for s in p['sources']])
    assert len(output['candidate_list']) == 20
    assert output['candidate_list'][-1]['name'] == '제어19로봇'
    batches = json.loads((tmp_path / 'candidate_extraction_raw.json').read_text())
    assert len(batches) == 10
    assert {sid for b in batches for sid in b['source_ids']} == {s['source_id'] for s in seeds}
    assert runtime.discovery['stop_reason'] == 'candidate_target_reached'
    assert len([c for c in calls if c[0] == 'CandidateHints']) == 10
    assert output['doc_pages'] <= 200


def test_replenishes_missing_company_and_saves_raw_rejections(monkeypatch, tmp_path):
    first = source('가나로봇', owner='__discovery__')
    later = source('다라로봇', owner='__discovery__')

    def extract(p):
        name = '가나로봇' if p['sources'][0]['source_id'] == first['source_id'] else '다라로봇'
        valid = hint(name, p['sources'][0])
        invalid = {**valid, 'name': '없는기업', 'aliases': []}
        return [valid, invalid]

    out, rt, _, queries = case(monkeypatch, tmp_path, [first], extract,
        additions={'https://example.com/new': later}, own_by_name={'가나로봇': [], '다라로봇': [source('다라로봇')]}, max_candidates=1)
    assert [c['name'] for c in out['candidate_list']] == ['다라로봇']
    assert len(out['prepared']['unresolved']) == 1
    assert out['prepared']['unresolved'][0]['name'] == '가나로봇'
    assert not out['prepared']['excluded']
    assert queries == ['분야 0']
    raw = json.loads((tmp_path / 'candidate_extraction_raw.json').read_text())
    assert raw[0]['rejected'][0]['reason'] == 'invalid_company_quote'


def test_no_new_rounds_stops_and_ask_failure_does_not_stop_next_company(monkeypatch, tmp_path):
    seeds = [source(n, owner='__discovery__') for n in ['가나로봇', '다라로봇']]

    def answer(payload):
        if payload['company'] == '가나로봇':
            raise TimeoutError('do not expose response details')
        return unknown_result(payload)

    out, rt, _, queries = case(monkeypatch, tmp_path, seeds,
        lambda p: [hint(s['title'].removesuffix(' 기업 소개'), s) for s in p['sources']], answer)
    assert len(out['candidate_list']) == 2
    assert 'TimeoutError' in out['candidate_list'][0]['identity']['reason']
    assert 'do not expose' not in str(out)
    assert queries == ['분야 0', '분야 1', '분야 2']
    assert rt.discovery['stop_reason'] == 'no_new_candidates'


def qualification_runtime(tmp_path, candidate, sources, response, review=None):
    calls = []

    def ask(schema, instructions, payload):
        calls.append((schema.__name__, payload))
        if schema.__name__ == 'EligibilityResult':
            return deepcopy(response)
        return {'checks': [{'criterion_id': f['criterion_id'], 'supported': review(f) if review else True,
                            'reason': '사업 설명 상충' if f['criterion_id'] == 1 else '근거 확인'} for f in payload['findings']]}

    class Corpus:
        def evidence_for(self, _, cid, role):
            assert cid == candidate['company_id'] and role is None
            return [s for s in sources if s['company_id'] == cid]

        def source_pages(self, chunks):
            return chunks

    return SimpleNamespace(collector=SimpleNamespace(sources=sources, _error=lambda *a: None),
                           corpus=Corpus(), ask=ask, output_dir=tmp_path), calls


def direct_candidate(name, text=None):
    initial = source(name, owner='__discovery__', source_id='initial', text=text)
    return {**hint(name, initial), 'company_id': discovery.company_id(name), 'source_ids': ['initial']}, initial


@pytest.mark.parametrize('name,text,field', [
    ('링크솔루션', '주식회사 링크솔루션은 코스닥 상장법인입니다. 2025년 6월 코스닥 시장 상장. 국내 로봇 관련 제조 기술을 개발합니다.', 'unlisted'),
    ('플로틱', '주식회사 플로틱(Floatic)은 2021년 6월에 설립되고, 2026년 1월에 폐업한 한국계 스타트업입니다.', 'operating'),
])
def test_explicit_listing_and_closure_override_model_misclassification(tmp_path, name, text, field):
    candidate, initial = direct_candidate(name)
    actual = source(name, 'market', text=text)
    response = unknown_result({})
    item = response['eligibility']['unlisted'] if field == 'unlisted' else response['operating']
    item.update(status='pass', reason='검색되지 않아 추정', evidence=[{'source_id': actual['source_id'], 'quote': text}])
    rt, _ = qualification_runtime(tmp_path, candidate, [initial, actual], response)
    result = discovery._qualify(rt, candidate)
    checked = result['eligibility']['unlisted'] if field == 'unlisted' else result['operating']
    assert checked['status'] == 'fail'
    assert checked['evidence'][0]['source_id'] == actual['source_id']


def test_teamrobotics_identity_conflict_uses_market_and_technology_documents(tmp_path):
    candidate, initial = direct_candidate('팀로보틱스', '팀로보틱스는 AI 의복형 착용 로봇을 개발합니다.')
    tech = source('팀로보틱스', 'technology', text='팀로보틱스는 AI 기반 산업용 자율 로봇 지게차를 개발합니다. 대표자는 백승민입니다.')
    market = source('팀로보틱스', 'market', source_id='market', text='팀로보틱스의 산업용 지게차는 자율주행 기술로 공장 운송을 자동화합니다.')
    response = unknown_result({})
    response['identity'] = {'status': 'pass', 'reason': '이름 일치', 'evidence': [{'source_id': tech['source_id'], 'quote': tech['text']}]}
    for key in ['domestic', 'physical_ai']:
        response['eligibility'][key] = deepcopy(response['identity'])
    rt, calls = qualification_runtime(tmp_path, candidate, [initial, tech, market], response, lambda f: f['criterion_id'] != 1)
    out = discovery._qualify(rt, candidate)
    assert {s['source_id'] for s in calls[0][1]['sources']} == {'initial', tech['source_id'], 'market'}
    assert out['identity']['status'] == 'unknown'
    assert out['eligibility']['physical_ai']['status'] == 'unknown'
    assert out['eligibility']['domestic']['status'] == 'unknown'


def test_initial_quote_alone_cannot_prove_same_company(tmp_path):
    candidate, initial = direct_candidate('가나로봇')
    response = unknown_result({})
    response['identity'] = {'status': 'pass', 'reason': '이름 같음', 'evidence': candidate['evidence']}
    rt, _ = qualification_runtime(tmp_path, candidate, [initial], response)
    assert discovery._qualify(rt, candidate)['identity']['status'] == 'unknown'


def test_listing_across_rendered_line_break_overrides_unknown_review(tmp_path):
    candidate, initial = direct_candidate('티로보틱스')
    text = '티로보틱스는 산업용 로봇과 물류자동화 솔루션을 개발하는 국내 로봇 전문기업이다. 2004년 설립돼 2018년 코스닥\n시장에 상장했다. 주요 사업은 물류이송용 로봇 공급이다.'
    actual = source('티로보틱스', 'technology', text=text, source_id='listing')
    response = unknown_result({})
    response['eligibility']['unlisted'] = {'status': 'fail', 'reason': '상장 완료',
        'evidence': [{'source_id': 'listing', 'quote': text}]}
    rt, _ = qualification_runtime(tmp_path, candidate, [initial, actual], response, lambda _: False)
    result = discovery._qualify(rt, candidate)['eligibility']['unlisted']
    assert result['status'] == 'fail'
    assert result['evidence'][0]['source_id'] == 'listing'
    assert result['evidence'][0]['quote'] in text


@pytest.mark.parametrize('text', [
    '가나로봇은 코스닥 상장을 준비합니다. 2027년 코스닥 상장 예정입니다.',
    '가나로봇은 2027년 코스닥\n시장 상장 예정이다.',
    '가나로봇은 기업의 폐업 방지 솔루션을 개발합니다.',
    '다른기업은 2026년 1월에 폐업한 회사입니다.',
])
def test_future_listing_and_other_company_are_not_completed_events(text):
    candidate, _ = direct_candidate('가나로봇')
    assert not discovery._explicit_status(candidate, [source('기사', text=text)])


@pytest.mark.parametrize('text', [
    '가나로봇은 로봇을 개발한다. 투자사 다나기업은 코스닥 상장기업이다.',
    '가나로봇은 영업을 지속한다. 고객사 다나기업은 2026년 폐업한 회사다.',
    '가나로봇이 협력하는 투자사는 코스닥 상장기업이다.',
])
def test_same_article_other_company_status_is_not_candidate_status(text):
    candidate, _ = direct_candidate('가나로봇')
    assert not discovery._explicit_status(candidate, [source('가나로봇', text=text)])


def test_company_search_is_bounded_and_zero_corpus_is_visible(tmp_path):
    queries = []
    candidate, _ = direct_candidate('가나로봇')
    collector = SimpleNamespace(sources=[], page_count=0, per_source=8, collect=lambda *a, **kw: [],
                                _error=lambda *a: None, links=lambda *a, **kw: [])
    rt = SimpleNamespace(config=settings(), collector=collector, candidate_names={}, output_dir=tmp_path,
                         preparation_started=time.monotonic(), discovery={'queries': [], 'coverage': {}},
                         search=lambda q, d=None: queries.append(q) or [])
    assert discovery._prepare_company(rt, candidate, 9) == []
    assert len(queries) == 5
    assert len(set(queries)) == 5
    assert rt.discovery['coverage'][candidate['company_id']]['unique_pages'] == 0


def test_verified_reopening_after_closure_is_not_overridden(tmp_path):
    candidate, initial = direct_candidate('가나로봇')
    closed = source('가나로봇', text='가나로봇은 2025년 1월 20일에 폐업한 회사입니다.', source_id='closed')
    reopened = source('가나로봇', text='가나로봇은 2026년 3월 1일 영업을 재개했습니다. 자율주행 로봇을 공급합니다.', source_id='reopened')
    response = unknown_result({})
    response['operating'] = {'status': 'pass', 'reason': '폐업 이후 영업 재개 확인',
                             'evidence': [{'source_id': 'reopened', 'quote': reopened['text']}]}
    rt, _ = qualification_runtime(tmp_path, candidate, [initial, closed, reopened], response)
    assert discovery._qualify(rt, candidate)['operating']['status'] == 'pass'


def test_company_heading_and_body_are_anchored_without_rewriting():
    text = '다른기업\n상세내용 닫기\n로보아르테\n조리 자동화 로봇\n#Series A\nShare\n튀김 요리를 자동화한 협동로봇 솔루션을 개발했습니다.'
    src = source('자료', owner='__discovery__', text=text)
    entry = {'name': '로보아르테', 'aliases': [], 'evidence': [{'source_id': src['source_id'], 'quote': '튀김 요리를 자동화한 협동로봇 솔루션을 개발했습니다.'}]}
    evidence = discovery._candidate_evidence(entry, [src])
    assert evidence == [{'source_id': src['source_id'], 'quote': text[text.index('로보아르테'):]}]
    assert discovery.valid_evidence(evidence, [src])
    assert discovery._has_domain_description(evidence, ['로보아르테'])


def test_adjacent_rendered_pages_preserve_separate_literal_quotes():
    a = source('앞쪽', owner='__discovery__', text='상세내용 닫기\n실시간 로봇 모션캡처\n#Seed\n무빈', source_id='page1')
    b = source('뒷쪽', owner='__discovery__', text='실시간 로봇 모션캡처\n#Seed\nLiDAR 센서로 로봇 기술을 개발했습니다.', source_id='page2')
    a.update(url='https://example.com/list', rendered_page=1)
    b.update(url=a['url'], rendered_page=2)
    entry = {'name': '무빈', 'aliases': [], 'evidence': [{'source_id': 'page2', 'quote': 'LiDAR 센서로 로봇 기술을 개발했습니다.'}]}
    evidence = discovery._candidate_evidence(entry, [a, b])
    assert len(evidence) == 2
    assert discovery.valid_evidence(evidence, [a, b])
    assert all(e['quote'] in {'page1': a['text'], 'page2': b['text']}[e['source_id']] for e in evidence)


@pytest.mark.parametrize('separator', ['상세내용 닫기\n다른기업', '다른기업'])
def test_anchor_never_crosses_another_company_card(separator):
    src = source('자료', owner='__discovery__', text=f'가나로봇\n제목\n{separator}\n자율주행 로봇을 개발했습니다.')
    entry = {'name': '가나로봇', 'aliases': [], 'evidence': [{'source_id': src['source_id'], 'quote': '자율주행 로봇을 개발했습니다.'}]}
    assert discovery._candidate_evidence(entry, [src], ['가나로봇', '다른기업']) == []


def test_punctuation_difference_is_not_repaired_by_guessing():
    src = source('자료', owner='__discovery__', text='비욘드허니컴\n콜라겐·지방 상태를 분석하는 조리로봇 솔루션을 개발했습니다.')
    entry = {'name': '비욘드허니컴', 'aliases': [], 'evidence': [{'source_id': src['source_id'], 'quote': '콜라겐 지방 상태를 분석하는 조리로봇 솔루션을 개발했습니다.'}]}
    assert discovery._candidate_evidence(entry, [src]) == []


def test_robotics_in_name_does_not_prove_domain():
    assert not discovery._has_domain_description([{'quote': 'From one act of trust, a global stage emerged Lee HanBin SeoulRobotics'}], ['SeoulRobotics'])


def test_qualification_can_anchor_stage_field_to_same_company_heading(tmp_path):
    candidate, initial = direct_candidate('가나로봇', '가나로봇\n자율주행 로봇 개발\nFounder\n홍길동\nLatest Funded\nSeries A, 2026')
    own = source('가나로봇')
    response = unknown_result({})
    response['eligibility']['stage'] = {'status': 'pass', 'reason': 'Series A 확인', 'evidence': [{'source_id': 'initial', 'quote': 'Latest Funded\nSeries A, 2026'}]}
    rt, _ = qualification_runtime(tmp_path, candidate, [initial, own], response)
    actual = discovery._qualify(rt, candidate)['eligibility']['stage']
    assert actual['status'] == 'pass'
    assert actual['evidence'][0]['quote'] == initial['text']


@pytest.mark.parametrize('key,reason', [
    ('no_exit', '인수나 상장 완료에 대한 정보가 없으며 현재 투자유치 중입니다.'),
    ('unlisted', 'Series A 기업이며 상장 완료 정보가 없습니다.'),
    ('no_exit', '독립 기업으로 추정됩니다.'),
    ('unlisted', '상장 여부의 검색 결과가 확인되지 않았습니다.'),
])
def test_absence_or_speculation_cannot_confirm_eligibility(tmp_path, key, reason):
    candidate, initial = direct_candidate('가나로봇')
    own = source('가나로봇')
    response = unknown_result({})
    response['eligibility'][key] = {'status': 'pass', 'reason': reason,
        'evidence': [{'source_id': own['source_id'], 'quote': own['text']}]}
    runtime, calls = qualification_runtime(tmp_path, candidate, [initial, own], response)
    result = discovery._qualify(runtime, candidate)['eligibility'][key]
    assert result['status'] == 'unknown'
    assert not result['evidence']
    # 검수 모델이 모두 supported=true로 응답해도 부재 추정을 되살리지 않습니다.
    assert not any(c[0] == 'EvidenceReview' for c in calls)


def test_direct_unlisted_statement_and_foreign_fail_are_preserved(tmp_path):
    candidate, initial = direct_candidate('가나로봇')
    own = source('가나로봇', text='가나로봇은 미국 본사에서 자율주행 로봇을 개발하는 비상장 기업입니다.')
    proof = [{'source_id': own['source_id'], 'quote': own['text']}]
    response = unknown_result({})
    response['identity'] = {'status': 'pass', 'reason': '법인과 사업 일치', 'evidence': proof}
    response['eligibility']['unlisted'] = {'status': 'pass', 'reason': '비상장 기업으로 명시', 'evidence': proof}
    response['eligibility']['domestic'] = {'status': 'fail', 'reason': '미국 본사로 명시', 'evidence': proof}
    runtime, _ = qualification_runtime(tmp_path, candidate, [initial, own], response)
    result = discovery._qualify(runtime, candidate)
    assert result['eligibility']['unlisted']['status'] == 'pass'
    assert result['eligibility']['domestic']['status'] == 'fail'


def test_requalify_uses_saved_sources_without_search_or_collection(monkeypatch, tmp_path):
    candidates, sources = [], []
    for name in ['가나로봇', '플로틱', '원문없는로봇']:
        candidate, initial = direct_candidate(name)
        initial['source_id'] = 'initial-' + name
        candidate['source_ids'] = [initial['source_id']]
        candidate['evidence'][0]['source_id'] = initial['source_id']
        candidates.append(candidate)
        sources.append(initial)
        if name != '원문없는로봇':
            text = '플로틱은 2026년 1월에 폐업한 회사입니다.' if name == '플로틱' else None
            sources.append(source(name, text=text))

    def forbidden(*args, **kwargs):
        pytest.fail('자격 재검증 중 웹 검색·자료 수집을 하면 안 됩니다.')

    collector = SimpleNamespace(sources=sources, errors=[{'code': 'old_error'}], page_count=len(sources),
        _error=lambda *args: None, collect=forbidden, export_pdf=lambda: tmp_path / 'corpus/rag-documents.pdf')
    corpus = SimpleNamespace(history=[], evidence_for=lambda queries, cid, role: [s for s in sources if s['company_id'] == cid],
        source_pages=lambda chunks: chunks)
    monkeypatch.setattr(discovery, 'Collector', lambda *args: collector)
    monkeypatch.setattr(discovery, '_index', lambda runtime: setattr(runtime, 'corpus', corpus))
    calls = []

    def ask(schema, instructions, payload):
        calls.append(schema.__name__)
        assert schema.__name__ == 'EligibilityResult'
        return unknown_result(payload)

    runtime = SimpleNamespace(config=settings(), output_dir=tmp_path, corpus=None, search=forbidden, ask=ask)
    accepted, excluded = discovery.requalify(runtime, candidates)
    assert [c['name'] for c in accepted] == ['가나로봇']
    assert [c['name'] for c in excluded] == ['플로틱']
    assert len(calls) == 2
    unresolved = json.loads((tmp_path / 'unresolved_candidates.json').read_text())
    assert [c['name'] for c in unresolved] == ['원문없는로봇']
    report = json.loads((tmp_path / 'requalification.json').read_text())
    assert report['new_pages'] == report['web_searches'] == 0
    assert report['page_count'] == len(sources)
