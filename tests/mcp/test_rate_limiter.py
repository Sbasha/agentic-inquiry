"""Tests for the rate limiter implementation.

Feature: SEC-004 - Implement Rate Limiting
Tests session-level and tool-level rate limiting with configurable limits.
"""

import pytest

pytestmark = pytest.mark.unit

from agent_vault.mcp.utils.rate_limiter import (
    RateLimiter,
    RateLimitConfig,
    RateLimitResult,
    CallTracker,
    TOOL_CATEGORY_SEARCH,
    TOOL_CATEGORY_ANALYSIS,
    TOOL_CATEGORIES,
    reset_rate_limiter,
    get_rate_limiter,
)


@pytest.fixture(autouse=True)
def reset_limiter():
    """Reset global rate limiter before each test."""
    reset_rate_limiter()
    yield
    reset_rate_limiter()


class TestRateLimitConfig:
    """Tests for RateLimitConfig."""

    def test_default_config_values(self):
        """Default config should have reasonable values."""
        config = RateLimitConfig()

        assert config.enabled is True
        assert config.session_calls_per_hour == 1000
        assert config.search_calls_per_minute == 50
        assert config.analysis_calls_per_hour == 20
        assert config.default_calls_per_minute == 60

    def test_get_tool_config_search(self):
        """Search tools should get search-specific limits."""
        config = RateLimitConfig()
        tool_config = config.get_tool_config("search_knowledge")

        assert tool_config.calls_per_minute == 50
        assert tool_config.window_seconds == 60
        assert tool_config.calls_per_hour is None

    def test_get_tool_config_analysis(self):
        """Analysis tools should get analysis-specific limits with hourly cap."""
        config = RateLimitConfig()
        tool_config = config.get_tool_config("analyze_impact")

        assert tool_config.calls_per_minute == 5
        assert tool_config.calls_per_hour == 20

    def test_get_tool_config_unknown_tool(self):
        """Unknown tools should get default limits."""
        config = RateLimitConfig()
        tool_config = config.get_tool_config("unknown_tool_xyz")

        assert tool_config.calls_per_minute == 60


class TestCallTracker:
    """Tests for CallTracker."""

    def test_record_and_count_calls(self):
        """Should correctly count recorded calls."""
        tracker = CallTracker()

        tracker.record_call()
        tracker.record_call()
        tracker.record_call()

        assert tracker.count_calls_in_window(60) == 3

    def test_cleanup_old_timestamps(self):
        """Should remove timestamps outside the window."""
        tracker = CallTracker()

        # Manually add old timestamps (simulating time passage)
        import time
        old_time = time.monotonic() - 120  # 2 minutes ago
        tracker.timestamps = [old_time, old_time + 1]
        tracker.record_call()  # Current time

        # Only the current call should remain in 60s window
        assert tracker.count_calls_in_window(60) == 1

    def test_get_retry_after_seconds(self):
        """Should calculate retry-after correctly."""
        tracker = CallTracker()
        tracker.record_call()

        retry_after = tracker.get_retry_after_seconds(60)

        # Should be close to 60 seconds (the full window)
        assert 59 <= retry_after <= 60


class TestRateLimitResult:
    """Tests for RateLimitResult."""

    def test_allowed_result(self):
        """Allowed result should have no error."""
        result = RateLimitResult(allowed=True)

        assert result.allowed is True
        assert result.error_message is None

    def test_denied_result(self):
        """Denied result should have error message and retry-after."""
        result = RateLimitResult(
            allowed=False,
            error_message="Rate limit exceeded",
            retry_after_seconds=30.0,
            limit_type="session"
        )

        assert result.allowed is False
        assert result.error_message == "Rate limit exceeded"
        assert result.retry_after_seconds == 30.0

    def test_to_error_response(self):
        """Error response should have correct structure."""
        result = RateLimitResult(
            allowed=False,
            error_message="Rate limit exceeded",
            retry_after_seconds=30.5,
            limit_type="tool"
        )

        response = result.to_error_response()

        assert response["code"] == "RATE_LIMITED"
        assert response["error"] == "Rate limit exceeded"
        assert response["retry_after_seconds"] == 30.5
        assert response["limit_type"] == "tool"
        assert "suggestion" in response


