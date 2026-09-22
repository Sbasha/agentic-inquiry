"""Tests for TokenBudgetManager service."""

import pytest

pytestmark = pytest.mark.integration

from agentic_inquiry.config import Config
from agentic_inquiry.mcp.services.token_budget import (
    BudgetAllocation,
    TokenBudgetManager,
)


@pytest.fixture
def config() -> Config:
    """Create test configuration."""
    return Config.load()


@pytest.fixture
def budget_manager(config: Config) -> TokenBudgetManager:
    """Create TokenBudgetManager instance."""
    return TokenBudgetManager(config)


class TestBudgetAllocation:
    """Tests for BudgetAllocation dataclass."""
    
    def test_valid_allocation(self) -> None:
        """Test creating valid budget allocation."""
        allocation = BudgetAllocation(
            code_budget=7000,
            docs_budget=3000,
            total_budget=10000,
            focus="code"
        )
        
        assert allocation.code_budget == 7000
        assert allocation.docs_budget == 3000
        assert allocation.total_budget == 10000
        assert allocation.focus == "code"
    
    def test_invalid_allocation_exceeds_total(self) -> None:
        """Test that allocation validates sum doesn't exceed total."""
        with pytest.raises(ValueError, match="exceeds total_budget"):
            BudgetAllocation(
                code_budget=7000,
                docs_budget=4000,
                total_budget=10000,
                focus="code"
            )


