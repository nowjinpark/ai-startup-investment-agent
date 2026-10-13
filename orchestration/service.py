"""검색·모델 호출·보고서 평가를 그래프의 제어 흐름과 분리합니다."""
import hashlib
import re
from pathlib import Path
from urllib.parse import urlparse

from common import save_json
from orchestration.state import (Evaluation, GroundingReview, Plan, Report, Research,
                                 VIEWS, VIEW_LABELS)

PROMPTS = Path(__file__).resolve().parents[1] / 'prompts' / 'orchestration'
CRITERIA = ('groundedness', 'neutrality', 'bias', 'coverage')
CITATION = re.compile(r'\[(S-[A-Za-z0-9_-]+)\]')
ATTRIBUTION = re.compile(r'회사.*(?:소개|설명|발표|주장)|공식.*(?:자료|사이트|소개)|(?:기사|자료|분석글|보도|출처|원문).*(?:따르면|설명|제시|보도|인용|기재|서술)')
PROMOTIONAL = re.compile(r'유일|독보|우월|최고|세계\s*1위|가장\s*우수|압도|사업성[을\s]*입증')
PERFORMANCE_NUMBER = re.compile(r'\d[\d,.]*\s*(?:mm|㎜|cm|%|퍼센트|배|곳|대|개|건|시간|분|초|명|원|억|만|천)', re.I)
NUMERIC_ATTRIBUTION = '회사 발표 기준·독립 실측 아님'
CONDITIONS = {
    'independent': '이 인용은 발표·서술된 내용이며 독립 성능 검증을 뜻하지 않습니다.',
    'paid': '공급·도입 언급과 실제 유료 계약·매출·재구매는 구분하여 확인합니다.',
    'scope': '언급한 현장·제품을 넘어 일반화하지 않으며 운영·안전 조건은 별도 확인합니다.',
    'planned': '계획·협의·착수는 완료 실적과 구분합니다.',
    'team': '팀·고객·투자자의 역할과 현재 팀의 역량·책임 범위는 구분하여 확인합니다.',
    'market_size': '투자액·회사 매출은 시장 규모가 아니며 시장의 지역·시점·범위를 추가 확인합니다.',
}
DEFAULT_CONDITION = {'technology': 'independent', 'market': 'paid',
                     'stakeholders': 'team', 'application': 'scope'}
NO_VIEW_FACT = '이 관점에 직접 답하는 검수된 사실은 아직 없어 추가 확인이 필요합니다.'
VIEW_HINTS = {
    'market': re.compile(r'고객|계약|매출|판매|납품|수출|과금|도입|수익\s*모델|지불|구매|실제\s*프로젝트|프로젝트에.*(?:참여|적용)'),
    'stakeholders': re.compile(r'대표|CTO|CEO|창업|투자사|투자자|투자\s*받|투자했|투자하|연속\s*투자|팀|고객|협력|협업|공급사|연구원|경력|파트너', re.I),
}
COMMERCIAL_FACT = re.compile(r'판매|수출|납품|과금|지불|구매|공급\s*계약|계약\s*(?:체결|방식)|실제\s*프로젝트.*적용')
SUPPLY_CONTEXT = re.compile(r'고객(?:사)?|거래처|납품처|프로젝트(?:에|의|에서)|(?:회사|기업|전자|자동차|제철|중공업|호텔|병원|공장)에')


def _commercial_fact(text):
    # 제품 기능의 데이터 공급과 투자자의 자금 공급은 고객 실적이 아닙니다.
    if re.search(r'(?:자금|투자금|유동성|대출)\s*(?:을|를)?\s*공급', text):
        return False
    supplied_to_customer = '공급' in text and SUPPLY_CONTEXT.search(text)
    return bool(COMMERCIAL_FACT.search(text) or supplied_to_customer)


def _prompt(name):
    return (PROMPTS / f'{name}.txt').read_text(encoding='utf-8')


def _short(value, limit):
    text = re.sub(r'\s+', ' ', str(value)).strip()
    return text if len(text) <= limit else text[:limit].rstrip() + '…'


def _unique(values):
    return list(dict.fromkeys(values))


def _performance_number(text):
    return PERFORMANCE_NUMBER.search(text) and re.search(
        r'오차|정밀|정확|성능|고객|매출|효율|비용|생산|처리|작업|운영|판매|납품|설치|속도|절감', text)


def _verification_questions(limitations):
    """출처가 없는 모델의 한계 문장을 사실로 전파하지 않고 확인 질문으로 바꿉니다."""
    topics = [
        (r'매출|가격|과금|유료|마진|재계약|계약|고객 수', '추가 확인: 유료 계약·과금 조건·매출 및 재계약 지표.'),
        (r'안전|인증|규제|위생', '추가 확인: 현장별 안전·규제 요건과 인증 적용 범위.'),
        (r'경쟁|대안|점유|시장 규모', '추가 확인: 동일 조건의 대안 비교와 지역·연도가 명시된 세부시장 규모.'),
        (r'독립|성능|오차|성숙|기술|작동|운용', '추가 확인: 독립적인 성능 시험과 실제 작동 조건.'),
        (r'관계|고객|공급|투자|팀|인력', '추가 확인: 팀·고객·공급사·투자자의 역할과 계약 근거.'),
        (r'해외|글로벌|산업|분야|적용|현장', '추가 확인: 적용 현장·지역별 계약과 운영 사례.'),
    ]
    joined = ' '.join(limitations)
    return [question for pattern, question in topics if re.search(pattern, joined)] or [
        '현재 검색자료에 포함되지 않은 정보는 별도 확인이 필요합니다.']


