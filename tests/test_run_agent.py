import json
from copy import deepcopy

import evidence_audit
import run_agent
from common import save_json
from test_investment import records


class Runtime:
    def __init__(self, config, output):
        self.output_dir = output

    def ask(self, *args, **kwargs):
        raise AssertionError('실제 API 호출은 허용하지 않습니다.')


def prepare_folder(tmp_path, records):
    candidate, tech, market = records
    save_json(tmp_path / 'candidates.json', [candidate])
    for role, value in [('technology', tech), ('market', market)]:
        save_json(tmp_path / 'analyses' / f'{candidate["company_id"]}-{role}.json', value)
    return candidate


def test_individual_investment_audits_then_saves_and_evaluates(monkeypatch, tmp_path, records):
    candidate = prepare_folder(tmp_path, records)
    calls = []
    def audit(runtime, company, tech, market):
        calls.append(company['company_id'])
        tech = deepcopy(tech)
        tech['findings'][0]['status'] = 'unknown'
        tech['audit_status'] = 'completed'
        return tech, market
    monkeypatch.setattr(evidence_audit, 'audit', audit)
    monkeypatch.setattr(run_agent, 'Runtime', Runtime)
    monkeypatch.setattr('sys.argv', ['run_agent.py', 'investment', '--run', str(tmp_path)])
    run_agent.main()
    output = tmp_path / 'part-investment'
    assert calls == [candidate['company_id']]
    assert json.loads((output / 'result.json').read_text())['decision'] == 'hold'
    audited = json.loads((output / 'analyses' / f'{candidate["company_id"]}-technology.json').read_text())
    assert audited['audit_status'] == 'completed'
    assert json.loads((tmp_path / 'analyses' / f'{candidate["company_id"]}-technology.json').read_text())['findings'][0]['status'] == 'verified'


def test_individual_report_never_receives_api_writer(monkeypatch, tmp_path):
    save_json(tmp_path / 'records.json', [])
    save_json(tmp_path / 'run_summary.json', {})
    called = []
    def report(records, output, metadata):
        called.append(True)
        return {'pdf_path': str(output / 'report.pdf')}
    monkeypatch.setattr(run_agent, 'Runtime', Runtime)
    monkeypatch.setattr(run_agent.report, 'create_report', report)
    monkeypatch.setattr('sys.argv', ['run_agent.py', 'report', '--run', str(tmp_path)])
    run_agent.main()
    assert called == [True]
