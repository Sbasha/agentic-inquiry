"""
Context management for the Memory System.

Manages agent contexts, profiles, and active context tracking
for personalization and learning.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from agentic_inquiry.memory.models import AgentProfile, MemoryContext

logger = logging.getLogger(__name__)


class ContextManager:
    """
    Manages agent contexts and profiles for memory personalization.

    Tracks active contexts, agent profiles, and provides automatic
    cleanup of stale contexts.
    """

    def __init__(
        self,
        max_concurrent_contexts: int = 100,
        cleanup_interval: int = 300,
        context_ttl: int = 3600,
    ) -> None:
        """
        Initialize ContextManager.

        Args:
            max_concurrent_contexts: Maximum number of concurrent active contexts
            cleanup_interval: Seconds between cleanup runs (default: 300)
            context_ttl: Seconds before a context is considered stale (default: 3600)
        """
        self.max_concurrent_contexts = max_concurrent_contexts
        self.cleanup_interval = cleanup_interval
        self.context_ttl = context_ttl

        # Internal storage
        self._active_contexts: dict[str, MemoryContext] = {}
        self._context_last_access: dict[str, datetime] = {}
        self._agent_profiles: dict[str, AgentProfile] = {}

        # Background task
        self._cleanup_task: asyncio.Task[None] | None = None
        self._running = False

    async def start(self) -> None:
        """Start background cleanup task."""
        if self._running:
            return

        self._running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("ContextManager started with cleanup interval %ds", self.cleanup_interval)

    async def stop(self) -> None:
        """Stop background cleanup task."""
        if not self._running:
            return

        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        logger.info("ContextManager stopped")

    async def _cleanup_loop(self) -> None:
        """Background task for cleaning up stale contexts."""
        while self._running:
            try:
                await asyncio.sleep(self.cleanup_interval)
                await self._cleanup_stale_contexts()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error in context cleanup loop")

    async def _cleanup_stale_contexts(self) -> None:
        """
        Remove stale contexts that haven't been accessed recently.

        Contexts are considered stale if they haven't been accessed
        within the context_ttl period.
        """
        now = datetime.now(timezone.utc)
        stale_threshold = now - timedelta(seconds=self.context_ttl)

        stale_keys = [
            key
            for key, last_access in self._context_last_access.items()
            if last_access < stale_threshold
        ]

        for key in stale_keys:
            self._active_contexts.pop(key, None)
            self._context_last_access.pop(key, None)

        if stale_keys:
            logger.debug("Cleaned up %d stale contexts", len(stale_keys))

    def create_context(
        self,
        agent_id: str,
        session_id: str,
        conversation_id: str,
        task_id: str | None = None,
        project_id: str | None = None,
        priority: float = 0.5,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryContext:
        """
        Create a new memory context.

        Args:
            agent_id: Agent identifier
            session_id: Session identifier
            conversation_id: Conversation identifier
            task_id: Optional task identifier
            project_id: Optional project identifier
            priority: Priority level (0.0-1.0)
            metadata: Optional metadata dictionary

        Returns:
            New MemoryContext instance

        Raises:
            ValueError: If max_concurrent_contexts limit reached
        """
        # Check capacity
        if len(self._active_contexts) >= self.max_concurrent_contexts:
            # Try cleanup first
            asyncio.create_task(self._cleanup_stale_contexts())
            if len(self._active_contexts) >= self.max_concurrent_contexts:
                raise ValueError(
                    f"Maximum concurrent contexts ({self.max_concurrent_contexts}) reached"
                )

        # Create context
        context = MemoryContext(
            agent_id=agent_id,
            session_id=session_id,
            conversation_id=conversation_id,
            task_id=task_id,
            project_id=project_id,
            priority=priority,
            metadata=metadata or {},
        )

        # Track context
        context_key = context.context_key
        self._active_contexts[context_key] = context
        self._context_last_access[context_key] = datetime.now(timezone.utc)

        logger.debug("Created context: %s", context_key)
        return context

    def get_active_contexts(
        self, agent_id: str | None = None, session_id: str | None = None
    ) -> list[MemoryContext]:
        """
        Get list of active contexts.

        Args:
            agent_id: Optional filter by agent_id
            session_id: Optional filter by session_id

        Returns:
            List of active MemoryContext instances
        """
        contexts = list(self._active_contexts.values())

        # Apply filters
        if agent_id:
            contexts = [c for c in contexts if c.agent_id == agent_id]
        if session_id:
            contexts = [c for c in contexts if c.session_id == session_id]

        return contexts

    def _touch_context(self, context: MemoryContext) -> None:
        """
        Update last access time for a context.

        Args:
            context: MemoryContext to touch
        """
        context_key = context.context_key
        if context_key in self._active_contexts:
            self._context_last_access[context_key] = datetime.now(timezone.utc)

    async def __aenter__(self) -> "ContextManager":
        """Async context manager entry."""
        await self.start()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.stop()

    def get_agent_profile(self, agent_id: str) -> AgentProfile:
        """
        Get or create agent profile.

        Args:
            agent_id: Agent identifier

        Returns:
            AgentProfile for the agent
        """
        if agent_id not in self._agent_profiles:
            self._agent_profiles[agent_id] = AgentProfile(agent_id=agent_id)
            logger.debug("Created new profile for agent: %s", agent_id)

        return self._agent_profiles[agent_id]

    def update_agent_profile(self, agent_id: str, profile: AgentProfile) -> None:
        """
        Update agent profile.

        Args:
            agent_id: Agent identifier
            profile: Updated AgentProfile
        """
        if profile.agent_id != agent_id:
            raise ValueError(f"Profile agent_id {profile.agent_id} does not match {agent_id}")

        profile.updated_at = datetime.now(timezone.utc)
        self._agent_profiles[agent_id] = profile
        logger.debug("Updated profile for agent: %s", agent_id)

    def update_agent_profile_from_feedback(
        self,
        agent_id: str,
        strategy: str,
        query_pattern: str | None = None,
        success: bool = True,
    ) -> None:
        """
        Update agent profile based on retrieval feedback.

        Args:
            agent_id: Agent identifier
            strategy: Retrieval strategy used
            query_pattern: Optional query pattern identifier
            success: Whether the retrieval was successful
        """
        profile = self.get_agent_profile(agent_id)

        # Update successful strategies
        if success:
            profile.update_successful_strategy(strategy)

        # Update query patterns
        if query_pattern:
            profile.update_query_pattern(query_pattern)

        logger.debug(
            "Updated profile for agent %s: strategy=%s, success=%s",
            agent_id,
            strategy,
            success,
        )

    def get_context_stats(self) -> dict[str, Any]:
        """
        Get statistics about active contexts and profiles.

        Returns:
            Dictionary with context and profile statistics
        """
        return {
            "active_contexts": len(self._active_contexts),
            "max_concurrent_contexts": self.max_concurrent_contexts,
            "agent_profiles": len(self._agent_profiles),
            "contexts_by_agent": self._get_contexts_by_agent(),
            "cleanup_interval": self.cleanup_interval,
            "context_ttl": self.context_ttl,
        }

    def _get_contexts_by_agent(self) -> dict[str, int]:
        """
        Get count of active contexts per agent.

        Returns:
            Dictionary mapping agent_id to context count
        """
        counts: dict[str, int] = {}
        for context in self._active_contexts.values():
            counts[context.agent_id] = counts.get(context.agent_id, 0) + 1
        return counts

