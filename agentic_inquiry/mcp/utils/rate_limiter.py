"""Rate limiting for MCP tool calls.

Provides sliding window rate limiting per session and per tool to prevent
runaway loops and excessive resource usage. Designed for local MCP servers.

SEC-004: Implements session-level and tool-level rate limiting with
configurable limits and Retry-After support.
"""

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


# Tool categories for rate limiting
TOOL_CATEGORY_SEARCH = "search"
TOOL_CATEGORY_ANALYSIS = "analysis"
TOOL_CATEGORY_INFO = "info"
TOOL_CATEGORY_DEFAULT = "default"

# Tool name to category mapping
TOOL_CATEGORIES: Dict[str, str] = {
    # Search tools - higher limits
    "search_knowledge": TOOL_CATEGORY_SEARCH,
    "find_similar": TOOL_CATEGORY_SEARCH,
    "search_by_symbol": TOOL_CATEGORY_SEARCH,
    # Analysis tools - lower limits (expensive operations)
    "analyze_impact": TOOL_CATEGORY_ANALYSIS,
    "build_context": TOOL_CATEGORY_ANALYSIS,
    "get_usage_examples": TOOL_CATEGORY_ANALYSIS,
    "find_related_concepts": TOOL_CATEGORY_ANALYSIS,
    # Info tools - moderate limits
    "get_project_info": TOOL_CATEGORY_INFO,
    "get_session_status": TOOL_CATEGORY_INFO,
    "get_events": TOOL_CATEGORY_INFO,
    "list_entities": TOOL_CATEGORY_INFO,
}


@dataclass
class ToolRateLimitConfig:
    """Rate limit configuration for a specific tool category."""

    calls_per_minute: int
    window_seconds: int = 60
    calls_per_hour: Optional[int] = None  # Additional hourly limit


@dataclass
class RateLimitConfig:
    """Rate limiting configuration with per-tool limits."""

    enabled: bool = True

    # Session-level limits (applies to all tools combined)
    session_calls_per_hour: int = 1000  # 100 queries/hour per requirements

    # Per-category limits
    search_calls_per_minute: int = 50  # search: 50/min per requirements
    analysis_calls_per_hour: int = 20  # analysis: 20/hour per requirements
    info_calls_per_minute: int = 30  # info endpoints
    default_calls_per_minute: int = 60  # fallback for unclassified tools

    # Burst settings
    burst_limit: int = 10  # Allow burst of 10 calls in quick succession

    def get_tool_config(self, tool_name: str) -> ToolRateLimitConfig:
        """Get rate limit config for a specific tool."""
        category = TOOL_CATEGORIES.get(tool_name, TOOL_CATEGORY_DEFAULT)

        if category == TOOL_CATEGORY_SEARCH:
            return ToolRateLimitConfig(
                calls_per_minute=self.search_calls_per_minute,
                window_seconds=60
            )
        elif category == TOOL_CATEGORY_ANALYSIS:
            return ToolRateLimitConfig(
                calls_per_minute=5,  # ~5/min to not exceed 20/hour
                window_seconds=60,
                calls_per_hour=self.analysis_calls_per_hour
            )
        elif category == TOOL_CATEGORY_INFO:
            return ToolRateLimitConfig(
                calls_per_minute=self.info_calls_per_minute,
                window_seconds=60
            )
        else:
            return ToolRateLimitConfig(
                calls_per_minute=self.default_calls_per_minute,
                window_seconds=60
            )


@dataclass
class CallTracker:
    """Tracks call timestamps for rate limiting."""

    timestamps: list = field(default_factory=list)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def cleanup_old_timestamps(self, window_seconds: int) -> None:
        """Remove timestamps older than the window."""
        cutoff = time.monotonic() - window_seconds
        self.timestamps = [t for t in self.timestamps if t > cutoff]

    def count_calls_in_window(self, window_seconds: int) -> int:
        """Count calls within the sliding window."""
        self.cleanup_old_timestamps(window_seconds)
        return len(self.timestamps)

    def record_call(self) -> None:
        """Record a new call timestamp."""
        self.timestamps.append(time.monotonic())

    def get_retry_after_seconds(self, window_seconds: int) -> float:
        """Calculate seconds until oldest call expires from window."""
        if not self.timestamps:
            return 0.0
        self.cleanup_old_timestamps(window_seconds)
        if not self.timestamps:
            return 0.0
        oldest = self.timestamps[0]
        return max(0.0, window_seconds - (time.monotonic() - oldest))


@dataclass
class RateLimitResult:
    """Result of a rate limit check."""

    allowed: bool
    error_message: Optional[str] = None
    retry_after_seconds: Optional[float] = None
    limit_type: Optional[str] = None  # "session", "tool", "hourly"

    def to_error_response(self) -> Dict[str, Any]:
        """Convert to error response dict for MCP tools."""
        response: Dict[str, Any] = {
            "error": self.error_message,
            "code": "RATE_LIMITED",
            "suggestion": "Reduce call frequency or wait before retrying",
        }
        if self.retry_after_seconds is not None:
            response["retry_after_seconds"] = round(self.retry_after_seconds, 1)
        if self.limit_type:
            response["limit_type"] = self.limit_type
        return response


