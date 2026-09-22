# Reranker Development Guide

This guide explains how to implement a custom reranker for hybrid search in Agentic Inquiry.

## Overview

Rerankers merge and reorder results from multiple search strategies (vector, FTS, graph) into a single ranked list. They operate post-retrieval—after the adapter has returned raw results.

**Key files:**
- `agentic_inquiry/search/rerankers/protocol.py` - RerankerProtocol interface
- `agentic_inquiry/search/rerankers/rrf.py` - RRF reference implementation
- `agentic_inquiry/search/rerankers/linear.py` - Linear combination reranker
- `agentic_inquiry/search/rerankers/registry.py` - Reranker registration
- `docs/design/ownership-and-extension-points.md` - Ownership boundaries

---

## RerankerProtocol

All rerankers implement this protocol:

```python
@runtime_checkable
class RerankerProtocol(Protocol):
    """Pluggable reranker strategy for hybrid search."""

    def rerank(
        self,
        query: str,
        vector_results: List[SearchResult],
        fts_results: List[SearchResult],
        config: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        """Merge and rerank results from multiple search strategies.

        Args:
            query: Original query string (for cross-encoder reranking)
            vector_results: Results from vector search (scores 0-1)
            fts_results: Results from FTS search (scores 0-1)
            config: Strategy-specific configuration overrides

        Returns:
            Merged, reranked results with normalized scores (0.0-1.0)
        """
        ...
```

### Key Contracts

1. **Input scores are normalized** (0.0-1.0) from the adapter
2. **Output scores MUST be normalized** to 0.0-1.0
3. **Preserve result identity** - same `SearchResult.id` in, same out
4. **No database access** - rerankers only transform in-memory results

---

## SearchResult Type

Rerankers work with the canonical `SearchResult`:

```python
from agentic_inquiry.database.results import SearchResult

@dataclass(frozen=True)
class SearchResult:
    id: str                           # Unique identifier
    score: float                      # Normalized 0.0-1.0
    data: Dict[str, Any]              # Full record data
    source: Optional[str] = None      # Source identifier
```

**Helper methods:**
- `result.with_score(new_score, source="reranker_name")` - Return copy with updated score
- `result.with_data(new_data)` - Return copy with updated data

---

## Score Normalization

This is critical. All output scores MUST be in the 0.0-1.0 range.

### Min-Max Normalization

The most common approach:

```python
def normalize_scores(results: List[SearchResult], source: str) -> List[SearchResult]:
    """Normalize scores to 0.0-1.0 using min-max."""
    if not results:
        return []

    scores = [r.score for r in results]
    min_score = min(scores)
    max_score = max(scores)

    # Handle single result or all-equal scores
    if max_score == min_score:
        return [r.with_score(1.0, source=source) for r in results]

    score_range = max_score - min_score
    return [
        r.with_score((r.score - min_score) / score_range, source=source)
        for r in results
    ]
```

### Edge Cases

| Scenario | Handling |
|----------|----------|
| Empty results | Return empty list |
| Single result | Score = 1.0 |
| All equal scores | All scores = 1.0 |
| Already 0-1 | Still normalize (maintains consistency) |

---

## Available Rerankers

### RRF (Reciprocal Rank Fusion)

Lightweight, deterministic, no ML required:

```python
# Formula: score = sum(weight / (k + rank)) for each result
# k=60 is the standard constant

@register_reranker("rrf")
class RRFReranker(RerankerProtocol):
    def __init__(self, k: int = 60):
        self.k = k
```

Best for: Most use cases, fast, reliable.

### Linear Combination

Weighted average of scores:

```python
# Formula: score = vector_weight * vector_score + fts_weight * fts_score

@register_reranker("linear_combination")
class LinearCombinationReranker(RerankerProtocol):
    pass
```

Best for: When you have calibrated score distributions.

### Cross-Encoder (ML-based)

Uses an ML model to score query-document pairs:

