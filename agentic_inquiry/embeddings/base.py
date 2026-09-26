"""Base classes for embedder implementations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List


class Embedder(ABC):
    """Abstract base class for all embedding models."""

    @abstractmethod
    def generate(self, texts: List[str]) -> List[List[float]]:
        """Generate vector embeddings for a batch of texts."""

    async def generate_async(self, texts: List[str]) -> List[List[float]]:
        """Async version of generate for non-blocking operation.

        Default implementation runs generate in a thread pool.
        Subclasses may provide a more efficient async implementation.
        """
        import asyncio
        from concurrent.futures import ThreadPoolExecutor

        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1) as executor:
            return await loop.run_in_executor(executor, self.generate, texts)

    @abstractmethod
    def ndims(self) -> int:
        """Return the dimensionality of the embedding vector."""

    def ensure_model_loaded(self) -> None:
        """Ensure underlying model weights are ready for inference."""
        return