class TestTokenBudgetManager:
    """Tests for TokenBudgetManager."""
    
    def test_initialization(self, budget_manager: TokenBudgetManager, config: Config) -> None:
        """Test manager initialization."""
        assert budget_manager.config == config
        assert budget_manager._encoding is not None
    
    def test_allocate_budget_with_default(self, budget_manager: TokenBudgetManager) -> None:
        """Test budget allocation using default budget."""
        allocation = budget_manager.allocate_budget()
        
        # Should use default budget from config
        assert allocation.total_budget == 50000
        assert allocation.focus == "balanced"
        # Balanced should be 50/50
        assert allocation.code_budget == 25000
        assert allocation.docs_budget == 25000
    
    def test_allocate_budget_code_focus(self, budget_manager: TokenBudgetManager) -> None:
        """Test budget allocation with code focus."""
        allocation = budget_manager.allocate_budget(total_budget=10000, focus="code")
        
        assert allocation.total_budget == 10000
        assert allocation.focus == "code"
        # Code focus should be 70/30
        assert allocation.code_budget == 7000
        assert allocation.docs_budget == 3000
    
    def test_allocate_budget_docs_focus(self, budget_manager: TokenBudgetManager) -> None:
        """Test budget allocation with docs focus."""
        allocation = budget_manager.allocate_budget(total_budget=10000, focus="docs")
        
        assert allocation.total_budget == 10000
        assert allocation.focus == "docs"
        # Docs focus should be 30/70
        assert allocation.code_budget == 3000
        assert allocation.docs_budget == 7000
    
    def test_allocate_budget_balanced_focus(self, budget_manager: TokenBudgetManager) -> None:
        """Test budget allocation with balanced focus."""
        allocation = budget_manager.allocate_budget(total_budget=10000, focus="balanced")
        
        assert allocation.total_budget == 10000
        assert allocation.focus == "balanced"
        # Balanced should be 50/50
        assert allocation.code_budget == 5000
        assert allocation.docs_budget == 5000
    
    def test_allocate_budget_below_minimum(self, budget_manager: TokenBudgetManager) -> None:
        """Test that allocation rejects budget below minimum."""
        with pytest.raises(ValueError, match="below minimum"):
            budget_manager.allocate_budget(total_budget=5000)
    
    def test_allocate_budget_above_maximum(self, budget_manager: TokenBudgetManager) -> None:
        """Test that allocation rejects budget above maximum."""
        with pytest.raises(ValueError, match="exceeds maximum"):
            budget_manager.allocate_budget(total_budget=150000)
    
    def test_allocate_budget_invalid_focus(self, budget_manager: TokenBudgetManager) -> None:
        """Test that allocation rejects invalid focus type."""
        with pytest.raises(ValueError, match="Unknown focus type"):
            budget_manager.allocate_budget(total_budget=10000, focus="invalid")  # type: ignore
    
    def test_allocate_budget_different_sizes(self, budget_manager: TokenBudgetManager) -> None:
        """Test budget allocation with different budget sizes."""
        # Small budget
        small = budget_manager.allocate_budget(total_budget=15000, focus="balanced")
        assert small.code_budget == 7500
        assert small.docs_budget == 7500
        
        # Large budget
        large = budget_manager.allocate_budget(total_budget=80000, focus="balanced")
        assert large.code_budget == 40000
        assert large.docs_budget == 40000
    
    def test_estimate_tokens_empty_string(self, budget_manager: TokenBudgetManager) -> None:
        """Test token estimation for empty string."""
        tokens = budget_manager.estimate_tokens("")
        assert tokens == 0
    
    def test_estimate_tokens_simple_text(self, budget_manager: TokenBudgetManager) -> None:
        """Test token estimation for simple text."""
        text = "Hello, world!"
        tokens = budget_manager.estimate_tokens(text)
        
        # Should return a positive number
        assert tokens > 0
        # Rough sanity check (should be a few tokens)
        assert tokens < 10
    
    def test_estimate_tokens_code(self, budget_manager: TokenBudgetManager) -> None:
        """Test token estimation for code."""
        code = """
def hello_world():
    print("Hello, world!")
    return True
"""
        tokens = budget_manager.estimate_tokens(code)
        
        # Should return a positive number
        assert tokens > 0
        # Code should be more than a few tokens
        assert tokens > 5
    
    def test_estimate_tokens_long_text(self, budget_manager: TokenBudgetManager) -> None:
        """Test token estimation for longer text."""
        # Create a longer text
        text = "This is a test sentence. " * 100
        tokens = budget_manager.estimate_tokens(text)
        
        # Should be significantly more tokens
        assert tokens > 100
    
    def test_fits_budget_within_limit(self, budget_manager: TokenBudgetManager) -> None:
        """Test that short text fits within budget."""
        text = "Hello, world!"
        fits = budget_manager.fits_budget(text, budget=1000)
        
        assert fits is True
    
    def test_fits_budget_exceeds_limit(self, budget_manager: TokenBudgetManager) -> None:
        """Test that long text exceeds small budget."""
        text = "This is a test sentence. " * 1000
        fits = budget_manager.fits_budget(text, budget=100)
        
        assert fits is False
    
    def test_fits_budget_with_buffer(self, budget_manager: TokenBudgetManager) -> None:
        """Test that buffer is applied correctly."""
        # Create text that's close to budget
        text = "word " * 50  # Roughly 50-100 tokens
        
        # With 10% buffer, effective budget is 90
        fits_with_buffer = budget_manager.fits_budget(text, budget=100, buffer_ratio=0.1)
        
        # With 50% buffer, effective budget is 50
        fits_with_large_buffer = budget_manager.fits_budget(text, budget=100, buffer_ratio=0.5)
        
        # Should be more restrictive with larger buffer
        if not fits_with_buffer:
            assert not fits_with_large_buffer
    
    def test_fits_budget_zero_budget(self, budget_manager: TokenBudgetManager) -> None:
        """Test that zero budget always returns False."""
        text = "Hello"
        fits = budget_manager.fits_budget(text, budget=0)
        
        assert fits is False
    
    def test_fits_budget_negative_budget(self, budget_manager: TokenBudgetManager) -> None:
        """Test that negative budget always returns False."""
        text = "Hello"
        fits = budget_manager.fits_budget(text, budget=-100)
        
        assert fits is False
    
    def test_estimate_batch_tokens_empty_list(self, budget_manager: TokenBudgetManager) -> None:
        """Test batch estimation with empty list."""
        result = budget_manager.estimate_batch_tokens([])
        
        assert result["total"] == 0
        assert result["average"] == 0
        assert result["min"] == 0
        assert result["max"] == 0
    
    def test_estimate_batch_tokens_single_text(self, budget_manager: TokenBudgetManager) -> None:
        """Test batch estimation with single text."""
        texts = ["Hello, world!"]
        result = budget_manager.estimate_batch_tokens(texts)
        
        assert result["total"] > 0
        assert result["average"] == result["total"]
        assert result["min"] == result["total"]
        assert result["max"] == result["total"]
    
    def test_estimate_batch_tokens_multiple_texts(self, budget_manager: TokenBudgetManager) -> None:
        """Test batch estimation with multiple texts."""
        texts = [
            "Short",
            "This is a medium length sentence.",
            "This is a much longer sentence with many more words to increase the token count significantly."
        ]
        result = budget_manager.estimate_batch_tokens(texts)
        
        assert result["total"] > 0
        assert result["average"] > 0
        assert result["min"] > 0
        assert result["max"] > 0
        # Max should be greater than min
        assert result["max"] >= result["min"]
        # Total should equal sum of individual estimates
        individual_total = sum(budget_manager.estimate_tokens(t) for t in texts)
        assert result["total"] == individual_total
    
    def test_estimate_batch_tokens_statistics(self, budget_manager: TokenBudgetManager) -> None:
        """Test that batch statistics are calculated correctly."""
        texts = ["a", "bb", "ccc", "dddd"]
        result = budget_manager.estimate_batch_tokens(texts)
        
        # Verify average is reasonable
        assert result["average"] <= result["max"]
        assert result["average"] >= result["min"]
        
        # Verify total is sum
        individual_counts = [budget_manager.estimate_tokens(t) for t in texts]
        assert result["total"] == sum(individual_counts)
        assert result["min"] == min(individual_counts)
        assert result["max"] == max(individual_counts)


