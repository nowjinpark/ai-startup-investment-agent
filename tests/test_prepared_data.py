import hashlib
import json
from types import SimpleNamespace

import pytest
from pypdf import PdfWriter

import prepared_data
from agents import discovery
from common import save_json


def _pdf(path, pages=1):
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=595, height=842)
    with path.open('wb') as stream:
        writer.write(stream)


def _run(folder, names=('기업가', '기업나'), demo=False):
    source = {'source_id': 'S-1', 'company_id': '__discovery__', 'doc_type': 'company',
              'text': '기업가와 기업나의 로봇 기술 및 사업 소개 원문입니다.',
              'file': 'documents/source.pdf'}
    candidates = [{'company_id': f'co-{index}', 'name': name, 'source_ids': ['S-1']}
                  for index, name in enumerate(names)]
    _pdf(folder / 'corpus/documents/source.pdf')
    _pdf(folder / 'corpus/rag-documents.pdf')
    save_json(folder / 'corpus/sources.json', [source])
    save_json(folder / 'candidates.json', candidates)
    save_json(folder / 'excluded_candidates.json', [])
    save_json(folder / 'unresolved_candidates.json', [])
    save_json(folder / 'run_summary.json', {'demo': demo, 'page_count': 1})
    return candidates


def _read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def _update_hashes(cache):
    manifest = _read(cache / 'manifest.json')
    for name in ('corpus/sources.json', 'candidates.json'):
        manifest['hashes'][name] = hashlib.sha256((cache / name).read_bytes()).hexdigest()
    save_json(cache / 'manifest.json', manifest)


@pytest.fixture
def environment(monkeypatch, tmp_path):
    config = {'domain': '국내 Physical AI', 'max_candidates': 20, 'refresh_data': False}
    save_json(tmp_path / 'config/settings.json', config)
    monkeypatch.setattr(prepared_data, 'ROOT', tmp_path)
    corpus_calls = []

    def fake_corpus(sources, settings, cache):
        corpus_calls.append(sources)
        return SimpleNamespace(sources=sources, history=[])

    def no_api(*args, **kwargs):
        raise AssertionError('저장 자료 재사용 중 API 또는 새 수집을 호출했습니다.')

    def runtime(name, **updates):
        return SimpleNamespace(config={**config, **updates}, output_dir=tmp_path / 'output' / name,
                               corpus=None, ask=no_api, search=no_api)

    monkeypatch.setattr(prepared_data, 'Corpus', fake_corpus)
    monkeypatch.setattr(discovery, 'run', no_api)
    return SimpleNamespace(root=tmp_path, runtime=runtime, corpus_calls=corpus_calls, config=config)


def _store(environment, names=('기업가', '기업나')):
    folder = environment.root / 'original'
    candidates = _run(folder, names)
    cache = prepared_data.store_prepared(folder, prepared_data.DEFAULT_REQUEST)
    return cache, candidates


def test_saved_documents_and_candidates_are_reused_without_collection(environment):
    cache, candidates = _store(environment)
    runtime = environment.runtime('reuse')
    result = prepared_data.prepare(runtime, '  ' + prepared_data.DEFAULT_REQUEST + '\n')
    assert result['candidate_list'] == candidates
    assert result['doc_pages'] == 1
    assert result['prepared']['reused'] is True
    assert len(environment.corpus_calls) == 1
    assert (runtime.output_dir / 'corpus/rag-documents.pdf').read_bytes() == (cache / 'corpus/rag-documents.pdf').read_bytes()
    log = _read(runtime.output_dir / 'preparation_reuse.json')
    assert log['collection_api_calls'] == log['web_searches'] == log['new_pages'] == 0


@pytest.mark.parametrize('limit, expected', [(1, 1), (20, 2)])
def test_candidate_limit_only_truncates_without_filling_missing_candidates(environment, limit, expected):
    cache, candidates = _store(environment)
    runtime = environment.runtime('limited', max_candidates=limit)
    result = prepared_data.prepare(runtime, prepared_data.DEFAULT_REQUEST)
    assert result['candidate_list'] == candidates[:expected]
    assert result['doc_pages'] == 1
    assert len(_read(cache / 'candidates.json')) == 2


