"""Token budget management for context building.

This module provides token budget allocation and estimation for building
context from search results, ensuring efficient use of available token budgets.
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Literal

import tiktoken

from agentic_inquiry.config import Config


logger = logging.getLogger(__name__)


FocusType = Literal["code", "docs", "balanced"]


@dataclass
class BudgetAllocation:
    """Budget allocation for different content types."""

    code_budget: int
    docs_budget: int
    total_budget: int
    focus: FocusType

    def __post_init__(self) -> None:
        """Validate budget allocation."""
        if self.code_budget + self.docs_budget > self.total_budget:
            raise ValueError(
                f"Sum of code_budget ({self.code_budget}) and docs_budget ({self.docs_budget}) "
                f"exceeds total_budget ({self.total_budget})"
            )


class TokenBudgetManager:
    """Manages token budgets for context building.

    Provides methods to allocate budgets based on focus type, estimate token
    counts, and check if content fits within budget constraints.
    """

    def __init__(self, config: Config):
        """Initialize token budget manager.

        Args:
            config: Configuration instance with token budget settings
        """
        self.config = config
        self._encoding = tiktoken.get_encoding(config.mcp.tokens.estimation_model)
        logger.debug(
            "Initialized TokenBudgetManager with model %s",
            config.mcp.tokens.estimation_model,
        )

    def allocate_budget(
        self, total_budget: int | None = None, focus: FocusType = "balanced"
    ) -> BudgetAllocation:
        """Allocate budget between code and documentation.

        Args:
            total_budget: Total token budget available. If None, uses default from config.
            focus: Focus type for allocation strategy

        Returns:
            BudgetAllocation with code and docs budgets

        Raises:
            ValueError: If total_budget is outside configured min/max range
        """
        # Use default budget if not provided
        if total_budget is None:
            total_budget = self.config.context.token_budget.default_budget
            logger.debug("Using default budget: %d", total_budget)

        # Validate budget range
        min_budget = self.config.context.token_budget.min_budget
        max_budget = self.config.context.token_budget.max_budget

        if total_budget < min_budget:
            raise ValueError(
                f"total_budget ({total_budget}) is below minimum ({min_budget})"
            )
        if total_budget > max_budget:
            raise ValueError(
                f"total_budget ({total_budget}) exceeds maximum ({max_budget})"
            )

        # Get focus allocation weights
        allocations = self.config.context.token_budget.focus_allocations
        if focus not in allocations:
            raise ValueError(
                f"Unknown focus type: {focus}. "
                f"Valid options: {list(allocations.keys())}"
            )

        weights = allocations[focus]
        code_weight = weights["code_weight"]
        docs_weight = weights["docs_weight"]

        # Calculate budgets
        code_budget = int(total_budget * code_weight)
        docs_budget = int(total_budget * docs_weight)

        logger.debug(
            "Allocated budget: total=%d, code=%d, docs=%d, focus=%s",
            total_budget,
            code_budget,
            docs_budget,
            focus,
        )

        return BudgetAllocation(
            code_budget=code_budget,
            docs_budget=docs_budget,
            total_budget=total_budget,
            focus=focus,
        )

    def estimate_tokens(self, text: str) -> int:
        """Estimate token count for text.

        Args:
            text: Text to estimate tokens for

        Returns:
            Estimated token count
        """
        if not text:
            return 0

        try:
            tokens = len(self._encoding.encode(text))
            return tokens
        except Exception as e:
            # Fallback to rough estimation if encoding fails
            logger.warning("Token encoding failed, using fallback: %s", e)
            # Rough estimate: ~4 characters per token
            return len(text) // 4

    def fits_budget(self, text: str, budget: int, buffer_ratio: float = 0.1) -> bool:
        """Check if text fits within budget.

        Args:
            text: Text to check
            budget: Token budget limit
            buffer_ratio: Safety buffer as ratio of budget (default: 0.1 = 10%)

        Returns:
            True if text fits within budget (including buffer), False otherwise
        """
        if budget <= 0:
            return False

        estimated = self.estimate_tokens(text)
        effective_budget = int(budget * (1 - buffer_ratio))

        fits = estimated <= effective_budget

        if not fits:
            logger.debug(
                "Content exceeds budget: estimated=%d, effective_budget=%d (buffer=%.1f%%)",
                estimated,
                effective_budget,
                buffer_ratio * 100,
            )

        return fits

    def estimate_batch_tokens(self, texts: List[str]) -> Dict[str, int]:
        """Estimate tokens for multiple texts.

        Args:
            texts: List of texts to estimate

        Returns:
            Dictionary with 'total', 'average', 'min', 'max' token counts
        """
        if not texts:
            return {"total": 0, "average": 0, "min": 0, "max": 0}

        counts = [self.estimate_tokens(text) for text in texts]

        return {
            "total": sum(counts),
            "average": sum(counts) // len(counts),
            "min": min(counts),
            "max": max(counts),
        }
