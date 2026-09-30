from common import review_findings


class Reviewer:
    def __init__(self, supported):
        self.supported = supported
        self.calls = 0

    def ask(self, schema, instructions, payload):
        self.calls += 1
        return {'checks': [{'criterion_id': f['criterion_id'], 'supported': self.supported,
                            'reason': '인용문은 타사 도입 사례이며 반복 거래 2건을 뒷받침하지 않습니다.'}
                           for f in payload['findings']]}


def test_real_quote_that_does_not_support_count_is_unknown():
    source = {'source_id': 'a', 'text': '다른 회사의 로봇을 물류기업에서 도입했습니다.'}
    finding = {'criterion_id': 6, 'status': 'verified', 'numeric_value': 2,
               'evidence': [{'source_id': 'a', 'quote': source['text']}]}
    result = review_findings(Reviewer(False), {'name': '현재기업'}, [finding], [source])
    assert result[0]['status'] == 'unknown'
    assert '근거 검수' in result[0]['reason']


def test_fabricated_quote_is_rejected_before_llm():
    reviewer = Reviewer(True)
    finding = {'criterion_id': 6, 'status': 'verified', 'numeric_value': 2,
               'evidence': [{'source_id': 'a', 'quote': '없는 원문을 임의로 만든 문장입니다.'}]}
    result = review_findings(reviewer, {'name': '현재기업'}, [finding], [{'source_id': 'a', 'text': '실제 원문입니다.'}])
    assert result[0]['status'] == 'unknown'
    assert reviewer.calls == 0
