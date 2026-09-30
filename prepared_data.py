import hashlib
import json
import shutil
import uuid
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from common import ROOT, save_json
from rag import Corpus

DEFAULT_REQUEST = '국내 비상장 Seed~Series C Physical AI 로봇·자율 시스템 스타트업'
FILES = ('candidates.json', 'excluded_candidates.json', 'unresolved_candidates.json', 'discovery_diagnostics.json')


def _read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _request(text):
    return ' '.join(text.split())


def _validate(folder):
    sources = _read(folder / 'corpus/sources.json')
    candidates = _read(folder / 'candidates.json')
    if not isinstance(sources, list) or not 1 <= len(sources) <= 200 or not isinstance(candidates, list):
        raise ValueError('준비 자료의 문서 수·후보 목록을 확인해 주세요.')
    ids = [s['source_id'] for s in sources]
    companies = [c['company_id'] for c in candidates]
    if len(set(ids)) != len(ids) or len(set(companies)) != len(companies):
        raise ValueError('준비 자료의 문서·기업 ID가 중복됩니다.')
    for source in sources:
        file = (folder / 'corpus' / source['file']).resolve()
        if not file.is_relative_to((folder / 'corpus').resolve()) or not file.is_file() or not source.get('text'):
            raise ValueError('준비 자료의 원문 파일 또는 본문이 없습니다.')
    for candidate in candidates:
        if not set(candidate.get('source_ids', [])).issubset(ids):
            raise ValueError('후보의 출처가 준비 자료에 없습니다.')
    if len(PdfReader(folder / 'corpus/rag-documents.pdf').pages) != len(sources):
        raise ValueError('원문 PDF 쪽수와 자료 목록이 다릅니다.')
    return sources, candidates


def store_prepared(run_dir, request, root=None):
    """완료된 문서·후보를 저장합니다. 분석 결과와 API 비용은 별도 실행 기록입니다."""
    root, run_dir = Path(root or ROOT), Path(run_dir)
    summary = run_dir / 'run_summary.json'
    if summary.exists() and _read(summary).get('demo'):
        raise ValueError('가상 예제는 실제 준비 자료로 저장할 수 없습니다.')
    sources, candidates = _validate(run_dir)
    data = root / 'data'
    temporary = data / ('.prepared-' + uuid.uuid4().hex)
    cache = data / 'prepared'
    temporary.mkdir(parents=True)
    try:
        shutil.copytree(run_dir / 'corpus', temporary / 'corpus')
        for name in FILES:
            if (run_dir / name).exists():
                shutil.copy2(run_dir / name, temporary / name)
        save_json(temporary / 'manifest.json', {
            'version': 1, 'complete': True, 'demo': False,
            'request': _request(request), 'domain': _read(root / 'config/settings.json')['domain'],
            'page_count': len(sources), 'candidate_count': len(candidates),
            'hashes': {name: _hash(temporary / name) for name in ('corpus/sources.json', 'candidates.json')},
            'source_run': run_dir.name,
        })
        if cache.exists():
            backup = data / 'prepared-backups' / uuid.uuid4().hex
            backup.parent.mkdir(parents=True, exist_ok=True)
            cache.rename(backup)
        temporary.rename(cache)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return cache


def prepare(runtime, request):
    cache = ROOT / 'data/prepared'
    if runtime.config.get('refresh_data') or not cache.exists():
        from agents import discovery
        result = discovery.run(runtime, request)
        store_prepared(runtime.output_dir, request)
        return result
    # 손상·다른 요청의 자료를 유료 재수집으로 자동 대체하지 않습니다.
    try:
        manifest = _read(cache / 'manifest.json')
        if manifest.get('version') != 1 or manifest.get('complete') is not True or manifest.get('demo') is not False:
            raise ValueError('준비 완료 자료가 아닙니다.')
        if manifest.get('request') != _request(request) or manifest.get('domain') != runtime.config['domain']:
            raise ValueError('저장 자료의 조사 조건이 다릅니다. 새 조사는 --refresh-data를 지정하세요.')
        for name in ('corpus/sources.json', 'candidates.json'):
            if manifest.get('hashes', {}).get(name) != _hash(cache / name):
                raise ValueError('준비 자료가 저장 이후 변경되었습니다.')
        sources, all_candidates = _validate(cache)
        if manifest.get('page_count') != len(sources) or manifest.get('candidate_count') != len(all_candidates):
            raise ValueError('준비 자료 개수가 일치하지 않습니다.')
    except (OSError, KeyError, TypeError, ValueError, PdfReadError) as error:
        raise ValueError(f'저장 자료를 확인해야 합니다. 자동 재수집하지 않습니다: {error}') from error
    runtime.output_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(cache / 'corpus', runtime.output_dir / 'corpus', dirs_exist_ok=True)
    for name in FILES:
        if (cache / name).exists():
            shutil.copy2(cache / name, runtime.output_dir / name)
    candidates = all_candidates[:runtime.config['max_candidates']]
    save_json(runtime.output_dir / 'candidates.json', candidates)
    runtime.corpus = Corpus(sources, runtime.config, ROOT / '.cache')
    excluded = _read(cache / 'excluded_candidates.json') if (cache / 'excluded_candidates.json').exists() else []
    unresolved = _read(cache / 'unresolved_candidates.json') if (cache / 'unresolved_candidates.json').exists() else []
    reuse = {'reused': True, 'page_count': len(sources), 'candidate_count': len(candidates), 'web_searches': 0,
             'collection_api_calls': 0, 'new_pages': 0, 'source_run': manifest['source_run']}
    save_json(runtime.output_dir / 'preparation_reuse.json', reuse)
    print(f'기존 문서 {len(sources)}쪽·후보 {len(candidates)}개 재사용 — 수집 API 호출 없음', flush=True)
    return {'candidate_list': candidates, 'doc_pages': len(sources), 'page_cap': 200,
            'prepared': {'corpus': str(runtime.output_dir / 'corpus'), 'reused': True,
                         'excluded': excluded, 'unresolved': unresolved}}
