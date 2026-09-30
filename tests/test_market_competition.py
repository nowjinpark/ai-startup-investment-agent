from types import SimpleNamespace

import pytest

from agents import investment, market_competition
from evidence_audit import audit
from models import MarketOutput
from test_investment import records


class EmptyCorpus:
    def evidence_for(self, *args):
        return []

    def source_pages(self, chunks):
        return []


def forbidden_call(*args, **kwargs):
    raise AssertionError('자료가 없을 때 추가 API를 호출하면 안 됩니다.')


def test_no_market_evidence_stays_insufficient_without_paid_audit_or_score(records):
    candidate, tech, _ = records
    runtime = SimpleNamespace(corpus=EmptyCorpus(), ask=forbidden_call, search=forbidden_call)
    result = market_competition.run(runtime, candidate, 1)
    MarketOutput.model_validate({**result['details'], **{k: result[k] for k in ('summary', 'findings', 'risks', 'missing')}})
    assert result['status'] == 'insufficient'
    assert {f['criterion_id'] for f in result['findings']} == {3, 6, 7, 8}
    assert all(f['status'] == 'unknown' and f['numeric_value'] is None and not f['evidence'] for f in result['findings'])
    tech, market = audit(runtime, candidate, tech, result)
    assert market['audit_status'] == 'failed'
    judged = investment.evaluate(candidate, tech, market, 1)
    assert judged['decision'] == 'hold'
    assert judged['total_score'] is None
    assert judged['execution_status'] == 'completed'
    assert judged['analysis_status']['market']['audit_error']['type'] == 'MissingEvidence'


def test_retrieval_error_is_not_reported_as_missing_evidence():
    class BrokenCorpus(EmptyCorpus):
        def evidence_for(self, *args):
            raise RuntimeError('검색 저장소 오류')

    runtime = SimpleNamespace(corpus=BrokenCorpus(), ask=forbidden_call, search=forbidden_call)
    with pytest.raises(RuntimeError, match='검색 저장소 오류'):
        market_competition.run(runtime, {'company_id': 'test', 'name': '테스트기업'}, 1)