class TestRateLimiter:
    """Tests for the RateLimiter class."""

    @pytest.mark.asyncio
    async def test_allows_calls_under_limit(self):
        """Should allow calls when under the limit."""
        config = RateLimitConfig(default_calls_per_minute=10)
        limiter = RateLimiter(config)

        for i in range(5):
            result = await limiter.check_rate_limit("session1")
            assert result.allowed is True

    @pytest.mark.asyncio
    async def test_blocks_calls_over_limit(self):
        """Should block calls when over the limit."""
        config = RateLimitConfig(default_calls_per_minute=3)
        limiter = RateLimiter(config)

        # Make 3 calls (should all succeed)
        for _ in range(3):
            result = await limiter.check_rate_limit("session1")
            assert result.allowed is True

        # 4th call should be blocked
        result = await limiter.check_rate_limit("session1")
        assert result.allowed is False
        assert result.limit_type == "session"

    @pytest.mark.asyncio
    async def test_separate_sessions(self):
        """Different sessions should have separate limits."""
        config = RateLimitConfig(default_calls_per_minute=2)
        limiter = RateLimiter(config)

        # Use up session1's limit
        await limiter.check_rate_limit("session1")
        await limiter.check_rate_limit("session1")

        # Session2 should still be allowed
        result = await limiter.check_rate_limit("session2")
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_tool_specific_limits(self):
        """Tool-specific limits should be enforced."""
        config = RateLimitConfig(search_calls_per_minute=2)
        limiter = RateLimiter(config)

        # Make 2 search calls
        for _ in range(2):
            result = await limiter.check_rate_limit("session1", "search_knowledge")
            assert result.allowed is True

        # 3rd search call should be blocked
        result = await limiter.check_rate_limit("session1", "search_knowledge")
        assert result.allowed is False
        assert result.limit_type == "tool"
        assert "search_knowledge" in result.error_message

    @pytest.mark.asyncio
    async def test_analysis_hourly_limit(self):
        """Analysis tools should have hourly limit."""
        config = RateLimitConfig(analysis_calls_per_hour=2)
        limiter = RateLimiter(config)

        # Make 2 analysis calls
        for _ in range(2):
            result = await limiter.check_rate_limit("session1", "analyze_impact")
            assert result.allowed is True

        # 3rd should be blocked by hourly limit
        result = await limiter.check_rate_limit("session1", "analyze_impact")
        assert result.allowed is False
        assert "hourly" in result.limit_type

    @pytest.mark.asyncio
    async def test_disabled_rate_limiting(self):
        """Should allow all calls when disabled."""
        config = RateLimitConfig(enabled=False, default_calls_per_minute=1)
        limiter = RateLimiter(config)

        # Should allow more than the limit when disabled
        for _ in range(10):
            result = await limiter.check_rate_limit("session1")
            assert result.allowed is True

    @pytest.mark.asyncio
    async def test_retry_after_in_response(self):
        """Blocked calls should include retry-after seconds."""
        config = RateLimitConfig(default_calls_per_minute=1)
        limiter = RateLimiter(config)

        await limiter.check_rate_limit("session1")
        result = await limiter.check_rate_limit("session1")

        assert result.allowed is False
        assert result.retry_after_seconds is not None
        assert result.retry_after_seconds > 0

    @pytest.mark.asyncio
    async def test_session_stats(self):
        """Should return correct session stats."""
        config = RateLimitConfig(default_calls_per_minute=10)
        limiter = RateLimiter(config)

        await limiter.check_rate_limit("session1", "search_knowledge")
        await limiter.check_rate_limit("session1", "search_knowledge")
        await limiter.check_rate_limit("session1", "analyze_impact")

        stats = limiter.get_session_stats("session1")

        assert stats["session"]["calls_in_minute"] == 3
        assert stats["tools"]["search_knowledge"]["calls_in_minute"] == 2
        assert stats["tools"]["analyze_impact"]["calls_in_minute"] == 1

    @pytest.mark.asyncio
    async def test_cleanup_session(self):
        """Should clean up session data."""
        config = RateLimitConfig(default_calls_per_minute=10)
        limiter = RateLimiter(config)

        await limiter.check_rate_limit("session1")
        await limiter.cleanup_session("session1")

        stats = limiter.get_session_stats("session1")
        assert stats["session"]["calls_in_minute"] == 0


class TestGlobalRateLimiter:
    """Tests for global rate limiter functions."""

    def test_get_rate_limiter_singleton(self):
        """get_rate_limiter should return same instance."""
        limiter1 = get_rate_limiter()
        limiter2 = get_rate_limiter()

        assert limiter1 is limiter2

    def test_reset_rate_limiter(self):
        """reset_rate_limiter should clear the singleton."""
        limiter1 = get_rate_limiter()
        reset_rate_limiter()
        limiter2 = get_rate_limiter()

        assert limiter1 is not limiter2


class TestToolCategories:
    """Tests for tool category mappings."""

    def test_search_tools_mapped(self):
        """Search tools should be in search category."""
        assert TOOL_CATEGORIES.get("search_knowledge") == TOOL_CATEGORY_SEARCH
        assert TOOL_CATEGORIES.get("find_similar") == TOOL_CATEGORY_SEARCH

    def test_analysis_tools_mapped(self):
        """Analysis tools should be in analysis category."""
        assert TOOL_CATEGORIES.get("analyze_impact") == TOOL_CATEGORY_ANALYSIS
        assert TOOL_CATEGORIES.get("build_context") == TOOL_CATEGORY_ANALYSIS
