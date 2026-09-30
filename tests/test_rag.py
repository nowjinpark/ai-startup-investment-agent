import pytest

from demo import DemoEmbeddings
from evaluate_retrieval import evaluate
from rag import Corpus


def source(key, owner, role, text, doc_types=None):
    return {
        "source_id": key, "company_id": owner, "doc_type": role,
        "doc_types": doc_types or [role], "text": text,
        "title": "검색 범위 시험 자료", "url": f"https://example.org/{key}",
    }


def corpus(sources, cache, top_k=20):
    return Corpus(
        sources,
        {"embedding_model": "demo-hash-v1", "chunk_size": 1000, "chunk_overlap": 0, "top_k": top_k},
        cache,
        embeddings=DemoEmbeddings(),
    )


def ids(chunks):
    return {chunk["source_id"] for chunk in chunks}


@pytest.fixture
def scoped_corpus(tmp_path):
    return corpus([
        source("a-company", "a", "company", "alpha robot company founder sales"),
        source("a-tech", "a", "technology", "alpha robot navigation control"),
        source("a-market", "a", "market", "alpha robot paying customers"),
        source("a-shared", "a", "technology", "alpha robot field operations", ["technology", "market"]),
        source("b-company", "b", "company", "robot robot robot company founder"),
        source("b-tech", "b", "technology", "robot robot robot navigation"),
        source("b-market", "b", "market", "robot robot robot customers"),
        source("sector", "__sector__", "market", "robot robot domestic market growth"),
        source("discovery", "__discovery__", "company", "robot robot startup investment candidates"),
    ], tmp_path / "cache")


def test_same_company_basic_material_is_shared_by_both_roles(scoped_corpus):
    technology = scoped_corpus.retrieve("robot", "a", "technology")
    market = scoped_corpus.retrieve("robot", "a", "market")
    assert ids(technology) == {"a-company", "a-tech", "a-market", "a-shared"}
    assert ids(market) == {"a-company", "a-tech", "a-market", "a-shared", "sector"}
    assert "b-company" not in ids(technology + market)
    assert "discovery" not in ids(technology + market)


def test_sector_material_is_available_only_to_market(scoped_corpus):
    assert "sector" in ids(scoped_corpus.retrieve("robot", "a", "market"))
    assert "sector" not in ids(scoped_corpus.retrieve("robot", "a", "technology"))
    assert "sector" not in ids(scoped_corpus.retrieve("robot", "a", "company"))


def test_company_discovery_can_search_all_company_material(scoped_corpus):
    assert ids(scoped_corpus.retrieve("robot", None, "company")) == {
        "a-company", "b-company", "discovery",
    }
    assert ids(scoped_corpus.retrieve("robot", "a", "company")) == {"a-company", "a-tech", "a-market", "a-shared"}


def test_real_faiss_is_built_and_k_is_honored(scoped_corpus):
    from langchain_community.vectorstores import FAISS

    results = scoped_corpus.retrieve("robot", "a", "technology", k=1)
    assert len(results) == 1
    assert results[0]["company_id"] == "a"
    assert isinstance(scoped_corpus.indexes[("a", "technology")], FAISS)
    assert scoped_corpus.history[-1]["source_ids"] == [results[0]["source_id"]]


def test_empty_scope_and_empty_corpus_return_no_evidence(scoped_corpus, tmp_path):
    assert scoped_corpus.retrieve("robot", "missing-company", "technology") == []
    assert scoped_corpus.retrieve("robot", "missing-company", "company") == []
    # 시장 공통 자료가 없으면 시장 범위도 비어 있습니다.
    empty = corpus([], tmp_path / "empty")
    assert empty.retrieve("robot", "a", "market") == []
    assert empty.evidence_for(["robot", "customer"], "a", "technology") == []
    assert empty.source_pages([]) == []


def test_multiple_questions_do_not_duplicate_evidence(scoped_corpus):
    chunks = scoped_corpus.evidence_for(["robot", "robot", "navigation"], "a", "technology")
    assert len({chunk["chunk_id"] for chunk in chunks}) == len(chunks)
    assert ids(chunks) == {"a-company", "a-tech", "a-market", "a-shared"}
    pages = scoped_corpus.source_pages(chunks + chunks)
    assert len(pages) == 4


def test_hit_rate_and_mrr_use_returned_rank_and_company_scope(tmp_path):
    data = corpus([
        source("a-first", "a", "technology", "robot robot"),
        source("a-second", "a", "technology", "robot robotics"),
        source("a-third", "a", "technology", "robotics robotics"),
        source("b-first", "b", "technology", "robot robot"),
    ], tmp_path / "metrics", top_k=2)
    # 해시 임베딩도 실제 FAISS의 정렬과 필터링 경로를 사용합니다.
    assert DemoEmbeddings().embed_query("robot") != DemoEmbeddings().embed_query("robotics")
    assert [c["source_id"] for c in data.retrieve("robot", "a", "technology", k=2)] == ["a-first", "a-second"]
    result = evaluate(data, [
        {"question": "robot", "company_id": "a", "doc_type": "technology", "expected_source_ids": ["a-second"]},
        {"question": "robotics", "company_id": "a", "doc_type": "technology", "expected_source_ids": ["a-third"]},
        {"question": "robot", "company_id": "a", "doc_type": "technology", "expected_source_ids": ["b-first"]},
    ], k=2)
    assert result["hit_rate"] == pytest.approx(2 / 3)
    assert result["mrr_at_k"] == pytest.approx((0.5 + 1 + 0) / 3)
    assert [item["reciprocal_rank"] for item in result["details"]] == [0.5, 1, 0]
    assert all("b-first" not in item["retrieved_source_ids"] for item in result["details"])


def test_evaluation_requires_existing_answer_sources(scoped_corpus):
    with pytest.raises(ValueError):
        evaluate(scoped_corpus, [], k=4)
    for expected in [[], ["missing"]]:
        with pytest.raises(ValueError):
            evaluate(scoped_corpus, [{"question": "robot", "company_id": "a", "doc_type": "technology", "expected_source_ids": expected}], k=4)


def test_qualification_can_use_every_role_without_other_company(scoped_corpus):
    assert ids(scoped_corpus.retrieve("robot", "a", None)) == {"a-company", "a-tech", "a-market", "a-shared"}

def test_empty_retrieval_is_also_logged(scoped_corpus):
    scoped_corpus.retrieve("robot", "missing", "technology")
    assert scoped_corpus.history[-1]["source_ids"] == []