class TestTokenBudgetIntegration:
    """Integration tests for TokenBudgetManager."""
    
    def test_realistic_workflow(self, budget_manager: TokenBudgetManager) -> None:
        """Test realistic workflow of allocating and checking budgets."""
        # Allocate budget with code focus
        allocation = budget_manager.allocate_budget(total_budget=20000, focus="code")
        
        # Simulate code content
        code_content = """
def process_data(data: list) -> dict:
    result = {}
    for item in data:
        result[item['id']] = item['value']
    return result
""" * 50  # Repeat to make it substantial
        
        # Simulate docs content
        docs_content = "This is documentation. " * 100
        
        # Check if content fits
        code_fits = budget_manager.fits_budget(code_content, allocation.code_budget)
        docs_fits = budget_manager.fits_budget(docs_content, allocation.docs_budget)
        
        # At least one should fit (or we need to adjust test data)
        assert code_fits or docs_fits
        
        # Estimate actual usage
        code_tokens = budget_manager.estimate_tokens(code_content)
        docs_tokens = budget_manager.estimate_tokens(docs_content)
        total_tokens = code_tokens + docs_tokens
        
        # Should be within total budget (with some margin)
        assert total_tokens <= allocation.total_budget * 1.5  # Allow 50% overflow for test
    
    def test_overflow_handling(self, budget_manager: TokenBudgetManager) -> None:
        """Test handling when content exceeds budget."""
        # Small budget
        allocation = budget_manager.allocate_budget(total_budget=10000, focus="balanced")
        
        # Large content
        large_content = "This is a test sentence. " * 1000
        
        # Should not fit
        fits = budget_manager.fits_budget(large_content, allocation.code_budget)
        assert fits is False
        
        # Estimate shows it's too large
        tokens = budget_manager.estimate_tokens(large_content)
        assert tokens > allocation.code_budget
