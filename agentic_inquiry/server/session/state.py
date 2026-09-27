"""Session State - Turn counter, checkpoints, topic tracking.

Manages per-session state including turn counting, checkpoint
detection, and recent query history.
"""

import logging
import time

logger = logging.getLogger("ai.server.session")


class SessionState:
    """Per-session state management."""

    def __init__(self, config: dict | None = None) -> None:
        config = config or {}
        checkpoints = config.get("checkpoints", {})
        self._checkpoint_interval = checkpoints.get("interval_turns", 5)

        self.turn_count = 0
        self.recent_queries: list[dict] = []
        self.current_topic: str = ""
        self.started_at = time.time()
        self._session_changes: list[dict] = []

    def increment_turn(self) -> dict:
        """Increment turn counter and check for checkpoint."""
        self.turn_count += 1
        is_checkpoint = (
            self.turn_count > 0 and self.turn_count % self._checkpoint_interval == 0
        )
        return {
            "turn": self.turn_count,
            "checkpoint": is_checkpoint,
        }

    def add_query(self, query: str, topic: str = "") -> None:
        """Record a recent query."""
        self.recent_queries.append(
            {
                "query": query[:200],
                "turn": self.turn_count,
                "timestamp": time.time(),
            }
        )
        # Keep last 20 queries
        if len(self.recent_queries) > 20:
            self.recent_queries = self.recent_queries[-20:]
        if topic:
            self.current_topic = topic

    def record_file_change(self, file_path: str, change_type: str) -> None:
        """Record a file change event."""
        self._session_changes.append(
            {
                "file_path": file_path,
                "change_type": change_type,
                "timestamp": time.time(),
            }
        )

    def get_state(self) -> dict:
        """Get current session state."""
        return {
            "turn": self.turn_count,
            "recent_queries": self.recent_queries[-10:],
            "topic": self.current_topic,
            "uptime": time.time() - self.started_at,
            "file_changes": len(self._session_changes),
        }

    def update_state(
        self,
        turn: int | None = None,
        query: str | None = None,
        topic: str | None = None,
    ) -> dict:
        """Update session state."""
        if turn is not None:
            self.turn_count = turn
        if query is not None:
            self.add_query(query, topic or "")
        elif topic is not None:
            self.current_topic = topic
        return {"updated": True}

    @property
    def pending_changes(self) -> list[dict]:
        """Get accumulated file changes."""
        return list(self._session_changes)

    def clear_changes(self) -> int:
        """Clear accumulated changes and return count."""
        count = len(self._session_changes)
        self._session_changes.clear()
        return count
