import hashlib
import json
import math
from copy import deepcopy
from pathlib import Path
from xml.sax.saxutils import escape

from langchain_core.embeddings import Embeddings

from common import ROOT, save_json, rubric
from rag import Corpus


class DemoEmbeddings(Embeddings):
    def embed_documents(self, texts):
        vectors = []
        for text in texts:
            vector = [0.0] * 64
            for token in text.split():
                vector[int(hashlib.sha256(token.encode()).hexdigest()[:8], 16) % 64] += 1
            length = math.sqrt(sum(v * v for v in vector)) or 1
            vectors.append([v / length for v in vector])
        return vectors

    def embed_query(self, text):
        return self.embed_documents([text])[0]


class DemoRuntime:
    demo = True

    def __init__(self, config, output_dir, all_hold=False):
        self.config = {**config, 'embedding_model': 'demo-hash-v1'}
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.fixtures = json.loads((ROOT / 'data/demo_inputs.json').read_text(encoding='utf-8'))[:config['max_candidates']]
        for item in self.fixtures:
            for role in ['technology', 'market']:
                if item[role].get('rubric_version') != rubric()['version']:
                    raise ValueError('가상 입력 자료의 평가표 버전을 확인해 주세요.')
                expected = {r['id'] for r in rubric()['criteria'] if r['owner'] == role}
                actual = {f['criterion_id'] for f in item[role]['findings']}
                if actual != expected:
                    raise ValueError('가상 입력 자료의 평가 항목을 확인해 주세요.')
        if all_hold:
            for item in self.fixtures:
                finding = next(f for f in item['market']['findings'] if f['criterion_id'] == 3)
                finding.update(status='unknown', reason='테스트: 고객 구매 근거 미확인', evidence=[])
        self.by_name = {item['candidate']['name']: item for item in self.fixtures}
        self.corpus = None

    def prepare(self, request):
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import Paragraph, SimpleDocTemplate
        corpus_dir = self.output_dir / 'corpus'
        corpus_dir.mkdir(exist_ok=True)
        pdfmetrics.registerFont(TTFont('DemoKorean', str(ROOT / 'assets/NanumGothic-Regular.ttf')))
        style = ParagraphStyle('demo', fontName='DemoKorean', fontSize=10, leading=16, wordWrap='CJK')
        sources = []
        for item in self.fixtures:
            for role in ['candidate', 'technology', 'market']:
                for source in item[role]['sources']:
                    source['file'] = source['source_id'] + '.pdf'
                    target = corpus_dir / source['file']
                    SimpleDocTemplate(str(target)).build([
                        Paragraph('테스트용 가상 기업 자료', style),
                        Paragraph(escape(source['text']).replace('\n', '<br/>'), style)])
                    sources.append(source)
        save_json(corpus_dir / 'sources.json', sources)
        self.corpus = Corpus(sources, self.config, self.output_dir / 'demo-cache', embeddings=DemoEmbeddings())
        self.corpus.retrieve(request, None, 'company')
        candidates = [item['candidate'] for item in self.fixtures]
        save_json(self.output_dir / 'candidates.json', candidates)
        return {'candidate_list': candidates, 'doc_pages': len(sources), 'page_cap': 200,
                'prepared': {'demo': True, 'corpus': str(corpus_dir)}}

    def ask(self, schema, instructions, payload):
        if schema.__name__ == 'EvidenceReview':
            return {'checks': [{'criterion_id': f['criterion_id'], 'supported': True, 'reason': '가상 테스트 입력의 근거'}
                               for f in payload['findings']]}
        if schema.__name__ == 'ReportSelection':
            return {'sentence_indices': list(range(min(3, len(payload['sentences']))))}
        role = 'technology' if schema.__name__ == 'TechnologyOutput' else 'market'
        item = deepcopy(self.by_name[payload['company']][role])
        return {**item['details'], 'summary': item['summary'], 'findings': item['findings'],
                'risks': item['risks'], 'missing': item['missing']}