def _inference_error(text, evidence):
    """반복 관찰한 시점 혼합·자료 부재 추론은 모델 승인과 별개로 차단합니다."""
    quote = ' '.join(e['quote'] for e in evidence)
    if PROMOTIONAL.search(text):
        return '검증된 비교 없이 우위를 주장하는 홍보 표현'
    def numbers(value):
        # 날짜 구분점은 소수점이 아닙니다. 2024.11.14와 2024년 11월을 비교합니다.
        value = re.sub(r'\b((?:19|20)\d{2})[./-](0?[1-9]|1[0-2])(?:[./-]([0-3]?\d))?(?!\d)',
                       lambda m: f'{m[1]}년 {int(m[2])}월' + (f' {int(m[3])}일' if m[3] else ''), value)
        return {n.replace(',', '') for n in re.findall(r'\d+(?:[.,]\d+)*', value)}
    if numbers(text) - numbers(quote):
        return '선택한 인용에 없는 날짜·수치'
    if re.search(r'내재화했|내재화한|내재화 완료', text) and not re.search(r'내재화했|내재화한|내재화 완료', quote):
        return '내재화 가능성·조건을 내재화 완료로 바꾼 표현'
    for match in re.finditer(r'(\d+)\s*년\s*연속', text):
        if not re.search(re.escape(match[1]) + r'\s*년\s*연속', quote):
            return '투자 횟수를 연속 연도로 바꾼 표현'
    for match in re.finditer(r'(?:실증\s*초기|상용화\s*초기|고객\s*사용\s*초기|초기|실험실)\s*단계', text):
        term = re.sub(r'\s+', '', match.group())
        if term not in re.sub(r'\s+', '', quote):
            return '자료 부재만으로 기술의 초기 단계를 추론한 표현'
    if re.search(r'국한|한정되어|낮은 성숙도', text) and not re.search(r'국한|한정되어|낮은 성숙도', quote):
        return '원문이 입증하지 않은 적용 범위·성숙도 제한'
    # 사업 시작 시점과 고객 수가 같은 자료에 나와도 집계 기준일은 따로 확인해야 합니다.
    date_count = re.search(r'(\d{4}년\s*\d{1,2}월)\s*(?:기준|부터|당시)[^.!?]{0,80}\d+\s*곳', text)
    if date_count:
        date = re.escape(date_count.group(1)).replace(r'\ ', r'\s*')
        if not re.search(date + r'[^\d,.!?]{0,24}(?:기준|현재|당시)[^.!?]{0,80}\d+\s*곳', quote):
            return '상용화 시작일과 고객 수 집계일을 합친 표현'
    return None


