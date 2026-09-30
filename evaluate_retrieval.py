import argparse
import json
from pathlib import Path

from common import ROOT, save_json, settings
from rag import Corpus


def evaluate(corpus, questions, k):
    if type(k) is not int or k < 1:
        raise ValueError('k는 1 이상의 정수여야 합니다.')
    if not questions:
        raise ValueError('사람이 정답 출처를 확인한 평가 질문을 먼저 작성해 주세요.')
    details = []
    for item in questions:
        expected = set(item['expected_source_ids'])
        if not expected or not expected.issubset(corpus.sources):
            raise ValueError('정답 source_id가 실제 수집 자료에 있는지 확인해 주세요.')
        chunks = corpus.retrieve(item['question'], item.get('company_id'), item['doc_type'], k=k)
        first = next((rank for rank, chunk in enumerate(chunks, 1) if chunk['source_id'] in expected), None)
        details.append({'question': item['question'], 'hit': int(first is not None),
                        'reciprocal_rank': 1 / first if first else 0,
                        'retrieved_source_ids': [c['source_id'] for c in chunks]})
    return {'k': k, 'questions': len(questions), 'hit_rate': sum(x['hit'] for x in details) / len(details),
            'mrr_at_k': sum(x['reciprocal_rank'] for x in details) / len(details), 'details': details}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--sources', type=Path, required=True)
    parser.add_argument('--questions', type=Path, default=ROOT / 'data/evaluation.json')
    parser.add_argument('--k', type=int, default=4)
    args = parser.parse_args()
    if args.k < 1:
        parser.error('--k는 1 이상입니다.')
    sources = json.loads(args.sources.read_text(encoding='utf-8'))
    if isinstance(sources, dict):
        sources = sources['sources']
    corpus = Corpus(sources, settings(), ROOT / '.cache')
    questions = json.loads(args.questions.read_text(encoding='utf-8'))
    result = evaluate(corpus, questions, args.k)
    save_json(args.sources.parent / 'retrieval_evaluation.json', result)
    print(json.dumps({k: v for k, v in result.items() if k != 'details'}, ensure_ascii=False, indent=2))
