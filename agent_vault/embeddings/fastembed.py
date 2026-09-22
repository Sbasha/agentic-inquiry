"""FastEmbed embedder implementation using qdrant/fastembed."""
from __future__ import annotations

import logging
from typing import Any, List, Optional

from agent_vault.embeddings.base import Embedder
from agent_vault.metrics import get_metrics_tracker

logger = logging.getLogger(__name__)


class FastEmbedEmbedder(Embedder):
    """Embedder implementation using the fastembed library.
    
    FastEmbed is highly optimized for CPU inference using ONNX Runtime.
    It supports many popular models like BGE, MiniLM, and multilingual-e5.
    """

    def __init__(
        self,
        model_name: str = "BAAI/bge-small-en-v1.5",
        cache_dir: Optional[str] = None,
        threads: Optional[int] = None,
        batch_size: int = 32,
        parallel: Optional[int] = None,
        **kwargs: Any
    ):
        """Initialize FastEmbed embedder.
        
        Args:
            model_name: Name of the model to use from fastembed supported models
            cache_dir: Optional directory to cache models
            threads: Optional number of threads for ONNX Runtime
            batch_size: Default batch size for encoding
            parallel: Optional number of processes for parallel encoding
            **kwargs: Additional arguments passed to TextEmbedding
        """
        self.model_name = model_name
        self.cache_dir = cache_dir
        self.threads = threads
        self.batch_size = batch_size
        self.parallel = parallel
        self.kwargs = kwargs
        
        self._model: Any = None
        self._metrics = get_metrics_tracker()
        self._ndims: Optional[int] = None
        
        logger.debug(
            "Initialized FastEmbedEmbedder with model_name=%s, batch_size=%d",
            model_name,
            batch_size
        )

    def _ensure_model_loaded(self) -> None:
        """Lazy load the FastEmbed model."""
        if self._model is not None:
            return

        try:
            from fastembed import TextEmbedding
            
            self._model = TextEmbedding(
                model_name=self.model_name,
                cache_dir=self.cache_dir,
                threads=self.threads,
                **self.kwargs
            )
            
            # Extract dimensions from the model info
            # model_obj is the underlying TextEmbedding instance
            self._ndims = self._model.model.model_out_channels
            
            logger.info(
                "FastEmbed model loaded: %s (dimensions: %d)",
                self.model_name,
                self._ndims
            )
        except ImportError:
            raise ImportError(
                "fastembed is required for FastEmbedEmbedder. "
                "Install it with: pip install fastembed"
            )
        except Exception as e:
            logger.error("Failed to load FastEmbed model '%s': %s", self.model_name, e)
            raise RuntimeError(f"Failed to load FastEmbed model: {e}") from e

    def ensure_model_loaded(self) -> None:
        """Ensure the underlying model is ready for inference."""
        self._ensure_model_loaded()

    def generate(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for a batch of texts."""
        with self._metrics.track_latency("embeddings.fastembed.generate"):
            self._ensure_model_loaded()
            
            # FastEmbed's passage_embed returns a generator of numpy arrays
            # We convert it to a list of lists for compatibility
            embeddings_gen = self._model.passage_embed(
                texts,
                batch_size=self.batch_size,
                parallel=self.parallel
            )
            
            return [emb.tolist() for emb in embeddings_gen]

    async def generate_async(self, texts: List[str]) -> List[List[float]]:
        """Async version of generate for non-blocking operation."""
        import asyncio
        from concurrent.futures import ThreadPoolExecutor
        
        # FastEmbed is CPU bound but optimized, still better to run in executor
        # to avoid blocking the main event loop
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1) as executor:
            return await loop.run_in_executor(executor, self.generate, texts)

    def ndims(self) -> int:
        """Return the dimensionality of the embedding vector."""
        if self._ndims is None:
            self._ensure_model_loaded()
        assert self._ndims is not None
        return self._ndims