class LiveService:
    def __init__(self, runtime, corpus, candidates, output_dir):
        self.runtime = runtime
        self.corpus = corpus
        self.candidates = {c['company_id']: c for c in candidates}
        self.output_dir = Path(output_dir)
        self.sources = corpus.sources

    def plan(self, state):
        companies = state.get('companies') or list(self.candidates.values())
        payload = {'request': state['request'], 'companies': [
            {key: c.get(key, '') for key in ('company_id', 'name', 'overview')}
            for c in companies], 'views': VIEW_LABELS}
        response = self.runtime.ask(Plan, _prompt('plan'), payload,
                                    model='gpt-4.1-mini', max_tokens=4096)
        return Plan.model_validate(response).model_dump()

    def research(self, task, revision, feedback):
        """검색 원문은 파일, 공유 상태에는 짧은 주장과 인용만 남깁니다."""
        task = task.model_dump() if hasattr(task, 'model_dump') else task
        token = hashlib.sha256(task['task_id'].encode()).hexdigest()[:16]
        raw_path = self.output_dir / 'raw' / token / f'revision-{int(revision)}.json'
        result = {'task_id': task['task_id'], 'company_id': task['company_id'],
                  'views': list(task['views']), 'revision': revision, 'status': 'ok',
                  'summary': '', 'findings': [], 'limitations': [],
                  'raw_path': str(raw_path), 'error': None,
                  'retrieved_chunk_count': 0, 'proposed_finding_count': 0,
                  'rejected_finding_count': 0, 'rejected_views': [],
                  'quote_rejected_count': 0, 'meaning_rejected_count': 0,
                  'missing_views': list(task['views']), 'evidence_status': 'not_started',
                  'grounding_status': 'not_started', 'grounding_corrected_count': 0}
        raw = {'task': task, 'revision': revision, 'feedback': feedback,
               'queries': [], 'chunks': [], 'sources': [], 'response': None}
        try:
            company = self.candidates[task['company_id']]
            queries = _unique([q.strip() for q in task.get('queries', []) if q.strip()])[:3]
            if not queries:
                queries = [company['name'] + ' ' + task['question']]
            chunks = {}
            for index, query in enumerate(queries):
                # 여러 관점의 작업은 해당 관점의 자료 종류를 번갈아 검색합니다.
                view = task['views'][index % len(task['views'])]
                doc_type = 'technology' if view == 'technology' else 'market'
                raw['queries'].append({'query': query, 'doc_type': doc_type, 'k': 4})
                for chunk in self.corpus.retrieve(query, task['company_id'], doc_type, k=4):
                    if chunk.get('company_id') not in {task['company_id'], '__sector__'}:
                        continue
                    chunks[chunk.get('chunk_id', chunk['source_id'])] = chunk
            raw['chunks'] = list(chunks.values())
            raw['sources'] = self.corpus.source_pages(raw['chunks'])
            result['retrieved_chunk_count'] = len(raw['chunks'])
            if not raw['chunks']:
                result['summary'] = '검색된 근거가 없어 확인이 필요합니다.'
                result['limitations'] = ['배정된 관점의 검색 자료가 없습니다. 자료 부재는 사실 부재를 뜻하지 않습니다.']
                result['evidence_status'] = 'no_documents'
            else:
                response = self.runtime.ask(Research, _prompt('research'),
                    {'company': company['name'], 'task': task, 'feedback': feedback,
                     'sources': raw['chunks']}, model='gpt-4.1-mini', max_tokens=4096)
                response = Research.model_validate(response).model_dump()
                raw['response'] = response
                result['proposed_finding_count'] = len(response['findings'])
                limitations = _verification_questions(response['limitations'])
                allowed = {s['source_id']: s for s in raw['sources']}
                raw['rejected_findings'] = []
                pending = []
                for finding in response['findings']:
                    if finding['view'] not in task['views']:
                        limitations.append('배정 범위를 벗어난 주장은 제외했습니다.')
                        result['rejected_finding_count'] += 1
                        raw['rejected_findings'].append({'finding': finding, 'reason': 'out_of_scope'})
                        continue
                    evidence = finding['evidence']
                    exact = bool(evidence) and all(
                        e['source_id'] in allowed and 8 <= len(e['quote'].strip()) <= 500
                        and e['quote'] in allowed[e['source_id']]['text'] for e in evidence)
                    if not exact:
                        limitations.append('검색 자료는 있으나 일부 주장의 인용 검증에 실패했습니다. 이는 원래 자료가 없다는 뜻이 아닙니다.')
                        result['rejected_finding_count'] += 1
                        result['quote_rejected_count'] += 1
                        result['rejected_views'].append(finding['view'])
                        raw['rejected_findings'].append({'finding': finding, 'reason': 'citation_rejected'})
                        continue
                    if len(pending) >= 12:
                        limitations.append('공유 상태에는 최대 12개 주장만 보관하며 전체 응답은 raw 파일에 남깁니다.')
                        break
                    pending.append(finding)
                if pending:
                    # 인용 문자열 일치만으로 사실의 시제·주체·의미까지 맞다고 볼 수 없습니다.
                    # 별도 검수자는 원문 문맥을 보고 주장과 실제 지원 인용을 함께 선택합니다.
                    reviewed = self._ground(pending, allowed, company, raw)
                    for finding, check in zip(pending, reviewed):
                        chosen = check['evidence_indices']
                        evidence = [finding['evidence'][i] for i in chosen]
                        text = re.sub(r'\s+', ' ', check['corrected_text']).strip()
                        reason = _inference_error(text, evidence)
                        suitable = _unique(check['suitable_views'])
                        if not check['supported'] or not text or len(text) > 160 or not evidence or reason or not suitable:
                            result['rejected_finding_count'] += 1
                            result['meaning_rejected_count'] += 1
                            result['rejected_views'].append(finding['view'])
                            raw['rejected_findings'].append({'finding': finding,
                                'reason': reason or check['reason'] or 'meaning_or_view_not_supported'})
                            limitations.append('검색 자료의 실제 표현과 일치하지 않는 주장은 제외하고 다시 확인합니다.')
                            continue
                        source = allowed[evidence[0]['source_id']]
                        text = self._source_sentence(text, source, company)
                        result['grounding_corrected_count'] += int(text != finding['text'])
                        result['findings'].append({'view': finding['view'], 'text': text,
                                                  'evidence': evidence, 'suitable_views': suitable})
                    result['grounding_status'] = 'reviewed'
                else:
                    result['grounding_status'] = 'no_valid_quotes'
                present = {view for f in result['findings'] for view in self._fact_views(f)
                           if self._view_hint(f, view)}
                missing = set(task['views']) - present
                repair_candidates = [f for f in pending if f['view'] in missing][:6]
                if repair_candidates:
                    # 과장된 원래 주장 전체를 버리기 전에 같은 인용의 좁은 사실을 한 번 복원합니다.
                    # 기존 원문·첫 판정은 유지하고 추가 검수 입력/응답을 별도 항목에 저장합니다.
                    repair = {'requested_views': sorted(missing), 'accepted': [], 'rejected': []}
                    try:
                        checks = self._ground(repair_candidates, allowed, company, repair,
                                              recover_views=sorted(missing))
                        for finding, check in zip(repair_candidates, checks):
                            evidence = [finding['evidence'][i] for i in check['evidence_indices']]
                            text = re.sub(r'\s+', ' ', check['corrected_text']).strip()
                            reason = _inference_error(text, evidence)
                            fixed = {'view': finding['view'], 'text': text, 'evidence': evidence,
                                     'suitable_views': _unique(check['suitable_views'])}
                            useful = set(self._fact_views(fixed)) & missing
                            if not check['supported'] or not evidence or not text or len(text) > 160 or reason or not useful:
                                repair['rejected'].append({'check': check, 'reason': reason or 'no_supported_missing_view'})
                                continue
                            fixed['text'] = self._source_sentence(text, allowed[evidence[0]['source_id']], company)
                            if len(result['findings']) < 12:
                                result['findings'].append(fixed)
                                repair['accepted'].append(fixed)
                                result['grounding_corrected_count'] += 1
                    except Exception as error:
                        repair['error'] = type(error).__name__
                    raw['grounding_repair'] = repair
                result['limitations'] = _unique(limitations)[:8]
                result['rejected_views'] = _unique(result['rejected_views'])
                result['missing_views'] = [v for v in task['views']
                                          if not any(v in self._fact_views(f) and self._view_hint(f, v)
                                                     for f in result['findings'])]
                # 내용은 참이어도 잘못 분류한 관점은 충족으로 세지 않습니다.
                mismatched = [f['view'] for f in result['findings'] if f['view'] not in f['suitable_views']]
                result['rejected_views'] = _unique(result['rejected_views'] + mismatched)
                result['view_mismatch_count'] = len(mismatched)
                result['summary'] = f"검색 {len(raw['chunks'])}개 청크에서 원문 인용과 의미를 검수한 주장 {len(result['findings'])}개를 보관했습니다."
                result['evidence_status'] = ('citation_rejected' if result['quote_rejected_count'] else
                    'meaning_rejected' if result['meaning_rejected_count'] else
                    'verified' if result['findings'] else 'no_claims')
                if result['missing_views']:
                    reason = '인용·의미 검증에 실패한 주장이 있어 재조사가 필요합니다.' if (
                        set(result['missing_views']) & set(result['rejected_views'])) else '근거를 현재 검색 범위에서 확인하지 못했습니다.'
                    result['limitations'] = result['limitations'][:7] + [
                        ', '.join(VIEW_LABELS[v] for v in result['missing_views']) + ': ' + reason]
        except Exception as error:
            # 공급자 예외 메시지에는 키나 원문이 섞일 수 있어 종류만 기록합니다.
            result.update(status='failed', summary='조사를 완료하지 못했습니다.', findings=[],
                          limitations=['실행 실패를 자료가 없다는 뜻으로 해석하지 않습니다.'],
                          error=type(error).__name__, evidence_status='execution_failed',
                          grounding_status='execution_failed')
            raw['error'] = type(error).__name__
        raw['result'] = result
        save_json(raw_path, raw)
        return result

    @staticmethod
    def _source_info(source, company):
        host = (urlparse(source.get('url') or '').hostname or '').lower().removeprefix('www.')
        official = (urlparse(company.get('website') or '').hostname or '').lower().removeprefix('www.')
        is_official = bool(official and (host == official or host.endswith('.' + official)))
        if is_official:
            kind = '회사 뉴스룸 발표' if 'news' in (source.get('url') or '').lower() else '회사 공식 자료'
        elif 'blog' in host or host.endswith(('doinghun.com', 'tistory.com')) or '분석]' in source.get('title', ''):
            kind = '외부 분석글'
        else:
            kind = '외부 자료'
        return {'url': source.get('url', ''), 'publisher': source.get('publisher') or host or '보관 원문',
                'source_kind': kind, 'official_domain_match': is_official,
                'company_website': company.get('website', '')}

    def _source_sentence(self, text, source, company):
        info = self._source_info(source, company)
        # 매체 귀속은 모델이 짐작하지 않고 확인한 URL에 따라 붙입니다.
        text = re.sub(r'^(?:해당 기사는|공식 소개는|회사 공식 사이트는|회사 발표는|공식 미션은|회사 뉴스룸은)\s*', '', text)
        if not info['official_domain_match'] and re.search(r'공식\s*(?:소개|발표|사이트|미션|자료)', text):
            raise ValueError('external_source_cannot_be_company_official')
        prefix = f"{info['source_kind']}({info['publisher']})에 따르면, "
        return self._attribute(prefix + text)

    def _ground(self, findings, sources, company, raw, recover_views=None):
        claims = []
        for index, finding in enumerate(findings):
            evidence = []
            for evidence_index, item in enumerate(finding['evidence']):
                source = sources[item['source_id']]
                position = source['text'].find(item['quote'])
                evidence.append({**item, 'index': evidence_index, **self._source_info(source, company),
                    'title': source.get('title', ''), 'published_at': source.get('published_at'),
                    'context': source['text'][max(0, position - 240):position + len(item['quote']) + 240]})
            claims.append({'index': index, 'view': finding['view'],
                           'text': finding['text'], 'evidence': evidence})
        raw['grounding_input'] = {'company': company['name'], 'company_website': company.get('website', ''),
                                  'view_definitions': VIEW_LABELS, 'claims': claims,
                                  'recover_views': recover_views or []}
        instructions = _prompt('grounding')
        if recover_views:
            instructions += ('\n추가 복원 검수입니다. 기존 text는 실패한 초안일 수 있습니다. 각 claim.view에 맞는 단일 사실을 '
                '같은 evidence.quote 안에서 새로 고르세요. 기존 문장 전체가 틀렸어도 quote의 참인 한 부분을 corrected_text로 반환할 수 있습니다. '
                'technology는 제품 구성·작동 원리·핵심 기술 목록, market는 실제 판매·수출·고객 공급·계약 방식을 우선합니다. '
                '날짜·고객 수·홍보 평가를 합치지 말고 필요하면 모두 제외한 단일 사실을 선택합니다. '
                '원문에 그러한 사실이 없을 때만 supported=false입니다. 원문 의미 검증 기준과 정확한 evidence_indices는 동일합니다.')
        response = self.runtime.ask(GroundingReview, instructions, raw['grounding_input'],
                                    model='gpt-4.1', max_tokens=4096)
        review = GroundingReview.model_validate(response).model_dump()
        raw['grounding_review'] = review
        checks = review['checks']
        # 생략·중복된 판정은 승인으로 보충하지 않고 작업 실패로 전파합니다.
        if sorted(check['index'] for check in checks) != list(range(len(findings))):
            raise ValueError('grounding_review_index_mismatch')
        checks.sort(key=lambda check: check['index'])
        for finding, check in zip(findings, checks):
            indices = check['evidence_indices']
            if len(indices) != len(set(indices)) or any(i < 0 or i >= len(finding['evidence']) for i in indices):
                raise ValueError('grounding_review_evidence_mismatch')
            if check['supported'] and len(indices) != 1:
                raise ValueError('grounding_review_requires_one_quote')
        return checks

    def _results(self, state):
        return list(state.get('results', {}).values())

    def _allowed(self, results, company_id=None):
        return {e['source_id'] for r in results
                if r.get('status') == 'ok' and (company_id is None or r['company_id'] == company_id)
                for f in r.get('findings', []) for e in f['evidence']
                if e['source_id'] in self.sources}

    def _catalog(self, results):
        # 모델의 관점 분류가 넓어져도 기능·미션만으로 시장/관계자 슬롯을 채우지 않습니다.
        return {f"{r['task_id']}:{index}": {**finding, 'company_id': r['company_id'],
                    'suitable_views': [view for view in self._fact_views(finding)
                                       if self._view_hint(finding, view)]}
                for r in results if r.get('status') == 'ok'
                for index, finding in enumerate(r.get('findings', []))}

    @staticmethod
    def _fact_views(finding):
        views = list(finding.get('suitable_views', [finding['view']]))
        # 이미 검수된 고객 공급·판매·수출은 시장 접점입니다. 금액·유료 여부는 추가하지 않습니다.
        if _commercial_fact(finding['text']) and 'market' not in views:
            views.append('market')
        return views

    @staticmethod
    def _view_hint(finding, view):
        if view == 'market' and _commercial_fact(finding['text']):
            return True
        pattern = VIEW_HINTS.get(view)
        return pattern is None or bool(pattern.search(finding['text']))

    @staticmethod
    def _render_finding(finding):
        return finding['text'] + ' ' + ' '.join(f"[{e['source_id']}]" for e in finding['evidence'])

    def _view_candidates(self, catalog, company_id, view):
        return {key: f for key, f in catalog.items() if f['company_id'] == company_id
                and view in f.get('suitable_views', [f['view']]) and self._view_hint(f, view)}

    def _render_view(self, catalog, company_id, view, selection, feedback):
        candidates = self._view_candidates(catalog, company_id, view)
        chosen = _unique(selection.get('finding_ids', []))[:2]
        # 타 기업·부적합 관점·잘못된 식별자를 대체 사실로 조용히 채우지 않습니다.
        findings = [candidates[key] for key in chosen if key in candidates]
        paragraphs = [self._render_finding(f) for f in findings] or [NO_VIEW_FACT]
        codes = _unique([DEFAULT_CONDITION[view]] + selection.get('condition_codes', []))
        if '독립' in feedback and view in {'technology', 'application'}:
            codes = _unique([DEFAULT_CONDITION[view], 'independent'] + codes)
        if re.search(r'계획|완료|협의', feedback) and view == 'application':
            codes = _unique(['scope', 'planned'] + codes)
        return ' '.join(paragraphs + [CONDITIONS[code] for code in codes[:2] if code in CONDITIONS])

    @staticmethod
    def _attribute(text):
        text = text if ATTRIBUTION.search(text) else '출처 자료의 설명에 따르면, ' + text
        if _performance_number(text) and NUMERIC_ATTRIBUTION not in text:
            text = text.rstrip('. ') + f' ({NUMERIC_ATTRIBUTION}).'
        return text

    def _summary_fallback(self, results, companies, selections=None):
        names = '·'.join(company['name'] for company in companies)
        prefix = f'{names} 등 {len(companies)}개 기업은 최신 자격 확인을 전제로 조건부 검토합니다. 핵심 확인 결과: '
        suffix = ' 공급·판매 언급과 유료 계약·독립 검증은 구분하며 추가 실사합니다.'
        catalog, options = self._catalog(results), []
        for company in companies:
            cid = company['company_id']
            eligible = self._view_candidates(catalog, cid, 'market')
            chosen = selections.get((cid, 'market'), {}).get('finding_ids', []) if selections is not None else list(eligible)
            facts = [eligible[key] for key in chosen if key in eligible]
            if facts:
                fact = min(facts, key=lambda value: len(self._render_finding(value)))
                options.append(company['name'] + ': ' + self._render_finding(fact))
        lines = []
        # 검수 문장을 자르거나 재서술하지 않고 전체가 들어가는 대표 근거를 선택합니다.
        for line in sorted(options, key=len):
            if len(lines) < 2 and len(prefix + ' '.join(lines + [line]) + suffix) <= 400:
                lines.append(line)
        if not lines and options:
            prefix = names + ': 조건부 검토. 확인 결과: '
            suffix = ' 자격·계약·독립 검증은 추가 확인합니다.'
            shortest = min(options, key=len)
            if len(prefix + shortest + suffix) <= 400:
                lines = [shortest]
        if not lines:
            lines = ['선택된 시장 근거를 추가 확인해야 합니다.']
        return prefix + ' '.join(lines) + suffix

    def _digest(self, text, results, fallback, limit):
        """요약도 검수된 문장을 그대로 선택한 경우만 사용합니다."""
        text = re.sub(r'\s+', ' ', text).strip()
        if not text or len(text) > limit or PROMOTIONAL.search(text):
            return fallback
        known = []
        for result in results:
            if result.get('status') != 'ok':
                continue
            company = self.candidates.get(result['company_id'], {})
            for finding in result.get('findings', []):
                plain = finding['text'].strip().rstrip('. ')
                refs = {e['source_id'] for e in finding['evidence']}
                known += [(plain, refs), (company.get('name', '') + ': ' + plain, refs)]
        # 프롬프트에서 각 사실을 '검수 문장 [출처].' 형식으로 지정합니다.
        sentences = re.split(r'(?<=\.)\s+(?!\[)', text)
        for sentence in sentences:
            cited = set(CITATION.findall(sentence))
            plain = CITATION.sub('', sentence).strip().rstrip('. ')
            if not any(plain == claim and cited == refs for claim, refs in known):
                return fallback
        return text

    def _company_questions(self, company):
        description = self.candidates[company['company_id']].get('overview', '')
        if re.search(r'조리|튀김|주방', description):
            domain = '주방별 설치·청소·인력 조건, 위생 인증의 적용 제품과 유지 비용을 확인할 수 있는가?'
        elif re.search(r'건설|철근', description):
            domain = '현장별 생산량·불량률·안전 조건과 설비 연동·납품 범위를 확인할 수 있는가?'
        elif re.search(r'3D|데이터|시뮬레이션', description):
            domain = '데이터의 물리 정확도·시뮬레이터 호환성과 실제 로봇 전환 성능을 같은 조건에서 검증할 수 있는가?'
        else:
            domain = '현장별 인식·작업 오차, 장비 호환성 및 장기간 운영 조건을 독립적으로 확인할 수 있는가?'
        return [domain, '대상 제품의 시장 규모는 어느 지역·기준연도·범위인가? 실제 매출·유료 계약과 동일 조건의 경쟁 대안은 무엇인가?',
                '핵심 팀원의 역량·역할·경력과 고객·투자자·공급사·규제기관의 책임을 계약·경력 자료로 확인할 수 있는가?']

    @staticmethod
    def _qualification(company):
        labels = {'unlisted': '비상장', 'stage': '투자 단계', 'no_exit': 'Exit 미완료'}
        pending, failed = [], []
        for key, label in labels.items():
            value = company.get('eligibility', {}).get(key, 'unknown')
            status = value.get('status', 'unknown') if isinstance(value, dict) else value
            if status == 'fail':
                failed.append(label)
            elif status != 'pass':
                pending.append(label)
        if failed:
            return '준비 자료에서 ' + ', '.join(failed) + ' 조건 불충족이 기록되어 있습니다. 현재 상태를 확인하기 전 투자 후보로 확정하지 않습니다.'
        if pending:
            return ', '.join(pending) + ' 자격이 미확인인 조건부 검토입니다. 확정 투자 추천이 아닙니다.'
        return '준비 자료의 자격 판정과 현재 상태를 구분합니다. 투자 실행 전 최신 자격 확인이 필요합니다.'

    def _paragraph(self, text, allowed, fallback, limit=600):
        text = re.sub(r'\s+', ' ', text).strip()
        cited = set(CITATION.findall(text))
        if not text or len(text) > limit or cited - allowed:
            return fallback
        # '확인 필요' 한마디로 앞의 무출처 사실문장이 통과하는 예외를 두지 않습니다.
        if not cited:
            return fallback
        # 한 문단 끝의 인용 하나가 다른 무출처 문장까지 자동으로 뒷받침하지 않습니다.
        sentences = re.split(r'(?<=[.!?])\s+(?!\[)', text)
        if any(sentence.strip() and not CITATION.search(sentence) for sentence in sentences):
            return fallback
        evidence = [{'quote': self.sources[sid]['text']} for sid in cited if sid in self.sources]
        if _inference_error(text, evidence):
            return fallback
        return text

    def synthesize(self, state):
        results = self._results(state)
        companies = state.get('companies') or list(self.candidates.values())
        catalog = self._catalog(results)
        payload = {'request': state['request'], 'feedback': state.get('feedback', ''),
                   'previous_report': state.get('report', ''), 'conditions': CONDITIONS,
                   'finding_catalog': catalog,
                   'required_slots': [{'company_id': company['company_id'], 'view': view,
                       'allowed_finding_ids': list(self._view_candidates(catalog, company['company_id'], view))}
                       for company in companies for view in VIEWS],
                   'companies': [{'company_id': c['company_id'], 'name': c['name']} for c in companies],
                   'results': [{k: r.get(k) for k in ('company_id', 'views', 'status', 'limitations',
                                'rejected_finding_count', 'rejected_views', 'missing_views', 'evidence_status')}
                               for r in results]}
        response = self.runtime.ask(Report, _prompt('synthesize'), payload,
                                    model='gpt-4.1-mini', max_tokens=7000)
        report = Report.model_validate(response).model_dump()
        selections = {}
        for selection in report['selections']:
            key = (selection['company_id'], selection['view'])
            if key in selections:
                raise ValueError('duplicate_report_selection')
            selections[key] = selection
        selection_repairs = []
        for company in companies:
            cid = company['company_id']
            for view in VIEWS:
                key = (cid, view)
                original = selections.get(key, {})
                eligible = self._view_candidates(catalog, cid, view)
                chosen = _unique([fid for fid in original.get('finding_ids', []) if fid in eligible])[:2]
                if not chosen and eligible:
                    # 실제로 검수된 동일 기업·관점 후보가 있을 때만 빠진 선택을 복구합니다.
                    chosen = [next(iter(eligible))]
                fixed = {'company_id': cid, 'view': view, 'finding_ids': chosen,
                         'condition_codes': original.get('condition_codes', [])}
                if fixed != original:
                    selection_repairs.append({'original': original, 'resolved': fixed})
                selections[key] = fixed
        save_json(self.output_dir / 'raw' / f"report-{state.get('revision', 0)}.json",
                  {'selections': list(selections.values()), 'model_response': report,
                   'selection_repairs': selection_repairs})
        summary = self._summary_fallback(results, companies, selections)
        lines = ['## SUMMARY', '', summary, '']
        for company in companies:
            cid = company['company_id']
            lines += [f"## {company['name']}", '']
            for view in VIEWS:
                text = self._render_view(catalog, cid, view, selections.get((cid, view), {}),
                                         state.get('feedback', ''))
                lines += [f'**{VIEW_LABELS[view]}** — {text}', '']
            lines += ['**검토 의견·기업 자격** — ' + self._qualification(company)
                      + ' 유료 계약·독립 성능 확인 후 투자 적합성을 검토합니다.', '']
            questions = self._company_questions(company)
            lines += ['**위험과 적용 조건** — ' + questions[0], '']
            lines += ['**추가 확인** — ' + ' / '.join(questions[1:]), '']
        # Writer가 선택한 시장/적용 사실을 회사별로 나란히 놓아 실제 차이를 비교합니다.
        comparison_rows = []
        for company in companies:
            cid = company['company_id']
            ids = selections.get((cid, 'market'), {}).get('finding_ids', [])
            eligible = self._view_candidates(catalog, cid, 'market')
            fact = next((eligible[key] for key in ids if key in eligible), None)
            comparison_rows.append('- ' + company['name'] + ': ' + (
                self._render_finding(fact) if fact else '시장 접점에 직접 답하는 근거는 추가 확인이 필요합니다.'))
        comparison = '\n'.join(comparison_rows) + '\n\n같은 조건의 비교 시험을 추가 확인하기 전 기술 우열이나 투자 순위를 결정하지 않습니다.'
        lines += ['## 비교와 한계', '', comparison, '',
                  '- 공식 기업·투자사 소개 중심의 자료에는 홍보와 선택 편향이 있을 수 있습니다. 독립 검증 자료와 부정적 근거가 충분한지 별도 확인해야 합니다.',
                  '- 자료에 나타나지 않은 사실을 없다고 판단하지 않습니다. 계획과 완료 실적, 고객과 투자자를 구분하며 검증되지 않은 성능 우위를 확정하지 않습니다.',
                  '- 이전 투자 점수는 재사용하지 않았습니다. 이번 실행에서는 투자 점수를 새로 산정하지 않았으며, 검수된 근거와 미확인 조건을 기준으로 검토합니다.']
        body = '\n'.join(lines).rstrip()
        used = sorted(set(CITATION.findall(body)))
        references = []
        for sid in used:
            source = self.sources[sid]
            site = source.get('publisher') or urlparse(source.get('url') or '').hostname or '보관 원문'
            details = [source.get('author') or '저자 정보 미수집', site, source.get('title', '제목 미상'), source.get('url') or '보관 원문',
                       '발행일 ' + str(source.get('published_at') or '미확인')]
            if source.get('collected_at'):
                details.append('수집일 ' + str(source['collected_at']))
            if source.get('original_page'):
                details.append('원문 ' + str(source['original_page']) + '쪽')
            references.append(f"- [{sid}] " + ' | '.join(details))
        if not references:
            references = ['- 본문에 검증 가능한 인용이 없어 추가 자료 확인이 필요합니다.']
        return body + '\n\n## REFERENCE\n\n' + '\n'.join(references) + '\n'

    def _check(self, state):
        """모델의 취향과 무관한 출처·필수 구성 오류를 먼저 확인합니다."""
        report = state.get('report', '')
        body, marker, references = report.partition('## REFERENCE')
        results = self._results(state)
        catalog = self._catalog(results)
        errors = []
        if not report.lstrip().startswith('## SUMMARY'):
            errors.append(('coverage', '첫 부분에 SUMMARY가 없습니다.'))
        if not marker or re.search(r'^## ', references, re.MULTILINE):
            errors.append(('coverage', '마지막에 REFERENCE가 필요합니다.'))
        if PROMOTIONAL.search(body):
            errors.append(('neutrality', '본문에 검증 없이 우위를 강조하는 표현이 있습니다.'))
        summary = body.split('## SUMMARY', 1)[-1].split('\n## ', 1)[0].strip()
        if len(summary) > 400:
            errors.append(('coverage', 'SUMMARY가 400자를 초과합니다.'))
        cited = set(CITATION.findall(body))
        allowed = self._allowed(results)
        if not cited:
            errors.append(('groundedness', '보고서에 확인 가능한 원문 인용이 없습니다.'))
        if cited - allowed:
            errors.append(('groundedness', '검증한 worker 근거에 없는 인용이 있습니다: ' + ', '.join(sorted(cited - allowed))))
        if cited != set(CITATION.findall(references)):
            errors.append(('groundedness', '본문 인용과 REFERENCE 출처가 일치하지 않습니다.'))
        for company in state.get('companies') or list(self.candidates.values()):
            header = f"## {company['name']}\n"
            if header not in body:
                errors.append(('coverage', company['name'] + ': 기업 설명이 없습니다.'))
                continue
            section = body.split(header, 1)[1].split('\n## ', 1)[0]
            for view, label in VIEW_LABELS.items():
                if f'**{label}**' not in section:
                    errors.append(('coverage', company['name'] + ': ' + label + ' 설명이 없습니다.'))
                    continue
                line = section.split(f'**{label}** — ', 1)[-1].split('\n', 1)[0]
                candidates = self._view_candidates(catalog, company['company_id'], view)
                remaining, used_count = line, 0
                for fact in candidates.values():
                    rendered = self._render_finding(fact)
                    if rendered in remaining:
                        remaining = remaining.replace(rendered, '', 1)
                        used_count += 1
                for condition in [NO_VIEW_FACT, *CONDITIONS.values()]:
                    remaining = remaining.replace(condition, '')
                if remaining.strip() or used_count > 2:
                    errors.append(('groundedness', company['name'] + ': ' + label + ' 문장이 해당 관점의 검수 사실과 다릅니다.'))
                if not used_count:
                    errors.append(('coverage', company['name'] + ': ' + label + '에 적합한 사실 선택이 없습니다.'))
            if set(CITATION.findall(section)) - self._allowed(results, company['company_id']):
                errors.append(('groundedness', company['name'] + ': 다른 기업 작업의 인용을 사용했습니다.'))
        for result in results:
            if result.get('status') == 'failed':
                errors.append(('coverage', result['task_id'] + ': worker 실행이 실패했습니다.'))
            if result.get('findings') and result.get('grounding_status') != 'reviewed':
                errors.append(('groundedness', result['task_id'] + ': 원문 의미 검수를 완료하지 않은 결과입니다.'))
            rejected_missing = set(result.get('missing_views', [])) & set(result.get('rejected_views', []))
            company_available = {view for f in catalog.values() if f['company_id'] == result['company_id']
                                 for view in f.get('suitable_views', [f['view']])}
            rejected_missing -= company_available
            if result.get('rejected_finding_count', 0) and rejected_missing:
                errors.append(('coverage', result['task_id'] + ': 검색 자료가 있지만 인용·의미 검증 실패로 '
                               + ', '.join(VIEW_LABELS[v] for v in sorted(rejected_missing))
                               + ' 근거가 누락됐습니다. 자료 부족으로 승인하지 말고 해당 작업을 재조사해야 합니다.'))
            for finding in result.get('findings', []):
                if _performance_number(finding['text']) and NUMERIC_ATTRIBUTION not in finding['text']:
                    errors.append(('neutrality', result['task_id'] + ': 수치의 회사 발표·독립 실측 여부가 빠졌습니다.'))
                for item in finding['evidence']:
                    source = self.sources.get(item['source_id'])
                    if source is None or item['quote'] not in source['text']:
                        errors.append(('groundedness', result['task_id'] + ': 인용 원문을 재확인할 수 없습니다.'))
        return errors

    def _contexts(self, state):
        used = set(CITATION.findall(state.get('report', '').partition('## REFERENCE')[0]))
        contexts = {}
        for result in self._results(state):
            for finding in result.get('findings', []):
                if self._render_finding(finding) not in state.get('report', ''):
                    continue
                for evidence in finding['evidence']:
                    sid, quote = evidence['source_id'], evidence['quote']
                    if sid not in used or sid not in self.sources:
                        continue
                    source = self.sources[sid]
                    position = source['text'].find(quote)
                    if position < 0:
                        continue
                    item = contexts.setdefault(sid, {'source_id': sid, 'company_id': source['company_id'],
                        'title': source.get('title', ''), 'url': source.get('url', ''),
                        'published_at': source.get('published_at'), 'excerpts': []})
                    excerpt = source['text'][max(0, position - 180):position + len(quote) + 180]
                    if excerpt not in item['excerpts'] and len(item['excerpts']) < 8:
                        item['excerpts'].append(excerpt)
        return list(contexts.values())

    def evaluate(self, state):
        errors = self._check(state)
        task_ids = {t['task_id'] for t in state.get('plan', [])}
        response = self.runtime.ask(Evaluation, _prompt('evaluate'),
            {'request': state['request'], 'report': state.get('report', ''),
             'plan': state.get('plan', []), 'source_contexts': self._contexts(state),
             'findings': [{'task_id': r['task_id'], 'company_id': r['company_id'],
                          'status': r['status'], 'findings': [f for f in r.get('findings', [])
                              if self._render_finding(f) in state.get('report', '')],
                          'limitations': r.get('limitations', []),
                          'retrieved_chunk_count': r.get('retrieved_chunk_count', 0),
                          'rejected_finding_count': r.get('rejected_finding_count', 0),
                          'missing_views': r.get('missing_views', []),
                          'evidence_status': r.get('evidence_status', '')} for r in self._results(state)]},
            model='gpt-4.1', max_tokens=3500)
        evaluation = Evaluation.model_validate(response).model_dump()
        checks = {}
        for criterion in CRITERIA:
            matches = [c for c in evaluation['criteria'] if c['criterion'] == criterion]
            if len(matches) != 1:
                errors.append((criterion, '평가 결과의 ' + criterion + ' 항목이 누락되거나 중복됐습니다.'))
                checks[criterion] = {'criterion': criterion, 'passed': False, 'reason': '평가 항목 누락·중복'}
            else:
                checks[criterion] = matches[0]
        for criterion, reason in errors:
            checks[criterion]['passed'] = False
            checks[criterion]['reason'] += ' / ' + reason
        evaluation['criteria'] = [checks[c] for c in CRITERIA]
        evaluation['deterministic_errors'] = [reason for _, reason in errors]
        evaluation['retry_task_ids'] = [t for t in _unique(evaluation['retry_task_ids']) if t in task_ids]
        if all(c['passed'] for c in evaluation['criteria']):
            evaluation.update(action='approve', retry_task_ids=[])
        else:
            failed = [r['task_id'] for r in self._results(state) if r.get('status') == 'failed']
            failed += [r['task_id'] for r in self._results(state)
                       if r.get('rejected_finding_count', 0)
                       and any(not self._view_candidates(self._catalog(self._results(state)), r['company_id'], view)
                               for view in set(r.get('missing_views', [])) & set(r.get('rejected_views', [])))]
            failed += [r['task_id'] for r in self._results(state)
                       if r.get('findings') and r.get('grounding_status') != 'reviewed']
            catalog = self._catalog(self._results(state))
            failed += [task['task_id'] for task in state.get('plan', [])
                       if any(not self._view_candidates(catalog, task['company_id'], view)
                              for view in task['views'])]
            if failed:
                evaluation.update(action='research', retry_task_ids=[t for t in _unique(failed) if t in task_ids])
            elif evaluation['action'] == 'approve':
                evaluation.update(action='rewrite', retry_task_ids=[])
            elif evaluation['action'] == 'research' and not evaluation['retry_task_ids']:
                evaluation['retry_task_ids'] = sorted(task_ids)
            elif evaluation['action'] == 'rewrite':
                evaluation['retry_task_ids'] = []
        if errors:
            evaluation['feedback'] += '\n코드 검사: ' + ' / '.join(reason for _, reason in errors)
        save_json(self.output_dir / 'raw' / f"evaluation-{state.get('revision', 0)}.json", evaluation)
        return evaluation
