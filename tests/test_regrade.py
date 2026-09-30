import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

import regrade
from common import ROOT, rubric, save_json


@pytest.fixture
def v2_analysis():
    rules = json.loads((ROOT / 'docs/archive/rubric-v2.json').read_text())
    def make(role):
        findings = []
        for rule in rules['criteria']:
            if rule['owner'] != role:
                continue
            quote = f"{rule['id']}번에 대해 저장된 실제 원문입니다."
            findings.append({
                'criterion_id': rule['id'], 'status': 'verified',
                'numeric_value': rule.get('medium'),
                'category_value': next(iter(rule.get('values', {})), None),
                'items': rule.get('allowed', [])[:1],
                'reason': f"{rule['id']}번 저장된 판정 이유입니다.",
                'evidence': [{'source_id': f"source-{rule['id']}", 'quote': quote}],
            })
        return {'company_id': 'demo', 'round_id': 4, 'rubric_version': '2.0',
                'status': 'completed', 'audit_status': 'completed',
                'findings': findings, 'summary': '이전 10항목 분석 요약',
                'missing': [], 'risks': ['원문 확인이 필요한 위험'],
                'details': {'technology': '저장된 기술 설명', 'team': '저장된 팀 설명'},
                'sources': [{'source_id': f['evidence'][0]['source_id'],
                             'text': f['evidence'][0]['quote'], 'company_id': 'demo'} for f in findings]}
    return make


@pytest.mark.parametrize('role,ids', [('technology', [2, 10]), ('market', [3, 6, 7, 8])])
def test_migration_preserves_retained_values_and_literal_evidence(v2_analysis, role, ids):
    original = v2_analysis(role)
    before = deepcopy(original)
    result = regrade.migrate_analysis(original, role)
    assert original == before
    assert [item['criterion_id'] for item in result['findings']] == ids
    assert result['findings'] == [item for item in before['findings'] if item['criterion_id'] in ids]
    assert result['sources'] == before['sources']
    assert result['details'] == before['details']
    assert result['risks'] == before['risks']
    assert result['rubric_version'] == '3.0' and result['regraded_from_version'] == '2.0'
    assert result['company_id'] == 'demo' and result['round_id'] == 4
    result['findings'][0]['evidence'][0]['quote'] = '별도 결과 수정'
    assert original == before


def test_removed_technology_items_are_qualitative_only(v2_analysis):
    analysis = v2_analysis('technology')
    result = regrade.migrate_analysis(analysis, 'technology')
    assert result['qualitative_findings'] == [f for f in analysis['findings'] if f['criterion_id'] in [4, 5, 9]]
    assert not {4, 5, 9} & {f['criterion_id'] for f in result['findings']}
    market = regrade.migrate_analysis(v2_analysis('market'), 'market')
    assert 1 not in {f['criterion_id'] for f in market['findings']}


def test_missing_retained_item_does_not_acquire_a_score(v2_analysis):
    analysis = v2_analysis('market')
    item = next(f for f in analysis['findings'] if f['criterion_id'] == 6)
    item.update(status='unknown', numeric_value=None, items=[], evidence=[], reason='검증 고객 수 자료가 없습니다.')
    result = regrade.migrate_analysis(analysis, 'market')
    assert next(f for f in result['findings'] if f['criterion_id'] == 6) == item
    assert result['missing'] == ['6번: 검증 고객 수 자료가 없습니다.']
    assert item['reason'] not in result['summary']


@pytest.mark.parametrize('version', [None, '1.0', '2.1', '3.1', 'future', 2])
def test_unsupported_saved_versions_are_rejected(v2_analysis, version):
    analysis = v2_analysis('technology')
    analysis['rubric_version'] = version
    before = deepcopy(analysis)
    with pytest.raises(ValueError, match='지원하지 않는'):
        regrade.migrate_analysis(analysis, 'technology')
    assert analysis == before


@pytest.mark.parametrize('role', ['discovery', 'investment', None, 'Technology'])
def test_unknown_role_is_rejected(v2_analysis, role):
    with pytest.raises(ValueError, match='기술 또는 시장'):
        regrade.migrate_analysis(v2_analysis('technology'), role)


