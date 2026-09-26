"""Construction tests for the fused hybrid pipeline (docs/specs/retrieval-core)."""
from __future__ import annotations

import pytest

from agentic_inquiry.config import Config
from agentic_inquiry.database.results import SearchResult
from agentic_inquiry.search.deduplicator import SearchDeduplicator
from agentic_inquiry.search.hybrid_search import MIN_CANDIDATES, HybridSearchService
from agentic_inquiry.search.rerankers.rrf import RRFReranker

pytestmark = pytest.mark.unit


def result(rid: str, path: str, score: float = 0.5) -> SearchResult:
    return SearchResult(id=rid, data={"id": rid, "file_path": path}, score=score, source="t")


class TestRRF:
    def test_plain_rank_fusion_rewards_agreement(self) -> None:
        fused = RRFReranker(k=60).rerank("q", [result("a", "x"), result("b", "y")], [result("b", "y"), result("c", "z")])
        assert [r.id for r in fused] == ["b", "a", "c"]

    def test_scores_are_relative_to_first_in_both_lists(self) -> None:
        fused = RRFReranker(k=60).rerank("q", [result("a", "x")], [result("a", "x")])
        assert fused[0].score == pytest.approx(1.0)
        only_one = RRFReranker(k=60).rerank("q", [result("a", "x")], [])
        assert only_one[0].score == pytest.approx(0.5)

    def test_raw_scores_do_not_change_order(self) -> None:
        low_first = RRFReranker().rerank("q", [result("a", "x", 0.01), result("b", "y", 0.99)], [])
        assert [r.id for r in low_first] == ["a", "b"]


def service(max_per_file: int) -> HybridSearchService:
    config = Config()
    config.search.hybrid_search.reranker_type = "rrf"
    config.search.hybrid_search.reranker_params = {"k": 60}
    return HybridSearchService(storage=None, config=config,  # type: ignore[arg-type]
                               deduplicator=SearchDeduplicator(max_results_per_file=max_per_file))


def fns(vector: list[SearchResult], fts: list[SearchResult], seen: dict[str, int]):  # type: ignore[no-untyped-def]
    async def vector_fn(**kwargs):  # type: ignore[no-untyped-def]
        seen["vector_limit"] = kwargs["limit"]
        return vector

    async def fts_fn(**kwargs):  # type: ignore[no-untyped-def]
        seen["fts_limit"] = kwargs["limit"]
        return fts

    return vector_fn, fts_fn


class TestPipeline:
    async def test_cap_applies_after_fusion_and_limit_last(self) -> None:
        vector = [result("a1", "a.py"), result("a2", "a.py"), result("b1", "b.py"), result("c1", "c.py")]
        fts = [result("a2", "a.py"), result("a1", "a.py"), result("c1", "c.py")]
        seen: dict[str, int] = {}
        vector_fn, fts_fn = fns(vector, fts, seen)
        out = await service(1).hybrid_search([0.0], "q", "q", vector_fn, fts_fn, limit=2)
        assert [r["id"] for r in out] == ["a1", "c1"]
        assert seen == {"vector_limit": MIN_CANDIDATES, "fts_limit": MIN_CANDIDATES}

    async def test_one_empty_list_keeps_the_other_order(self) -> None:
        vector_fn, fts_fn = fns([], [result("x", "x.py"), result("y", "y.py")], {})
        out = await service(3).hybrid_search([0.0], "q", "q", vector_fn, fts_fn, limit=5)
        assert [r["id"] for r in out] == ["x", "y"]

    async def test_candidate_depth_scales_with_limit(self) -> None:
        seen: dict[str, int] = {}
        vector_fn, fts_fn = fns([], [], seen)
        await service(1).hybrid_search([0.0], "q", "q", vector_fn, fts_fn, limit=50)
        assert seen["vector_limit"] == 150