```python
@register_reranker("cross_encoder")
class CrossEncoderReranker(RerankerProtocol):
    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        self._model = CrossEncoder(model_name)
```

Best for: Maximum relevance quality, when latency allows.

---

## Registry

Register rerankers using the decorator:

```python
from agentic_inquiry.search.rerankers.registry import register_reranker

@register_reranker("my_reranker")
class MyReranker(RerankerProtocol):
    ...
```

Retrieve rerankers:

```python
from agentic_inquiry.search.rerankers.registry import get_reranker

reranker = get_reranker("rrf")
```

---

## Example: Custom Reranker

Here's a complete example implementing a boost-based reranker:

```python
"""Custom reranker that boosts results matching specific criteria."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from agentic_inquiry.search.rerankers.protocol import RerankerProtocol, SearchResult
from agentic_inquiry.search.rerankers.registry import register_reranker


@register_reranker("boost_reranker")
class BoostReranker(RerankerProtocol):
    """Reranker that boosts results based on metadata criteria.

    Applies a multiplicative boost to results matching specified criteria,
    then renormalizes to 0.0-1.0.

    Example:
        >>> reranker = BoostReranker(
        ...     boost_field="content_type",
        ...     boost_values=["text/markdown", "text/x-python"],
        ...     boost_factor=1.5,
        ... )
        >>> merged = reranker.rerank(query, vector_results, fts_results)
    """

    def __init__(
        self,
        boost_field: str = "content_type",
        boost_values: Optional[List[str]] = None,
        boost_factor: float = 1.5,
        k: int = 60,  # RRF constant for initial merge
    ):
        """Initialize boost reranker.

        Args:
            boost_field: Field in result.data to check for boost.
            boost_values: Values that trigger boost. None = no boost.
            boost_factor: Multiplicative factor for boosted results.
            k: RRF constant for initial result merging.
        """
        self.boost_field = boost_field
        self.boost_values = set(boost_values or [])
        self.boost_factor = boost_factor
        self.k = k

    def rerank(
        self,
        query: str,
        vector_results: List[SearchResult],
        fts_results: List[SearchResult],
        config: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        """Merge with RRF, then apply boosts, then renormalize.

        Args:
            query: Original query string (not used)
            vector_results: Results from vector search
            fts_results: Results from FTS search
            config: Optional overrides (boost_factor, boost_values)

        Returns:
            Reranked results with normalized scores (0.0-1.0)
        """
        config = config or {}

        # Get config overrides
        boost_factor = config.get("boost_factor", self.boost_factor)
        boost_values = set(config.get("boost_values", self.boost_values))

        # Step 1: Merge using RRF
        merged = self._rrf_merge(vector_results, fts_results, config)

        if not merged:
            return []

        # Step 2: Apply boosts
        boosted_results: List[tuple[SearchResult, float]] = []
        for result in merged:
            field_value = result.data.get(self.boost_field)
            if field_value in boost_values:
                boosted_score = result.score * boost_factor
            else:
                boosted_score = result.score
            boosted_results.append((result, boosted_score))

        # Step 3: Sort by boosted score
        boosted_results.sort(key=lambda x: x[1], reverse=True)

        # Step 4: Renormalize to 0.0-1.0
        return self._normalize([
            (r, s) for r, s in boosted_results
        ])

    def _rrf_merge(
        self,
        vector_results: List[SearchResult],
        fts_results: List[SearchResult],
        config: Dict[str, Any],
    ) -> List[SearchResult]:
        """Initial merge using RRF."""
        vector_weight = config.get("vector_weight", 0.7)
        fts_weight = config.get("fts_weight", 0.3)

        scores: Dict[str, float] = {}
        result_map: Dict[str, SearchResult] = {}

        for rank, result in enumerate(vector_results):
            rrf_score = vector_weight / (self.k + rank + 1)
            scores[result.id] = scores.get(result.id, 0.0) + rrf_score
            result_map[result.id] = result

        for rank, result in enumerate(fts_results):
            rrf_score = fts_weight / (self.k + rank + 1)
            scores[result.id] = scores.get(result.id, 0.0) + rrf_score
            if result.id not in result_map:
                result_map[result.id] = result

        ranked_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
        return [
            result_map[id_].with_score(scores[id_], source="boost_rrf")
            for id_ in ranked_ids
        ]

    def _normalize(
        self, results: List[tuple[SearchResult, float]]
    ) -> List[SearchResult]:
        """Normalize boosted scores to 0.0-1.0."""
        if not results:
            return []

        scores = [s for _, s in results]
        min_score = min(scores)
        max_score = max(scores)

        if max_score == min_score:
            return [r.with_score(1.0, source="boost_reranker") for r, _ in results]

        score_range = max_score - min_score
        return [
            r.with_score((s - min_score) / score_range, source="boost_reranker")
            for r, s in results
        ]
```

