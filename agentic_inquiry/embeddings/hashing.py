"""Simple deterministic hashing based embedder."""
from __future__ import annotations

import hashlib
import math
from typing import List

from agentic_inquiry.embeddings.base import Embedder


class HashingEmbedder(Embedder):
    """A lightweight embedder that derives vectors by hashing character n-grams."""

    def __init__(self, ndims: int = 128, ngram_size: int = 3):
        self._ndims = ndims
        self.ngram_size = ngram_size

    def generate(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for each supplied text."""
        return [self._embed_single(text) for text in texts]

    def _embed_single(self, content: str) -> List[float]:
        if content is None:
            raise ValueError("content must be a string")
        if not content:
            return [0.0] * self.ndims()

        vector = [0.0] * self.ndims()
        ngrams = [
            content[i : i + self.ngram_size]
            for i in range(len(content) - self.ngram_size + 1)
        ]

        if not ngrams:
            return vector

        for ngram in ngrams:
            digest = hashlib.sha256(ngram.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.ndims()
            value = (int.from_bytes(digest[4:5], "big") - 128) / 128.0
            vector[index] += value

        norm = math.sqrt(sum(component * component for component in vector))
        if norm > 0:
            vector = [component / norm for component in vector]

        return vector

    def ndims(self) -> int:
        return self._ndims
