"""Token budget management and optimization for MCP context building.

This module provides utilities for managing token budgets when assembling
context from multiple sources. It uses tiktoken for accurate token counting
with fallback to character-based estimation.
"""

from dataclasses import dataclass
from typing import Any, Optional
import logging

logger = logging.getLogger(__name__)

# Try to import tiktoken for accurate token counting
try:
    import tiktoken
    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False
    logger.warning(
        "tiktoken not available, falling back to character-based estimation. "
        "Install tiktoken for accurate token counting: pip install tiktoken"
    )


@dataclass
class TokenBudget:
    """Manages token budget for context assembly.
    
    Tracks token usage and provides methods to check if content can be added
    within the budget. Uses tiktoken for accurate counting when available,
    otherwise falls back to character-based estimation (1 token ≈ 4 characters).
    
    Attributes:
        max_tokens: Maximum number of tokens allowed
        used_tokens: Number of tokens currently used
        encoding_name: Name of tiktoken encoding to use (default: cl100k_base for GPT-4)
    """
    
    max_tokens: int
    used_tokens: int = 0
    encoding_name: str = "cl100k_base"
    _encoder: Optional[Any] = None
    
    def __post_init__(self):
        """Initialize tiktoken encoder if available."""
        if TIKTOKEN_AVAILABLE and self._encoder is None:
            try:
                self._encoder = tiktoken.get_encoding(self.encoding_name)
            except Exception as e:
                logger.warning("Failed to load tiktoken encoding: %s", e)
                self._encoder = None
    
    def estimate_tokens(self, text: str) -> int:
        """Estimate token count for text.
        
        Uses tiktoken for accurate counting if available, otherwise uses
        character-based estimation (1 token ≈ 4 characters).
        
        Args:
            text: Text to estimate tokens for
            
        Returns:
            Estimated number of tokens
        """
        if not text:
            return 0
        
        if self._encoder is not None:
            try:
                return len(self._encoder.encode(text))
            except Exception as e:
                logger.warning("tiktoken encoding failed: %s, falling back to estimation", e)
        
        # Fallback: rough estimation (1 token ≈ 4 characters)
        return len(text) // 4
    
    def can_add(self, text: str) -> bool:
        """Check if text can be added within budget.
        
        Args:
            text: Text to check
            
        Returns:
            True if text fits within remaining budget
        """
        estimated = self.estimate_tokens(text)
        return self.used_tokens + estimated <= self.max_tokens
    
    def add(self, text: str) -> bool:
        """Add text to budget if it fits.
        
        Args:
            text: Text to add
            
        Returns:
            True if text was added, False if it exceeded budget
        """
        estimated = self.estimate_tokens(text)
        if self.used_tokens + estimated <= self.max_tokens:
            self.used_tokens += estimated
            return True
        return False
    
    def remaining(self) -> int:
        """Get remaining token budget.
        
        Returns:
            Number of tokens remaining in budget
        """
        return max(0, self.max_tokens - self.used_tokens)
    
    def usage_percentage(self) -> float:
        """Get budget usage as percentage.
        
        Returns:
            Percentage of budget used (0.0 to 100.0)
        """
        if self.max_tokens == 0:
            return 0.0
        return (self.used_tokens / self.max_tokens) * 100.0
    
    def reset(self):
        """Reset used tokens to zero."""
        self.used_tokens = 0
    
    def __repr__(self) -> str:
        """String representation of budget."""
        return (
            f"TokenBudget(used={self.used_tokens}/{self.max_tokens}, "
            f"remaining={self.remaining()}, "
            f"usage={self.usage_percentage():.1f}%)"
        )


class TokenOptimizer:
    """Optimizes content for token efficiency.
    
    Provides utilities for truncating, summarizing, and prioritizing content
    to fit within token budgets.
    """
    
    def __init__(self, encoding_name: str = "cl100k_base"):
        """Initialize token optimizer.
        
        Args:
            encoding_name: Name of tiktoken encoding to use
        """
        self.encoding_name = encoding_name
        self._encoder = None
        
        if TIKTOKEN_AVAILABLE:
            try:
                self._encoder = tiktoken.get_encoding(encoding_name)
            except Exception as e:
                logger.warning("Failed to load tiktoken encoding: %s", e)
    
    def truncate_to_tokens(self, text: str, max_tokens: int) -> str:
        """Truncate text to fit within token limit.
        
        Args:
            text: Text to truncate
            max_tokens: Maximum number of tokens
            
        Returns:
            Truncated text
        """
        if not text:
            return text
        
        if self._encoder is not None:
            try:
                tokens = self._encoder.encode(text)
                if len(tokens) <= max_tokens:
                    return text
                truncated_tokens = tokens[:max_tokens]
                return self._encoder.decode(truncated_tokens)
            except Exception as e:
                logger.warning("tiktoken truncation failed: %s, using character-based", e)
        
        # Fallback: character-based truncation
        estimated_chars = max_tokens * 4
        if len(text) <= estimated_chars:
            return text
        return text[:estimated_chars] + "..."
    
    def create_snippet(self, text: str, max_tokens: int = 125) -> str:
        """Create a snippet from text.
        
        Truncates text to max_tokens and adds ellipsis if truncated.
        Default 125 tokens ≈ 500 characters (as per design spec).
        
        Args:
            text: Text to create snippet from
            max_tokens: Maximum tokens for snippet (default: 125)
            
        Returns:
            Snippet text
        """
        if not text:
            return ""
        
        truncated = self.truncate_to_tokens(text, max_tokens)
        
        # Add ellipsis if truncated
        if len(truncated) < len(text):
            # Remove any partial word at the end
            if truncated and not truncated[-1].isspace():
                last_space = truncated.rfind(' ')
                if last_space > 0:
                    truncated = truncated[:last_space]
            truncated = truncated.rstrip() + "..."
        
        return truncated
    
    def estimate_tokens(self, text: str) -> int:
        """Estimate token count for text.
        
        Args:
            text: Text to estimate
            
        Returns:
            Estimated token count
        """
        budget = TokenBudget(max_tokens=0, encoding_name=self.encoding_name)
        budget._encoder = self._encoder
        return budget.estimate_tokens(text)