class RateLimiter:
    """Session and tool-aware rate limiter using sliding window algorithm.

    Supports:
    - Session-level rate limiting (all tools combined)
    - Tool-level rate limiting (per-tool category limits)
    - Hourly limits for expensive operations
    - Retry-After calculation for HTTP 429 responses
    """

    def __init__(self, config: Optional[RateLimitConfig] = None):
        """Initialize rate limiter.

        Args:
            config: Rate limiting configuration. Uses defaults if None.
        """
        self.config = config or RateLimitConfig()
        # Session-level tracking
        self._sessions: Dict[str, CallTracker] = defaultdict(CallTracker)
        # Per-session per-tool tracking: {session_id: {tool_name: CallTracker}}
        self._tool_trackers: Dict[str, Dict[str, CallTracker]] = defaultdict(
            lambda: defaultdict(CallTracker)
        )
        # Hourly session tracking (separate window)
        self._hourly_sessions: Dict[str, CallTracker] = defaultdict(CallTracker)
        self._global_lock = asyncio.Lock()

    async def check_rate_limit(
        self,
        session_id: str,
        tool_name: Optional[str] = None
    ) -> RateLimitResult:
        """Check if a call is allowed under rate limits.

        Args:
            session_id: The session making the call
            tool_name: Optional tool name for tool-specific limits

        Returns:
            RateLimitResult with allowed status and retry info
        """
        if not self.config.enabled:
            return RateLimitResult(allowed=True)

        # Check session hourly limit first
        hourly_result = await self._check_hourly_limit(session_id)
        if not hourly_result.allowed:
            return hourly_result

        # Check tool-specific limit if tool_name provided
        if tool_name:
            tool_result = await self._check_tool_limit(session_id, tool_name)
            if not tool_result.allowed:
                return tool_result

        # Check session-level limit (all tools combined)
        session_result = await self._check_session_limit(session_id)
        if not session_result.allowed:
            return session_result

        # All checks passed - record the call
        await self._record_call(session_id, tool_name)
        return RateLimitResult(allowed=True)

    async def _check_hourly_limit(self, session_id: str) -> RateLimitResult:
        """Check session hourly limit."""
        tracker = self._hourly_sessions[session_id]

        async with tracker.lock:
            calls_in_hour = tracker.count_calls_in_window(3600)  # 1 hour

            if calls_in_hour >= self.config.session_calls_per_hour:
                retry_after = tracker.get_retry_after_seconds(3600)
                return RateLimitResult(
                    allowed=False,
                    error_message=(
                        f"Session hourly limit exceeded: {calls_in_hour}/"
                        f"{self.config.session_calls_per_hour} calls/hour. "
                        f"Try again in {retry_after:.0f}s"
                    ),
                    retry_after_seconds=retry_after,
                    limit_type="session_hourly"
                )

        return RateLimitResult(allowed=True)

    async def _check_session_limit(self, session_id: str) -> RateLimitResult:
        """Check session-level per-minute limit."""
        tracker = self._sessions[session_id]
        # Use default per-minute limit for session
        limit = self.config.default_calls_per_minute

        async with tracker.lock:
            calls_in_window = tracker.count_calls_in_window(60)

            if calls_in_window >= limit:
                retry_after = tracker.get_retry_after_seconds(60)
                return RateLimitResult(
                    allowed=False,
                    error_message=(
                        f"Session rate limit exceeded: {calls_in_window}/{limit} "
                        f"calls/minute. Try again in {retry_after:.1f}s"
                    ),
                    retry_after_seconds=retry_after,
                    limit_type="session"
                )

        return RateLimitResult(allowed=True)

    async def _check_tool_limit(
        self,
        session_id: str,
        tool_name: str
    ) -> RateLimitResult:
        """Check tool-specific rate limit."""
        tool_config = self.config.get_tool_config(tool_name)
        tracker = self._tool_trackers[session_id][tool_name]

        async with tracker.lock:
            # Check per-minute limit
            calls_in_minute = tracker.count_calls_in_window(tool_config.window_seconds)

            if calls_in_minute >= tool_config.calls_per_minute:
                retry_after = tracker.get_retry_after_seconds(tool_config.window_seconds)
                return RateLimitResult(
                    allowed=False,
                    error_message=(
                        f"Tool '{tool_name}' rate limit exceeded: "
                        f"{calls_in_minute}/{tool_config.calls_per_minute} "
                        f"calls/minute. Try again in {retry_after:.1f}s"
                    ),
                    retry_after_seconds=retry_after,
                    limit_type="tool"
                )

            # Check hourly limit if configured
            if tool_config.calls_per_hour:
                calls_in_hour = tracker.count_calls_in_window(3600)
                if calls_in_hour >= tool_config.calls_per_hour:
                    retry_after = tracker.get_retry_after_seconds(3600)
                    return RateLimitResult(
                        allowed=False,
                        error_message=(
                            f"Tool '{tool_name}' hourly limit exceeded: "
                            f"{calls_in_hour}/{tool_config.calls_per_hour} "
                            f"calls/hour. Try again in {retry_after:.0f}s"
                        ),
                        retry_after_seconds=retry_after,
                        limit_type="tool_hourly"
                    )

        return RateLimitResult(allowed=True)

    async def _record_call(
        self,
        session_id: str,
        tool_name: Optional[str] = None
    ) -> None:
        """Record a call for rate limiting."""
        # Record in session tracker
        session_tracker = self._sessions[session_id]
        async with session_tracker.lock:
            session_tracker.record_call()

        # Record in hourly tracker
        hourly_tracker = self._hourly_sessions[session_id]
        async with hourly_tracker.lock:
            hourly_tracker.record_call()

        # Record in tool tracker if tool specified
        if tool_name:
            tool_tracker = self._tool_trackers[session_id][tool_name]
            async with tool_tracker.lock:
                tool_tracker.record_call()

    async def cleanup_session(self, session_id: str) -> None:
        """Remove tracking data for a session."""
        async with self._global_lock:
            self._sessions.pop(session_id, None)
            self._hourly_sessions.pop(session_id, None)
            self._tool_trackers.pop(session_id, None)

    def get_session_stats(self, session_id: str) -> Dict[str, Any]:
        """Get rate limiting stats for a session."""
        session_tracker = self._sessions.get(session_id)
        hourly_tracker = self._hourly_sessions.get(session_id)

        stats: Dict[str, Any] = {
            "session": {
                "calls_in_minute": 0,
                "remaining_per_minute": self.config.default_calls_per_minute,
                "limit_per_minute": self.config.default_calls_per_minute,
            },
            "hourly": {
                "calls_in_hour": 0,
                "remaining_per_hour": self.config.session_calls_per_hour,
                "limit_per_hour": self.config.session_calls_per_hour,
            },
            "tools": {}
        }

        if session_tracker:
            calls = session_tracker.count_calls_in_window(60)
            stats["session"]["calls_in_minute"] = calls
            stats["session"]["remaining_per_minute"] = max(
                0, self.config.default_calls_per_minute - calls
            )

        if hourly_tracker:
            calls = hourly_tracker.count_calls_in_window(3600)
            stats["hourly"]["calls_in_hour"] = calls
            stats["hourly"]["remaining_per_hour"] = max(
                0, self.config.session_calls_per_hour - calls
            )

        # Tool-level stats
        tool_trackers = self._tool_trackers.get(session_id, {})
        for tool_name, tracker in tool_trackers.items():
            tool_config = self.config.get_tool_config(tool_name)
            calls = tracker.count_calls_in_window(60)
            stats["tools"][tool_name] = {
                "calls_in_minute": calls,
                "remaining_per_minute": max(0, tool_config.calls_per_minute - calls),
                "limit_per_minute": tool_config.calls_per_minute,
            }

        return stats


