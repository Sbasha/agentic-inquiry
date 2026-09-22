"""Search strategy selection based on index progress.

This module provides functionality to determine the optimal search strategy
based on the current state of the index. As indexing progresses, the system
can transition from fallback search methods to semantic search.
"""

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_vault.config import Config


class SearchStrategy(str, Enum):
    """Search strategy based on index state.

    The strategy determines how searches are executed based on index completeness:
    - FALLBACK_ONLY: Index too sparse, use static/fallback search exclusively
    - HYBRID_FALLBACK_PRIMARY: Mix of fallback and semantic, fallback prioritized
    - SEMANTIC_PRIMARY: Mix of semantic and fallback, semantic prioritized
    - SEMANTIC_ONLY: Index complete enough for pure semantic search
    """

    FALLBACK_ONLY = "fallback_only"
    HYBRID_FALLBACK_PRIMARY = "hybrid_fallback"
    SEMANTIC_PRIMARY = "semantic_primary"
    SEMANTIC_ONLY = "semantic_only"


@dataclass
class StrategyThresholds:
    """Configurable thresholds for strategy selection.

    These thresholds define the index progress percentages at which
    the search strategy transitions to the next level.

    Attributes:
        fallback_only_max: Max progress for FALLBACK_ONLY (0 to this value)
        hybrid_fallback_max: Max progress for HYBRID_FALLBACK_PRIMARY
        semantic_primary_max: Max progress for SEMANTIC_PRIMARY
    """

    fallback_only_max: float = 10.0
    hybrid_fallback_max: float = 50.0
    semantic_primary_max: float = 80.0

    @classmethod
    def from_config(cls, config: "Config") -> "StrategyThresholds":
        """Load thresholds from config.

        Args:
            config: Application configuration

        Returns:
            StrategyThresholds with values from config or defaults
        """
        # Future: Read from config.search.strategy_thresholds when added
        # For now, return defaults
        return cls()

    def validate(self) -> None:
        """Validate threshold values are in correct order.

        Raises:
            ValueError: If thresholds are not in ascending order or out of range
        """
        if not (0 <= self.fallback_only_max <= 100):
            raise ValueError(
                "fallback_only_max must be between 0 and 100, "
                "got %s" % self.fallback_only_max
            )
        if not (0 <= self.hybrid_fallback_max <= 100):
            raise ValueError(
                "hybrid_fallback_max must be between 0 and 100, "
                "got %s" % self.hybrid_fallback_max
            )
        if not (0 <= self.semantic_primary_max <= 100):
            raise ValueError(
                "semantic_primary_max must be between 0 and 100, "
                "got %s" % self.semantic_primary_max
            )
        if not (
            self.fallback_only_max
            <= self.hybrid_fallback_max
            <= self.semantic_primary_max
        ):
            raise ValueError(
                "Thresholds must be in ascending order: "
                "fallback_only_max <= hybrid_fallback_max <= semantic_primary_max"
            )


def determine_search_strategy(
    progress_percent: float,
    index_status: str,
    thresholds: StrategyThresholds | None = None,
) -> SearchStrategy:
    """Determine optimal search strategy based on index progress.

    The strategy selection follows these thresholds (configurable):
    - 0-10%: FALLBACK_ONLY (index too sparse for semantic search)
    - 10-50%: HYBRID_FALLBACK_PRIMARY (mix, prefer fallback)
    - 50-80%: SEMANTIC_PRIMARY (mix, prefer semantic)
    - 80%+: SEMANTIC_ONLY (index complete enough)

    Args:
        progress_percent: Index completion percentage (0-100)
        index_status: Current index status string (e.g., "indexing", "ready", "idle")
        thresholds: Optional custom thresholds. Uses defaults if None.

    Returns:
        SearchStrategy enum value indicating the recommended strategy
    """
    if thresholds is None:
        thresholds = StrategyThresholds()

    # Clamp progress to valid range
    progress = max(0.0, min(100.0, progress_percent))

    # If actively indexing with low progress, be conservative
    if index_status == "indexing" and progress < thresholds.fallback_only_max:
        return SearchStrategy.FALLBACK_ONLY

    # Determine strategy based on progress thresholds
    if progress < thresholds.fallback_only_max:
        return SearchStrategy.FALLBACK_ONLY
    elif progress < thresholds.hybrid_fallback_max:
        return SearchStrategy.HYBRID_FALLBACK_PRIMARY
    elif progress < thresholds.semantic_primary_max:
        return SearchStrategy.SEMANTIC_PRIMARY
    else:
        return SearchStrategy.SEMANTIC_ONLY


def get_strategy_description(strategy: SearchStrategy) -> str:
    """Get human-readable description of search strategy.

    Args:
        strategy: The search strategy to describe

    Returns:
        Human-readable description of the strategy
    """
    descriptions = {
        SearchStrategy.FALLBACK_ONLY: "Using static search only (index building)",
        SearchStrategy.HYBRID_FALLBACK_PRIMARY: (
            "Using hybrid search (static + semantic, static prioritized)"
        ),
        SearchStrategy.SEMANTIC_PRIMARY: (
            "Using hybrid search (semantic + static, semantic prioritized)"
        ),
        SearchStrategy.SEMANTIC_ONLY: "Using semantic search (index ready)",
    }
    return descriptions.get(strategy, "Unknown strategy")


def get_strategy_weights(strategy: SearchStrategy) -> tuple[float, float]:
    """Get vector and FTS weights for a given strategy.

    Returns weights that can be used to configure hybrid search behavior.
    The tuple contains (vector_weight, fts_weight) which should sum to 1.0.

    Args:
        strategy: The search strategy

    Returns:
        Tuple of (vector_weight, fts_weight)
    """
    weights = {
        SearchStrategy.FALLBACK_ONLY: (0.0, 1.0),
        SearchStrategy.HYBRID_FALLBACK_PRIMARY: (0.3, 0.7),
        SearchStrategy.SEMANTIC_PRIMARY: (0.7, 0.3),
        SearchStrategy.SEMANTIC_ONLY: (1.0, 0.0),
    }
    return weights.get(strategy, (0.5, 0.5))


__all__ = [
    "SearchStrategy",
    "StrategyThresholds",
    "determine_search_strategy",
    "get_strategy_description",
    "get_strategy_weights",
]
