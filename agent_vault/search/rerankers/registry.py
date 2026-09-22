"""Reranker registry for factory-based instantiation.

Provides a central registry for reranker types and factory methods
to create reranker instances from configuration.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional, Type

from agent_vault.search.rerankers.protocol import RerankerProtocol

logger = logging.getLogger(__name__)

# Type alias for reranker factory functions
RerankerFactory = Callable[..., RerankerProtocol]

# Global registry mapping reranker type names to factory functions
_RERANKER_REGISTRY: Dict[str, RerankerFactory] = {}


def register_reranker(name: str) -> Callable[[Type[RerankerProtocol]], Type[RerankerProtocol]]:
    """Decorator to register a reranker class.

    Args:
        name: The configuration key for this reranker type

    Returns:
        Decorator function that registers the class

    Example:
        @register_reranker("rrf")
        class RRFReranker(RerankerProtocol):
            ...
    """

    def decorator(cls: Type[RerankerProtocol]) -> Type[RerankerProtocol]:
        _RERANKER_REGISTRY[name] = cls
        logger.debug("Registered reranker: %s -> %s", name, cls.__name__)
        return cls

    return decorator


def get_reranker(
    reranker_type: str,
    config: Optional[Dict[str, Any]] = None,
) -> Optional[RerankerProtocol]:
    """Get a reranker instance by type name.

    Note: This creates a NEW instance each time. For lightweight rerankers
    (RRF, LinearCombination) this is fine. For ML-based rerankers (CrossEncoder,
    ColBERT, Cohere), callers should cache the instance to avoid repeated
    model loading which is expensive (seconds + GBs of RAM).

    Args:
        reranker_type: The reranker type key (e.g., "rrf", "linear_combination")
        config: Optional configuration dict passed to reranker constructor

    Returns:
        Reranker instance or None if type not found or initialization fails

    Example:
        reranker = get_reranker("rrf", {"k": 60})
        reranker = get_reranker("linear_combination", {"vector_weight": 0.8})
    """
    config = config or {}

    factory = _RERANKER_REGISTRY.get(reranker_type)
    if factory is None:
        logger.warning("Unknown reranker type: %s", reranker_type)
        return None

    try:
        return factory(**config)
    except Exception as e:
        logger.error("Failed to create reranker %s: %s", reranker_type, e)
        return None


def list_rerankers() -> list[str]:
    """List all registered reranker type names.

    Returns:
        List of available reranker type keys
    """
    return list(_RERANKER_REGISTRY.keys())
