"""Tests for the similarity_metric config surface and translation helpers."""

from __future__ import annotations

import pytest

from agentic_inquiry.storage.config import BackendConfig
from agentic_inquiry.storage.similarity import (
    DEFAULT_SIMILARITY_METRIC,
    distance_to_similarity,
    lancedb_metric,
    normalize_metric,
    opensearch_metric,
)


pytestmark = pytest.mark.unit


class TestSimilarityTranslations:
    """Canonical names translate to each backend's spelling."""

    @pytest.mark.parametrize(
        "metric,expected",
        [("cosine", "cosine"), ("l2", "l2"), ("dot", "dot")],
    )
    def test_lancedb_metric(self, metric: str, expected: str) -> None:
        assert lancedb_metric(metric) == expected


    @pytest.mark.parametrize(
        "metric,expected",
        [("cosine", "cosinesimil"), ("l2", "l2"), ("dot", "innerproduct")],
    )
    def test_opensearch_metric(self, metric: str, expected: str) -> None:
        assert opensearch_metric(metric) == expected

    def test_normalize_metric_rejects_unknown(self) -> None:
        with pytest.raises(ValueError, match="unsupported similarity_metric"):
            normalize_metric("hamming")


class TestBackendConfigSimilarityMetric:
    """BackendConfig validates similarity_metric per backend."""

    def test_default_is_cosine(self) -> None:
        cfg = BackendConfig(type="lancedb", database_path="./data")
        assert cfg.similarity_metric == DEFAULT_SIMILARITY_METRIC == "cosine"

    def test_lancedb_accepts_non_cosine(self) -> None:
        cfg = BackendConfig(
            type="lancedb",
            database_path="./data",
            similarity_metric="l2",
        )
        assert cfg.similarity_metric == "l2"


    def test_unknown_metric_is_rejected(self) -> None:
        # pydantic's Literal type enforcement catches this before the
        # model validator runs.
        with pytest.raises(ValueError, match="Input should be 'cosine', 'l2' or 'dot'"):
            BackendConfig(
                type="lancedb",
                database_path="./data",
                similarity_metric="hamming",  # type: ignore[arg-type]
            )


class TestDistanceToSimilarity:
    """pgvector distances normalize into [0, 1] scores per-metric."""

    @pytest.mark.parametrize(
        "distance,expected",
        [
            (0.0, 1.0),  # perfect match: cosine_sim = 1
            (0.5, 0.5),
            (1.0, 0.0),  # orthogonal for normalized vectors
            (2.0, 0.0),  # opposite direction — clamped to 0
            (-0.1, 1.0),  # negative distance clamped up (pgvector edge)
        ],
    )
    def test_cosine(self, distance: float, expected: float) -> None:
        assert distance_to_similarity(distance, "cosine") == pytest.approx(expected)

    @pytest.mark.parametrize(
        "distance,expected",
        [
            (0.0, 1.0),
            (1.0, 0.5),
            (3.0, 0.25),
        ],
    )
    def test_l2_monotone_in_unit_interval(
        self, distance: float, expected: float
    ) -> None:
        got = distance_to_similarity(distance, "l2")
        assert 0.0 < got <= 1.0
        assert got == pytest.approx(expected)

    @pytest.mark.parametrize(
        "distance,expected",
        [
            (-1.0, 1.0),  # pgvector <#> = -inner; inner=1 → distance=-1 → sim=1
            (0.0, 0.5),
            (1.0, 0.0),
            (-5.0, 1.0),  # unnormalized: clamped to 1
            (5.0, 0.0),  # unnormalized: clamped to 0
        ],
    )
    def test_dot(self, distance: float, expected: float) -> None:
        assert distance_to_similarity(distance, "dot") == pytest.approx(expected)

    def test_scores_are_always_in_unit_interval(self) -> None:
        """All three metrics produce scores in [0, 1] over their respective domains.

        pgvector guarantees: ``<=>`` (cosine) ∈ [0, 2], ``<->`` (l2) ∈ [0, ∞),
        ``<#>`` (-inner) ∈ (-∞, ∞). We only check within those domains.
        """
        domain = {
            "cosine": (0.0, 0.25, 0.5, 1.0, 1.5, 2.0),
            "l2": (0.0, 0.5, 1.0, 5.0, 100.0),
            "dot": (-10.0, -1.0, 0.0, 0.5, 1.0, 10.0),
        }
        for metric, distances in domain.items():
            for d in distances:
                s = distance_to_similarity(d, metric)
                assert 0.0 <= s <= 1.0, (metric, d, s)

    def test_rejects_unknown_metric(self) -> None:
        with pytest.raises(ValueError, match="unsupported similarity_metric"):
            distance_to_similarity(0.0, "hamming")


