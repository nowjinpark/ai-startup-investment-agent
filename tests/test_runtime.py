import json
import threading

import pytest

from common import BudgetExceeded, Runtime, compact, valid_evidence


def runtime(tmp_path, limit=0.10):
    r = object.__new__(Runtime)
    r.output_dir = tmp_path
    r._lock = threading.Lock()
    r.spent_usd = r.reserved_usd = 0.0
    r.cost_limit = limit
    return r


def test_parallel_requests_cannot_reserve_more_than_budget(tmp_path):
    r = runtime(tmp_path)
    r._reserve(0.06)
    with pytest.raises(BudgetExceeded):
        r._reserve(0.05)
    r._settle(0.06, 0.02)
    r._reserve(0.07)
    r._settle(0.07)
    assert r.spent_usd == pytest.approx(0.09)
    assert json.loads((tmp_path / 'cost.json').read_text())['reserved_usd'] == 0


def test_pdf_word_wrap_uses_same_evidence_rule():
    source = {'source_id': 'x', 'text': '기업의 사업모\n델은 로봇을 월 단위로 임대하는 방식입니다.'}
    quote = '기업의 사업모델은 로봇을 월 단위로 임대하는 방식입니다.'
    assert valid_evidence([{'source_id': 'x', 'quote': quote}], [source])
    assert compact(source['text']) == compact(quote)
    assert not valid_evidence([{'source_id': 'x', 'quote': quote.replace('임대', '판매')}], [source])


def test_separate_sentences_cannot_be_spliced_into_quote():
    source = {'source_id': 'x', 'text': '고객은 두 곳입니다. 두 곳 모두 무료 실증입니다. 계약은 없습니다.'}
    assert not valid_evidence([{'source_id': 'x', 'quote': '고객은 두 곳입니다. 계약은 없습니다.'}], [source])


def test_evidence_ids_preserve_exact_text_and_source_scope():
    from common import evidence_segments, resolve_segments, compact
    text = '기업 가\n' + ('로봇 제어 기술을 고객 현장에서 검증했습니다.\n' * 35)
    original = {'sources': [{'source_id': 'S-one', 'text': text}, {'source_id': 'S-two', 'text': '다른 기업의 원문입니다.'}]}
    prepared, units = evidence_segments(original)
    assert original['sources'][0]['text'] == text
    assert 'text' not in prepared['sources'][0]
    assert all(compact(u['quote']) in compact(original['sources'][0 if u['source_id'] == 'S-one' else 1]['text']) for u in units.values())
    key = next(iter(units))
    resolved = resolve_segments({'evidence': [{'source_id': 'S-one', 'quote': key}]}, units)
    assert resolved['evidence'][0]['quote'] == units[key]['quote']
    wrong = {'source_id': 'S-two', 'quote': key}
    assert resolve_segments(wrong, units) == wrong
    unknown = {'source_id': 'S-one', 'quote': 'S-one:U999'}
    assert resolve_segments(unknown, units) == unknown


def fake_llm_runtime(monkeypatch, tmp_path, outcomes, limit=1):
    from types import SimpleNamespace
    from pydantic import BaseModel
    import langchain_core.prompts
    import langchain_openai
    from common import settings

    class Output(BaseModel):
        value: str

    calls = []

    class Chain:
        def __or__(self, other):
            return self

        def invoke(self, inputs):
            calls.append(inputs)
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    limits = []

    def llm(**kwargs):
        limits.append(kwargs['max_tokens'])
        return SimpleNamespace(with_structured_output=lambda *a, **kw: None)

    monkeypatch.setenv('OPENAI_API_KEY', 'offline-test-placeholder')
    monkeypatch.setattr(langchain_openai, 'ChatOpenAI', llm)
    monkeypatch.setattr(langchain_core.prompts.ChatPromptTemplate, 'from_messages', lambda *a: Chain())
    success = {'raw': SimpleNamespace(usage_metadata={'input_tokens': 100, 'output_tokens': 50}),
               'parsed': Output(value='ok'), 'parsing_error': None}
    return Runtime({**settings(), 'max_cost_usd': limit}, tmp_path), Output, calls, limits, success


def test_truncation_retries_once_with_new_budget_reservation(monkeypatch, tmp_path):
    error = type('LengthFinishReasonError', (Exception,), {})('private prompt must not be logged')
    outcomes = [error]
    rt, schema, calls, limits, success = fake_llm_runtime(monkeypatch, tmp_path, outcomes)
    outcomes.append(success)
    assert rt.ask(schema, 'instruction', {}, max_tokens=4096) == {'value': 'ok'}
    assert len(calls) == 2 and limits == [4096, 8192]
    assert rt.reserved_usd == 0 and rt.spent_usd > 4096 * 1.6e-6
    errors = (tmp_path / 'llm_errors.json').read_text()
    assert 'response_truncated' in errors and 'private prompt' not in errors


def test_second_truncation_stops_without_third_request(monkeypatch, tmp_path):
    error = type('LengthFinishReasonError', (Exception,), {})()
    rt, schema, calls, limits, _ = fake_llm_runtime(monkeypatch, tmp_path, [error, error])
    with pytest.raises(type(error)):
        rt.ask(schema, '', {}, max_tokens=6144)
    assert len(calls) == 2 and limits == [6144, 12288]
    assert rt.reserved_usd == 0
    assert len(json.loads((tmp_path / 'llm_errors.json').read_text())) == 2


def test_retry_is_blocked_when_second_reservation_would_exceed_budget(monkeypatch, tmp_path):
    error = type('LengthFinishReasonError', (Exception,), {})()
    rt, schema, calls, _, _ = fake_llm_runtime(monkeypatch, tmp_path, [error], limit=0.015)
    with pytest.raises(BudgetExceeded):
        rt.ask(schema, '', {}, max_tokens=4096)
    assert len(calls) == 1 and rt.reserved_usd == 0
    assert rt.spent_usd <= rt.cost_limit


def test_timeout_does_not_retry(monkeypatch, tmp_path):
    rt, schema, calls, _, _ = fake_llm_runtime(monkeypatch, tmp_path, [TimeoutError()])
    with pytest.raises(TimeoutError):
        rt.ask(schema, '', {})
    assert len(calls) == 1 and rt.reserved_usd == 0


def test_length_finish_metadata_retries_after_settling_actual_usage(monkeypatch, tmp_path):
    from types import SimpleNamespace
    outcomes = []
    rt, schema, calls, limits, success = fake_llm_runtime(monkeypatch, tmp_path, outcomes)
    outcomes.extend([{'raw': SimpleNamespace(usage_metadata={'input_tokens': 100, 'output_tokens': 4096},
                                           response_metadata={'finish_reason': 'length'}),
                      'parsed': None, 'parsing_error': ValueError()}, success])
    rt.ask(schema, '', {})
    assert len(calls) == 2 and limits == [4096, 8192]
    assert rt.spent_usd == pytest.approx((200 * .4 + 4146 * 1.6) * 1e-6)