---

## Configuration

Configure rerankers in `agentic-inquiry.yaml`:

```yaml
search:
  hybrid_search:
    reranker_type: "rrf"  # Or "linear_combination", "cross_encoder", "boost_reranker"
    vector_weight: 0.7
    fts_weight: 0.3

    # Reranker-specific options (passed to config dict)
    rrf_k: 60
    boost_field: "content_type"
    boost_values: ["text/markdown"]
```

---

## Testing Rerankers

### Basic Protocol Compliance

```python
def test_protocol_compliance():
    reranker = MyReranker()
    assert isinstance(reranker, RerankerProtocol)

def test_empty_inputs():
    reranker = MyReranker()
    result = reranker.rerank("query", [], [])
    assert result == []

def test_single_result():
    reranker = MyReranker()
    result = reranker.rerank(
        "query",
        [SearchResult(id="1", score=0.5, data={})],
        [],
    )
    assert len(result) == 1
    assert result[0].score == 1.0  # Normalized
```

### Score Normalization

```python
def test_scores_normalized():
    reranker = MyReranker()
    result = reranker.rerank("query", vector_results, fts_results)

    for r in result:
        assert 0.0 <= r.score <= 1.0, f"Score {r.score} out of range"
```

### Result Identity Preservation

```python
def test_preserves_ids():
    reranker = MyReranker()
    input_ids = {r.id for r in vector_results + fts_results}
    result = reranker.rerank("query", vector_results, fts_results)
    output_ids = {r.id for r in result}

    # All output IDs should come from inputs
    assert output_ids <= input_ids
```

### Determinism

```python
def test_deterministic():
    reranker = MyReranker()
    result1 = reranker.rerank("query", vector_results, fts_results)
    result2 = reranker.rerank("query", vector_results, fts_results)

    assert [r.id for r in result1] == [r.id for r in result2]
    assert [r.score for r in result1] == [r.score for r in result2]
```

---

## Ownership Boundaries

From `docs/design/ownership-and-extension-points.md`:

**Reranker Layer Owns:**
- Post-retrieval ordering
- Score normalization to 0.0-1.0
- Result identity preservation
- ML inference (for cross-encoder)

**Reranker Layer Does NOT Own:**
- Database access (no fetching more rows)
- Business-level boosting rules (those are app-layer)
- Filter application (that's adapter layer)

---

## Implementation Checklist

- [ ] Implement `RerankerProtocol.rerank()`
- [ ] Normalize output scores to 0.0-1.0
- [ ] Handle edge cases (empty, single, equal scores)
- [ ] Preserve result identity (same IDs)
- [ ] Register with `@register_reranker("name")`
- [ ] Add configuration to `config/default.yaml`
- [ ] Write protocol compliance tests
- [ ] Document configuration options

---

## See Also

- `docs/design/ownership-and-extension-points.md` - Ownership boundaries
- `agentic_inquiry/search/rerankers/rrf.py` - RRF reference implementation
- `agentic_inquiry/search/rerankers/linear.py` - Linear combination example
- `tests/search/test_rerankers.py` - Test patterns