@pytest.mark.parametrize('key,value', [
    ('owner', 'technology'), ('field', 'items'), ('rule', 'category'),
    ('values', {'proven': 3}), ('allowed', ['payer']), ('high', 3), ('medium', 2),
    ('minimum', 1), ('integer', False), ('alternative_categories', {'guess': 3}),
    ('evidence_requirements', '출처가 없더라도 값을 추정합니다.'), ('unit', '매출액'),
])
def test_retained_rule_changes_require_new_analysis(v2_analysis, monkeypatch, key, value):
    rules = deepcopy(rubric())
    next(rule for rule in rules['criteria'] if rule['id'] == 6)[key] = value
    monkeypatch.setattr(regrade, 'rubric', lambda: rules)
    with pytest.raises(ValueError, match='채점 규칙도 변경'):
        regrade.migrate_analysis(v2_analysis('market'), 'market')


def test_display_label_and_pass_threshold_changes_do_not_reinterpret_evidence(v2_analysis, monkeypatch):
    rules = deepcopy(rubric())
    rules['pass_score'] = 11
    rules['criteria'][0].update(name='표시 이름', display_number=1, description='표시 설명')
    monkeypatch.setattr(regrade, 'rubric', lambda: rules)
    result = regrade.migrate_analysis(v2_analysis('technology'), 'technology')
    assert [f['criterion_id'] for f in result['findings']] == [2, 10]


def test_current_version_keeps_qualitative_findings(v2_analysis):
    migrated = regrade.migrate_analysis(v2_analysis('technology'), 'technology')
    before = deepcopy(migrated)
    again = regrade.migrate_analysis(migrated, 'technology')
    assert migrated == before
    assert again['findings'] == before['findings']
    assert again['qualitative_findings'] == before['qualitative_findings']
    assert again['regraded_from_version'] == '3.0'


def test_saved_run_keeps_source_review_provenance_and_uses_no_api(tmp_path, monkeypatch, v2_analysis):
    source, output = tmp_path / 'original', tmp_path / 'regraded'
    save_json(source / 'candidates.json', [{'company_id': 'demo'}])
    save_json(source / 'run_summary.json', {'demo': False})
    save_json(source / 'corpus/sources.json', [{'source_id': 'raw', 'text': '보존할 원문'}])
    review = {'method': 'Codex source comparison', 'human_reviewed': False,
              'changes': [{'company_id': 'demo', 'review_reason': '원문 인용 대조'}]}
    save_json(source / 'source_review.json', review)
    originals = {}
    for role in ('technology', 'market'):
        name = f'analyses/demo-{role}.json'
        save_json(source / name, v2_analysis(role))
        originals[name] = (source / name).read_bytes()
    class Graph:
        def get_graph(self):
            return SimpleNamespace(draw_mermaid=lambda: 'graph TD; A-->B;')
        def stream(self, state, **kwargs):
            yield {'report': {'records': [], 'passed_records': [], 'conditional_records': [],
                              'report': {'pdf_path': str(output / 'report.pdf')}}}
    def build(runtime):
        assert runtime.offline_evaluation is True
        for method in (runtime.ask, runtime.search):
            with pytest.raises(RuntimeError, match='API를 호출하지 않습니다'):
                method('forbidden')
        return Graph()
    monkeypatch.setattr(regrade, 'build_graph', build)
    result = regrade.regrade_run(source, output)
    assert result['api_cost_usd'] == 0
    assert json.loads((output / 'source_review.json').read_text()) == review
    assert (output / 'corpus/sources.json').read_bytes() == (source / 'corpus/sources.json').read_bytes()
    assert all((source / name).read_bytes() == data for name, data in originals.items())
    provenance = json.loads((output / 'regrade_provenance.json').read_text())
    assert provenance['new_api_calls'] == provenance['new_api_cost_usd'] == provenance['new_documents'] == 0
    assert len(provenance['original_analyses']) == 2
    assert all(len(item['sha256']) == 64 for item in provenance['original_analyses'])