def test_first_collection_is_saved_and_second_run_reuses_it(environment, monkeypatch):
    calls = []

    def collect(runtime, request):
        calls.append(request)
        candidates = _run(runtime.output_dir)
        return {'candidate_list': candidates, 'doc_pages': 1, 'page_cap': 200, 'prepared': {}}

    monkeypatch.setattr(discovery, 'run', collect)
    prepared_data.prepare(environment.runtime('first'), prepared_data.DEFAULT_REQUEST)
    second = prepared_data.prepare(environment.runtime('second'), prepared_data.DEFAULT_REQUEST)
    assert calls == [prepared_data.DEFAULT_REQUEST]
    assert second['prepared']['reused'] is True


def test_explicit_refresh_replaces_cache_and_preserves_previous_snapshot(environment, monkeypatch):
    cache, old_candidates = _store(environment)
    calls = []

    def collect(runtime, request):
        calls.append(request)
        candidates = _run(runtime.output_dir, names=('새기업',))
        return {'candidate_list': candidates, 'doc_pages': 1, 'page_cap': 200, 'prepared': {}}

    monkeypatch.setattr(discovery, 'run', collect)
    result = prepared_data.prepare(environment.runtime('refresh', refresh_data=True), prepared_data.DEFAULT_REQUEST)
    assert len(calls) == 1
    assert result['candidate_list'][0]['name'] == '새기업'
    assert _read(cache / 'candidates.json')[0]['name'] == '새기업'
    backups = list((environment.root / 'data/prepared-backups').iterdir())
    assert len(backups) == 1
    assert _read(backups[0] / 'candidates.json') == old_candidates


def test_failed_refresh_preserves_valid_previous_snapshot(environment, monkeypatch):
    cache, candidates = _store(environment)
    manifest = (cache / 'manifest.json').read_bytes()

    def failed_collection(runtime, request):
        raise RuntimeError('자료 수집 중단')

    monkeypatch.setattr(discovery, 'run', failed_collection)
    with pytest.raises(RuntimeError, match='자료 수집 중단'):
        prepared_data.prepare(environment.runtime('failed', refresh_data=True), prepared_data.DEFAULT_REQUEST)
    assert (cache / 'manifest.json').read_bytes() == manifest
    assert _read(cache / 'candidates.json') == candidates


@pytest.mark.parametrize('field,value', [
    ('complete', False), ('demo', True), ('version', 2),
    ('request', '다른 분야'), ('domain', '국외 바이오'),
    ('page_count', 2), ('candidate_count', 3),
])
def test_invalid_or_different_manifest_never_triggers_paid_fallback(environment, field, value):
    cache, _ = _store(environment)
    manifest = _read(cache / 'manifest.json')
    manifest[field] = value
    save_json(cache / 'manifest.json', manifest)
    with pytest.raises(ValueError, match='자동 재수집하지 않습니다'):
        prepared_data.prepare(environment.runtime('bad'), prepared_data.DEFAULT_REQUEST)
    assert environment.corpus_calls == []


@pytest.mark.parametrize('corruption', ['json', 'hash', 'source_missing', 'pdf_pages', 'pdf_corrupt',
                                       'duplicate_source', 'duplicate_company', 'unknown_source', 'over_limit'])
