"""Canonical similarity metric names and per-backend translations.

Agentic Inquiry exposes a single canonical vocabulary for similarity metrics
(``cosine``, ``l2``, ``dot``) so callers never have to know which backend a
config value ends up in. Each backend spells its metrics differently, so this
module provides a small translation layer.

Mappings:
    ``cosine``
        - LanceDB: ``cosine``
        - pgvector operator class: ``vector_cosine_ops`` (distance op: ``<=>``)
        - OpenSearch k-NN: ``cosinesimil``
    ``l2``
        - LanceDB: ``l2``
        - pgvector operator class: ``vector_l2_ops`` (distance op: ``<->``)
        - OpenSearch k-NN: ``l2``
    ``dot``
        - LanceDB: ``dot``
        - pgvector operator class: ``vector_ip_ops`` (distance op: ``<#>``)
        - OpenSearch k-NN: ``innerproduct``

Example:
    >>> from agentic_inquiry.storage.similarity import lancedb_metric
    >>> lancedb_metric("cosine")
    'cosine'
"""

from __future__ import annotations

from typing import Literal


SimilarityMetric = Literal["cosine", "l2", "dot"]
"""Canonical set of similarity metric names accepted by Agentic Inquiry config."""

DEFAULT_SIMILARITY_METRIC: SimilarityMetric = "cosine"
"""Default metric, preserving historical cosine behaviour."""

SUPPORTED_METRICS: frozenset[str] = frozenset(("cosine", "l2", "dot"))


_LANCEDB_METRICS: dict[str, str] = {
    "cosine": "cosine",
    "l2": "l2",
    "dot": "dot",
}

_PGVECTOR_OPERATOR_CLASSES: dict[str, str] = {
    "cosine": "vector_cosine_ops",
    "l2": "vector_l2_ops",
    "dot": "vector_ip_ops",
}

_PGVECTOR_DISTANCE_OPERATORS: dict[str, str] = {
    "cosine": "<=>",
    "l2": "<->",
    "dot": "<#>",
}

_OPENSEARCH_METRICS: dict[str, str] = {
    "cosine": "cosinesimil",
    "l2": "l2",
    "dot": "innerproduct",
}


def normalize_metric(metric: str) -> SimilarityMetric:
    """Validate and return the canonical name.

    Args:
        metric: Candidate metric name.

    Returns:
        The canonical name, unchanged when valid.

    Raises:
        ValueError: If ``metric`` is not one of ``SUPPORTED_METRICS``.
    """
    if metric not in SUPPORTED_METRICS:
        raise ValueError(
            f"unsupported similarity_metric '{metric}'. "
            f"Supported: {sorted(SUPPORTED_METRICS)}"
        )
    return metric  # type: ignore[return-value]


def lancedb_metric(metric: str) -> str:
    """Return the LanceDB ``create_index(metric=...)`` value."""
    return _LANCEDB_METRICS[normalize_metric(metric)]


def pgvector_operator_class(metric: str) -> str:
    """Return the pgvector operator-class name (e.g. ``vector_cosine_ops``)."""
    return _PGVECTOR_OPERATOR_CLASSES[normalize_metric(metric)]


def pgvector_distance_operator(metric: str) -> str:
    """Return the pgvector distance operator (e.g. ``<=>``)."""
    return _PGVECTOR_DISTANCE_OPERATORS[normalize_metric(metric)]


def opensearch_metric(metric: str) -> str:
    """Return the OpenSearch k-NN ``space_type`` value."""
    return _OPENSEARCH_METRICS[normalize_metric(metric)]


def distance_to_similarity(distance: float, metric: str) -> float:
    """Map a raw pgvector distance to a ``[0, 1]`` similarity score.

    pgvector returns a raw distance via its operators: ``<=>`` is cosine
    distance (``1 - cosine_similarity``), ``<->`` is Euclidean distance,
    ``<#>`` is negative inner product. None of those are directly usable as
    a [0, 1] score — callers want "1 means perfect match, 0 means no
    match". Each metric gets its own monotone mapping:

    - ``cosine`` → ``1 - distance``, clamped to ``[0, 1]``.
    - ``l2`` → ``1 / (1 + distance)`` (naturally in ``(0, 1]``).
    - ``dot`` → ``(1 - distance) / 2``, clamped. Well-defined for
      normalized vectors (distance ∈ ``[-1, 1]``); for unnormalized
      vectors it still preserves the ordering but loses interpretability.
    """
    m = normalize_metric(metric)
    if m == "cosine":
        return max(0.0, min(1.0, 1.0 - distance))
    if m == "l2":
        return 1.0 / (1.0 + distance)
    # dot: pgvector <#> returns -inner_product; for normalized vectors
    # distance ∈ [-1, 1], so (1 - d)/2 ∈ [0, 1].
    return max(0.0, min(1.0, (1.0 - distance) / 2.0))