# Global rate limiter instance (initialized lazily)
_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter(config: Optional[RateLimitConfig] = None) -> RateLimiter:
    """Get or create the global rate limiter instance."""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter(config)
    return _rate_limiter


def reset_rate_limiter() -> None:
    """Reset the global rate limiter (for testing)."""
    global _rate_limiter
    _rate_limiter = None


def rate_limited(
    session_id_param: str = "session_id",
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator to apply rate limiting to async functions.

    Args:
        session_id_param: Name of the parameter containing the session ID

    Returns:
        Decorated function with rate limiting applied

    Example:
        @rate_limited(session_id_param="session_id")
        async def my_tool(services, session_id: str, query: str) -> dict:
            ...
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            rate_limiter = get_rate_limiter()

            # Extract session_id from kwargs or positional args
            session_id = kwargs.get(session_id_param)

            if not session_id:
                # Session ID not found - skip rate limiting but log warning
                logger.debug(
                    "Rate limiting skipped: no %s parameter in %s",
                    session_id_param,
                    func.__name__,
                )
                return await func(*args, **kwargs)

            # Check rate limit with tool name
            result = await rate_limiter.check_rate_limit(
                session_id,
                tool_name=func.__name__
            )

            if not result.allowed:
                logger.warning(
                    "Rate limit hit for session %s on tool %s: %s",
                    session_id,
                    func.__name__,
                    result.limit_type,
                )
                return result.to_error_response()

            return await func(*args, **kwargs)

        return wrapper

    return decorator
