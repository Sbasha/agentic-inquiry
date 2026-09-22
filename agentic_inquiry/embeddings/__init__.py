"""Embedding implementations and registry utilities."""

from .base import Embedder
from .hashing import HashingEmbedder
from .registry import EmbeddingRegistry, embedding_registry
from .sentence_transformer import SentenceTransformerEmbedder
from .service import EmbeddingService

__all__ = [
    "Embedder",
    "EmbeddingRegistry",
    "EmbeddingService",
    "HashingEmbedder",
    "SentenceTransformerEmbedder",
    "embedding_registry",
]
