"""Embedding service with async interface."""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import List, Optional, Tuple

import numpy as np

from agentic_inquiry.config import Config
from agentic_inquiry.embeddings.base import Embedder


logger = logging.getLogger(__name__)


class EmbeddingService:
    """Service for generating embeddings.
    
    Provides async interface for embedding generation using a single
    configured embedder for all components.
    """
    
    def __init__(self, config: Config | None = None):
        """Initialize the embedding service.

        Args:
            config: Configuration instance. If None, loads default config.
        """
        self.config = config if config is not None else Config.load()
        self._embedder: Embedder | None = None
        self._warmup_thread: Optional[threading.Thread] = None
        self._warmup_complete = threading.Event()
    
    def _create_embedder(self) -> Embedder:
        """Create embedder based on configuration.
        
        Respects config.embeddings.default_provider to select the embedder type:
        - "sentence_transformer": Uses SentenceTransformerEmbedder (default)
        - "hashing": Uses HashingEmbedder for fast, deterministic embeddings
        - "local_model": Uses LocalModelEmbedder for ONNX models
        - "bedrock": Uses BedrockEmbedder for Amazon Titan v2 (RFC 0003)

        Note: this is the *second* dispatcher (the factory in
        ``embeddings/factory.py`` is the first). Both must accept the
        same provider literals — see ``docs/architecture/embeddings.md``
        § "Two EmbeddingServices" for the existing-code drift on
        "local" vs "local_model".

        Returns:
            Embedder instance configured from settings
        """
        # Check if embedding_registry has a default configured embedder (explicit override)
        from agentic_inquiry.embeddings.registry import embedding_registry

        if embedding_registry.has_default_embedder():
            embedder = embedding_registry.get_default_embedder()
            logger.info(
                "Using configured embedder from registry (%s, %d dims)",
                type(embedder).__name__,
                embedder.ndims()
            )
            return embedder

        # Respect config.embeddings.default_provider setting
        provider = self.config.embeddings.default_provider

        if provider == "hashing":
            from agentic_inquiry.embeddings.hashing import HashingEmbedder
            hashing_config = self.config.embeddings.hashing
            embedder = HashingEmbedder(
                ndims=hashing_config.ndims or self.config.embeddings.default_dimensions
            )
            logger.info(
                "Created HashingEmbedder (%d dims)",
                embedder.ndims()
            )
            return embedder

        elif provider in ("local_model", "local"):
            # Accept both the factory-side literal (``"local"``, what the
            # JSON schema enum validates) and the legacy service-side
            # literal (``"local_model"``). Without this alias, a config
            # with ``default_provider: local`` passes schema validation
            # and routes correctly through the factory but silently
            # falls back to ``SentenceTransformerEmbedder`` here. Long-
            # term cleanup is to collapse the dispatchers (cluster
            # #168); this alias keeps both literals working until then.
            from agentic_inquiry.embeddings.local_model import LocalModelEmbedder
            local_config = self.config.embeddings.local_model
            embedder = LocalModelEmbedder(
                model_path=local_config.model_path,
                ndims=local_config.ndims or self.config.embeddings.default_dimensions,
                batch_size=local_config.batch_size,
                normalize=local_config.normalize,
                config=self.config,
            )
            logger.info(
                "Created LocalModelEmbedder (%s, %d dims)",
                local_config.model_path,
                embedder.ndims()
            )
            return embedder

        elif provider == "bedrock":
            from agentic_inquiry.embeddings.bedrock import BedrockEmbedder
            from agentic_inquiry.exceptions import ConfigurationError

            bd_config = self.config.embeddings.bedrock
            if not bd_config.region:
                raise ConfigurationError(
                    "embeddings.bedrock.region is required when "
                    "default_provider == 'bedrock'. Set it in YAML or "
                    "via AI_EMBEDDINGS_BEDROCK_REGION."
                )
            embedder = BedrockEmbedder(
                region=bd_config.region,
                model_id=bd_config.model_id,
                ndims=bd_config.output_dim,
                normalize=bd_config.normalize,
                batch_size=bd_config.batch_size,
                max_retries=bd_config.max_retries,
                timeout_seconds=bd_config.timeout_seconds,
                request_concurrency=bd_config.request_concurrency,
            )
            logger.info(
                "Created BedrockEmbedder (%s, %d dims, region=%s)",
                bd_config.model_id,
                embedder.ndims(),
                bd_config.region,
            )
            return embedder

        else:  # default: sentence_transformer
            from agentic_inquiry.embeddings.sentence_transformer import SentenceTransformerEmbedder
            embedder = SentenceTransformerEmbedder(
                model_name=self.config.embeddings.sentence_transformer.model_name,
                ndims=self.config.embeddings.default_dimensions
            )
            logger.info(
                "Created SentenceTransformerEmbedder (%s, %d dims)",
                self.config.embeddings.sentence_transformer.model_name,
                self.config.embeddings.default_dimensions
            )
            return embedder
    
    def _get_embedder(self) -> Embedder:
        """Get or create the embedder instance.
        
        Returns:
            Embedder instance
        """
        if self._embedder is None:
            self._embedder = self._create_embedder()
        return self._embedder
    
    async def embed_async(self, text: str) -> np.ndarray:
        """Generate embedding for a single text.

        Args:
            text: Text to embed

        Returns:
            Embedding vector as numpy array
        """
        from agentic_inquiry.executors import get_embedding_executor

        embedder = self._get_embedder()
        # Note: Do NOT call ensure_model_loaded() here - it's blocking!
        # The generate() method calls it internally within the executor.

        # Run embedding generation in dedicated executor to avoid blocking
        loop = asyncio.get_running_loop()
        embeddings = await loop.run_in_executor(
            get_embedding_executor(),
            embedder.generate,
            [text]
        )

        return np.array(embeddings[0], dtype=np.float32)
    
    async def embed_batch_async(self, texts: List[str]) -> List[np.ndarray]:
        """Generate embeddings for multiple texts.

        Args:
            texts: List of texts to embed

        Returns:
            List of embedding vectors as numpy arrays
        """
        from agentic_inquiry.executors import get_embedding_executor

        embedder = self._get_embedder()
        # Note: Do NOT call ensure_model_loaded() here - it's blocking!
        # The generate() method calls it internally within the executor.

        # Run embedding generation in dedicated executor to avoid blocking
        loop = asyncio.get_running_loop()
        embeddings = await loop.run_in_executor(
            get_embedding_executor(),
            embedder.generate,
            texts
        )

        return [np.array(emb, dtype=np.float32) for emb in embeddings]
    
    def get_dimensions(self) -> int:
        """Get vector dimensions for embeddings.

        Returns:
            Number of dimensions
        """
        embedder = self._get_embedder()
        return embedder.ndims()

    def start_background_warmup(self) -> None:
        """Start loading the embedding model in a background thread.

        This allows the server to start accepting requests immediately while
        the model loads in parallel. The first query that needs embeddings
        will wait for warmup to complete (via the embedder's internal lock).

        Thread safety is handled by the embedder's _load_lock - concurrent
        access during warmup is safe.

        Example:
            >>> service = EmbeddingService(config)
            >>> service.start_background_warmup()  # Returns immediately
            >>> # ... server starts, model loads in background ...
            >>> await service.embed_async("query")  # Waits if still loading
        """
        if self._warmup_thread is not None and self._warmup_thread.is_alive():
            logger.debug("Background warmup already in progress")
            return

        def _warmup() -> None:
            try:
                logger.info("Background warmup: Loading embedding model...")
                embedder = self._get_embedder()
                embedder.ensure_model_loaded()
                logger.info(
                    "Background warmup complete: %s (%d dimensions)",
                    getattr(embedder, 'model_name', type(embedder).__name__),
                    embedder.ndims()
                )
            except Exception as e:
                logger.error("Background warmup failed: %s", e)
            finally:
                self._warmup_complete.set()

        self._warmup_thread = threading.Thread(
            target=_warmup,
            name="embedding-warmup",
            daemon=True
        )
        self._warmup_thread.start()
        logger.info("Started background embedding model warmup")

    def is_warmup_complete(self) -> bool:
        """Check if background warmup has completed.

        Returns:
            True if warmup is complete or was never started
        """
        return self._warmup_complete.is_set() or self._warmup_thread is None

    async def wait_for_warmup(self, timeout: float = 30.0) -> bool:
        """Wait for background warmup to complete.

        Args:
            timeout: Maximum seconds to wait

        Returns:
            True if warmup completed, False if timeout
        """
        if self._warmup_thread is None:
            return True

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            self._warmup_complete.wait,
            timeout
        )

    def get_embedder_configuration(
        self,
        table_name: str,
        column_name: str
    ) -> Tuple[Embedder, int]:
        """Get embedder configuration for a specific table/column.
        
        This method is used by parsers to get the configured embedder.
        
        Args:
            table_name: Target table name (e.g. "graph_entities")
            column_name: Target column name (e.g. "vector")
            
        Returns:
            Tuple of (Embedder instance, dimension count)
        """
        embedder = self._get_embedder()
        return embedder, embedder.ndims()

    async def generate_embeddings_batch(
        self,
        texts: List[str],
        embedder: Optional[Embedder] = None,
        purpose: str = "batch",
    ) -> List[np.ndarray]:
        """Generate embeddings for a batch of texts.
        
        Alias for embed_batch_async with additional context logging.
        
        Args:
            texts: List of texts to embed
            embedder: Optional specific embedder (ignored in this implementation,
                     uses the service's configured embedder for consistency)
            purpose: Description of operation for logging
            
        Returns:
            List of embedding vectors as numpy arrays
        """
        if not texts:
            return []
            
        # Log large batches
        if len(texts) > 100:
            logger.info(
                "Generating embeddings for %d texts (purpose: %s)",
                len(texts), purpose
            )
            
        return await self.embed_batch_async(texts)
