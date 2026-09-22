# Result Contract (Canonical SearchResult)

This document defines the ONE canonical result type for the system: `SearchResult`.

It must align with the “Canonical Result Contract” section in `docs/design/database-abstraction-revised.md`:

> DO NOT create SearchResultV2, NormalizedResult, RankedResult, etc.

## Why this exists

Different backends return different score formats (distance vs similarity) and different payload shapes. A single canonical result type prevents drift across adapters, rerankers, deduplicators, and consumers.

## Canonical Type

```python
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True, slots=True)
class SearchResult:
    """
    Canonical search result - the ONLY result type in the system.

    Used at ALL boundaries:
    - Adapter returns List[SearchResult]
    - Reranker accepts and returns List[SearchResult]
    - SearchService returns List[SearchResult] to consumers
    """

    id: str
    data: Dict[str, Any]             # Original row/document data
    score: float                     # Normalized: 0.0 (worst) to 1.0 (best)
    source: str = "unknown"          # Provenance: "vector", "fts", "hybrid", "filter", "graph"
    distance: Optional[float] = None # Raw distance if applicable (debugging only)
```

## Score Semantics

### Backend score variance

| Backend | Typical score | Range | Higher = better? |
|---------|---------------|-------|------------------|
| LanceDB | distance (`_distance`) | 0..inf | No |
| Pinecone | similarity | 0..1 | Yes |
| Weaviate | certainty | 0..1 | Yes |
| Qdrant | score | 0..1 | Yes |

### Adapter normalization requirements

Adapters must return `SearchResult` with `score` normalized to **0.0..1.0** for:
- `vector_search`
- `fts_search` (if applicable)
- `hybrid_search` (if native hybrid is supported)
- `query`/filter-only queries (set `score=1.0` by default unless a meaningful score exists)

If the backend provides a distance (lower is better), convert to similarity:
- `score = 1 / (1 + distance)` (distance ≥ 0)
- set `distance` for debugging

If the backend provides a similarity in [0, 1]:
- set `score=similarity`
- leave `distance=None`

## Reranking Semantics (Single Type)

Rerankers must accept `List[SearchResult]` and return `List[SearchResult]`.

If a reranker computes an unbounded intermediate score (e.g. raw RRF sums), it must **renormalize** to 0.0..1.0 before returning `SearchResult` objects to preserve the canonical invariant.

Recommended approach:
- compute intermediate fused scores
- normalize fused scores via min-max into 0..1
- set `source` to reflect the rerank path (e.g. `"hybrid"`, `"cross_encoder"`)

## Deduplication Contract

Deduplication keys are based on `SearchResult.id`.
- If a backend cannot provide stable `id`, it is not adapter-compliant for this system.

## Required Adapter Documentation

For each new adapter, document:
- which backend-native scoring fields are used (distance vs similarity)
- the exact normalization function to produce `SearchResult.score`
- capability degradation behavior (e.g. no FTS, no offsets)