def test_corrupt_documents_never_trigger_paid_fallback(environment, corruption):
    cache, _ = _store(environment)
    if corruption == 'json':
        (cache / 'manifest.json').write_text('{', encoding='utf-8')
    elif corruption == 'hash':
        (cache / 'candidates.json').write_text('[]', encoding='utf-8')
    elif corruption == 'source_missing':
        (cache / 'corpus/documents/source.pdf').unlink()
    elif corruption == 'pdf_pages':
        _pdf(cache / 'corpus/rag-documents.pdf', pages=2)
    elif corruption == 'pdf_corrupt':
        (cache / 'corpus/rag-documents.pdf').write_bytes(b'not a PDF')
    else:
        sources = _read(cache / 'corpus/sources.json')
        candidates = _read(cache / 'candidates.json')
        if corruption == 'duplicate_source':
            sources.append(sources[0])
        elif corruption == 'duplicate_company':
            candidates.append(candidates[0])
        elif corruption == 'unknown_source':
            candidates[0]['source_ids'] = ['S-not-found']
        elif corruption == 'over_limit':
            sources = [{**sources[0], 'source_id': f'S-{i}'} for i in range(201)]
        save_json(cache / 'corpus/sources.json', sources)
        save_json(cache / 'candidates.json', candidates)
        _update_hashes(cache)
    with pytest.raises(ValueError, match='자동 재수집하지 않습니다'):
        prepared_data.prepare(environment.runtime('bad'), prepared_data.DEFAULT_REQUEST)
    assert environment.corpus_calls == []


def test_demo_result_cannot_be_stored_as_real_prepared_documents(environment):
    folder = environment.root / 'demo'
    _run(folder, demo=True)
    with pytest.raises(ValueError, match='가상 예제'):
        prepared_data.store_prepared(folder, prepared_data.DEFAULT_REQUEST)
    assert not (environment.root / 'data/prepared').exists()


def test_individual_discovery_uses_the_same_saved_documents(environment, monkeypatch):
    import run_agent
    _, candidates = _store(environment)

    def runtime(config, output):
        instance = environment.runtime('unused')
        instance.config, instance.output_dir = config, output
        return instance

    folder = environment.root / 'individual'
    monkeypatch.setattr(run_agent, 'Runtime', runtime)
    monkeypatch.setattr(run_agent, 'settings', lambda: dict(environment.config))
    monkeypatch.setattr('sys.argv', ['run_agent.py', 'discovery', '--run', str(folder)])
    run_agent.main()
    result = _read(folder / 'part-discovery/result.json')
    assert result['candidate_list'] == candidates
    assert result['prepared']['reused'] is True


def test_live_entrypoint_prepares_from_cache_by_default(environment, monkeypatch):
    import main
    import workflow
    _, candidates = _store(environment)

    def runtime(config, output):
        instance = environment.runtime('unused')
        instance.config, instance.output_dir = config, output
        return instance

    def graph(runtime):
        def stream(state, **kwargs):
            prepared = runtime.prepare(state['request'])
            yield {'discovery': {**prepared, 'records': [], 'passed_records': [],
                                 'report': {'pdf_path': 'cached-report.pdf'}}}
        return SimpleNamespace(stream=stream,
            get_graph=lambda: SimpleNamespace(draw_mermaid=lambda: 'graph TD'))

    output = environment.root / 'entrypoint'
    monkeypatch.setattr(main, 'Runtime', runtime)
    monkeypatch.setattr(main, 'settings', lambda: dict(environment.config))
    monkeypatch.setattr(workflow, 'build_graph', graph)
    monkeypatch.setattr('sys.argv', ['main.py', 'live', '--output', str(output)])
    main.main()
    result = _read(output / 'state.json')
    assert result['candidate_list'] == candidates
    assert result['prepared']['reused'] is True


@pytest.mark.parametrize('arguments', [
    ['demo', '--refresh-data'], ['report', '--refresh-data'],
    ['live', '--refresh-data', '--resume-from', 'old'],
    ['live', '--refresh-data', '--reuse-corpus', 'old'],
])
def test_main_rejects_conflicting_refresh_options(monkeypatch, arguments):
    import main
    monkeypatch.setattr('sys.argv', ['main.py', *arguments])
    with pytest.raises(SystemExit) as error:
        main.main()
    assert error.value.code == 2


@pytest.mark.parametrize('arguments', [
    ['discovery', '--demo', '--refresh-data'], ['technology', '--refresh-data'],
])
def test_individual_run_rejects_conflicting_refresh_options(monkeypatch, arguments):
    import run_agent
    monkeypatch.setattr('sys.argv', ['run_agent.py', *arguments])
    with pytest.raises(SystemExit) as error:
        run_agent.main()
    assert error.value.code == 2
