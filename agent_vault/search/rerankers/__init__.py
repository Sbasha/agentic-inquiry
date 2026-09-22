"""Rerankers package for hybrid search result merging.

This package provides pluggable reranking strategies for combining
vector and full-text search results in hybrid search.

Available rerankers:
- RRFReranker: Reciprocal Rank Fusion (lightweight, no ML)
- LinearCombinationReranker: Weighted score combination
- CrossEncoderReranker: Joint query-document encoding (requires sentence-transformers)
- ColBERTReranker: Late interaction reranking (requires colbert-ai)
- CohereReranker: Cohere API reranking (requires API key)

Usage:
    from agent_vault.search.rerankers import get_reranker, RRFReranker

    # Via registry (recommended)
    reranker = get_reranker("rrf", {"k": 60})

    # Direct instantiation
    reranker = RRFReranker(k=60)

    # Use in hybrid search
    results = reranker.rerank(query, vector_results, fts_results)
"""
from agent_vault.search.rerankers.protocol import RerankerProtocol, SearchResult
from agent_vault.search.rerankers.registry import (
    get_reranker,
    list_rerankers,
    register_reranker,
)

# Import rerankers to trigger registration
from agent_vault.search.rerankers.rrf import RRFReranker
from agent_vault.search.rerankers.linear import LinearCombinationReranker

# Optional ML-based rerankers (may not be available)
try:
    from agent_vault.search.rerankers.cross_encoder import CrossEncoderReranker
except ImportError:
    CrossEncoderReranker = None  # type: ignore[misc, assignment]

try:
    from agent_vault.search.rerankers.colbert import ColBERTReranker
except ImportError:
    ColBERTReranker = None  # type: ignore[misc, assignment]

try:
    from agent_vault.search.rerankers.cohere import CohereReranker
except ImportError:
    CohereReranker = None  # type: ignore[misc, assignment]

__all__ = [
    # Protocol and types
    "RerankerProtocol",
    "SearchResult",
    # Registry functions
    "get_reranker",
    "list_rerankers",
    "register_reranker",
    # Reranker classes
    "RRFReranker",
    "LinearCombinationReranker",
    "CrossEncoderReranker",
    "ColBERTReranker",
    "CohereReranker",
]
