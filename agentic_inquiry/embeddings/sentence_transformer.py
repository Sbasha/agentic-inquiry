"""Sentence-transformer-backed embedder with CUDA autodetection and opt-in MPS."""

from __future__ import annotations

import logging
import os
import threading
from typing import List, Optional

import numpy as np

from agentic_inquiry.embeddings.base import Embedder
from agentic_inquiry.metrics import get_metrics_tracker

logger = logging.getLogger(__name__)

# Operator pin: set to ``cpu`` / ``cuda`` / ``mps`` to skip autodetect.
# ``mps`` is only ever used through this variable; see ``_select_device``.
_DEVICE_ENV_VAR = "INQUIRY_EMBEDDING_DEVICE"

_KNOWN_DEVICES = frozenset({"cpu", "cuda", "mps"})


def _select_device(preferred: Optional[str] = None) -> str:
    """Pick the torch device for the embedding model.

    Order: explicit ``preferred`` (if a recognised device string) → CUDA →
    CPU.

    Apple MPS is never autodetected. Indexing embeds from a thread pool,
    and torch's MPS stream aborts the whole process under that load with a
    Metal command-buffer assertion, which no Python-level fallback can
    catch. CPU is slower on Apple Silicon but finishes. Operators who want
    Metal opt in with ``INQUIRY_EMBEDDING_DEVICE=mps``.

    ``preferred`` is normalised to lowercase and rejected with a warning if
    it isn't a known device; autodetect then applies. Known values pass
    through without availability checks so the pin can force a device even
    if detection misreports it; the model-load fallback in
    ``_ensure_model_loaded`` catches a device that fails at placement.
    """
    try:
        import torch
    except ImportError:
        return "cpu"

    if preferred:
        normalised = preferred.strip().lower()
        if normalised in _KNOWN_DEVICES:
            return normalised
        logger.warning(
            "Ignoring unknown preferred device %r; expected one of %s. "
            "Falling through to autodetect.",
            preferred,
            sorted(_KNOWN_DEVICES),
        )

    if torch.cuda.is_available():
        return "cuda"

    return "cpu"


class SentenceTransformerEmbedder(Embedder):
    """Embedder using sentence-transformers library for semantic embeddings."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2", ndims: int = 384):
        self.model_name = model_name
        self._ndims = ndims
        self._metrics = get_metrics_tracker()
        self._model = None
        self._load_lock = threading.Lock()

    def ensure_model_loaded(self) -> None:
        """Ensure the underlying model is ready for inference."""
        self._ensure_model_loaded()

    def _ensure_model_loaded(self):
        """Lazy load the sentence transformer model.

        Three-stage sequence, in order, so each failure mode surfaces a
        distinct and actionable error:

        1. **Select the target device.** ``_select_device`` handles
           torch-missing internally (returns ``"cpu"``), so this step
           never raises. Doing it up front means the device choice
           doesn't depend on sentence-transformers being importable —
           simpler to reason about, and a future refactor that changes
           the ImportError handling below can't silently break device
           selection.
        2. **Import sentence-transformers.** If missing, re-raise with
           an install hint; other ImportErrors propagate.
        3. **Load the model on the chosen device**, with CPU fallback
           for the MPS/CUDA "available but model placement fails" case
           (seen on older macOS and torch nightlies).
        """
        if self._model is not None:
            return

        with self._load_lock:
            if self._model is not None:
                return

            # Stage 1: pick a device. No raise path — worst case is CPU.
            preferred = os.environ.get(_DEVICE_ENV_VAR) or None
            device = _select_device(preferred=preferred)

            # Stage 2: import the library. Friendly message if missing.
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as e:
                if "sentence_transformers" in str(e):
                    raise ImportError(
                        "sentence-transformers is required for semantic embeddings. "
                        "Install it with: pip install sentence-transformers"
                    )
                raise

            # Stage 3: load the model. Fall back to CPU if the chosen
            # accelerator claims availability but fails at placement.
            try:
                self._model = SentenceTransformer(self.model_name, device=device)
                logger.debug(
                    "SentenceTransformerEmbedder loaded model=%s device=%s",
                    self.model_name,
                    device,
                )
            except Exception as e:
                # MPS / CUDA can claim availability but raise on actual
                # model placement (memory layout, meta-tensor issues,
                # driver mismatches). Retry on CPU so the embedder still
                # works — users see degraded throughput, not hard failure.
                if device == "cpu":
                    raise
                logger.warning(
                    "SentenceTransformerEmbedder failed to load on device=%s "
                    "(%s: %s); falling back to CPU. Set %s=cpu to pin CPU up "
                    "front and skip the failed attempt on subsequent runs.",
                    device,
                    type(e).__name__,
                    e,
                    _DEVICE_ENV_VAR,
                )
                self._model = SentenceTransformer(self.model_name, device="cpu")

    def generate(self, texts: List[str]) -> List[List[float]]:
        with self._metrics.track_latency("embeddings.generate"):
            self._ensure_model_loaded()
            assert self._model is not None, "Model not loaded"

            # Validate inputs
            for text in texts:
                if text is None:
                    raise ValueError("text must be a string")

            # Generate embeddings using the real model
            embeddings = self._model.encode(
                texts,
                convert_to_numpy=True,
                normalize_embeddings=False,  # We'll normalize after dimension adjustment
                show_progress_bar=False,
            )

            # Truncate or pad to requested dimensions if needed
            if embeddings.shape[1] != self._ndims:
                if embeddings.shape[1] > self._ndims:
                    # Truncate to requested dimensions
                    embeddings = embeddings[:, : self._ndims]
                else:
                    # Pad with zeros if model produces fewer dimensions
                    padding = np.zeros(
                        (embeddings.shape[0], self._ndims - embeddings.shape[1])
                    )
                    embeddings = np.concatenate([embeddings, padding], axis=1)

            # Normalize embeddings after dimension adjustment for cosine similarity
            norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
            # Avoid division by zero
            norms = np.where(norms == 0, 1, norms)
            embeddings = embeddings / norms

            return embeddings.tolist()

    def ndims(self) -> int:
        return self._ndims
