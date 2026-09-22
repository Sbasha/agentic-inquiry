"""Memory Manager - Store, recall, checkpoints, and lifecycle.

Handles aggressive memory capture, recall with project isolation,
pre-compact snapshots, and session summaries.
"""

import logging
import time
import uuid

logger = logging.getLogger("ai.daemon.memory")


class MemoryManager:
    """Memory operations for the daemon service."""

    def __init__(
        self,
        workspace: str,
        project_id: str,
        config: dict,
        cache_manager,
        version_manager,
    ) -> None:
        self.workspace = workspace
        self.project_id = project_id
        self.config = config
        self._cache_manager = cache_manager
        self._version_manager = version_manager

        # ai memory system (lazy init)
        self._memory_system = None
        self._memory_context = None
        self._initialized = False

        # Session state
        self.turn_count = 0
        self._session_changes: list[dict] = []

    async def initialize(self) -> None:
        """Initialize ai memory system."""
        if self._initialized:
            return

        try:
            from agentic_inquiry.config import Config
            from agentic_inquiry.embeddings.service import EmbeddingService
            from agentic_inquiry.memory.system import MemorySystem

            config = Config.load()
            embedding_service = EmbeddingService(config)
            self._memory_system = MemorySystem(config, embedding_service)
            await self._memory_system.initialize()

            self._memory_context = self._memory_system.create_agent_context(
                agent_id="ai-daemon",
                session_id=f"daemon-{self.project_id}",
                conversation_id=f"daemon-{self.project_id}",
                project_id=self.project_id,
            )

            # Run staleness check
            self._version_manager.update_last_commit()

            self._initialized = True
            logger.info("Memory manager initialized")
        except Exception:
            logger.warning(
                "ai memory system not available - using basic storage"
            )
            self._initialized = True

    async def shutdown(self) -> None:
        """Cleanup."""
        if self._memory_system:
            try:
                await self._memory_system.shutdown()
            except Exception:
                logger.debug("Memory system shutdown error", exc_info=True)

    async def store(
        self,
        content: str,
        category: str = "observation",
        importance: float = 0.7,
        metadata: dict | None = None,
        file_paths: list[str] | None = None,
        entity_names: list[str] | None = None,
    ) -> str:
        """Store a memory with git versioning.

        Returns memory ID.
        """
        memory_id = str(uuid.uuid4())[:8]

        # Add version metadata
        version_meta = self._version_manager.create_version_metadata(
            file_paths=file_paths,
            entity_names=entity_names,
        )

        combined_metadata = {
            "category": category,
            "project_id": self.project_id,
            "scope": "project",
            **(metadata or {}),
            **version_meta,
        }

        if self._memory_system and self._memory_context:
            try:
                result = await self._memory_system.store(
                    content=content,
                    context=self._memory_context,
                    importance=importance,
                    metadata=combined_metadata,
                )
                memory_id = str(getattr(result, "id", memory_id))
                logger.debug("Memory stored: %s (importance=%.1f)", memory_id, importance)
            except Exception:
                logger.warning("ai memory store failed, using basic storage")
                # Fall through to basic storage

        # Invalidate memory cache
        self._cache_manager.invalidate_memories()

        return memory_id

    async def recall(
        self,
        query: str,
        limit: int = 5,
        include_global: bool = False,
    ) -> list[dict]:
        """Recall memories for a query with project isolation."""
        # Check cache
        cache_key = self._cache_manager.hash_key(
            query, self.project_id, str(include_global)
        )
        cached = self._cache_manager.get_memories(cache_key)
        if cached is not None:
            return cached

        memories = []

        if self._memory_system and self._memory_context:
            try:
                results = await self._memory_system.retrieve(
                    query=query,
                    context=self._memory_context,
                    limit=limit,
                    strategy="adaptive",
                )

                # Handle both list and dict returns
                if isinstance(results, dict):
                    items = results.get("results", [])
                else:
                    items = results

                for item in items:
                    memory = self._format_memory(item)
                    if memory:
                        memories.append(memory)
            except Exception:
                logger.debug("ai memory recall failed", exc_info=True)

        # Apply version staleness check
        memories = self._version_manager.check_staleness(memories)

        # Filter by confidence gate
        confidence_gate = self.config.get("context", {}).get(
            "confidence_gate", 0.7
        )
        # Include stale but flag them (don't filter out)
        for m in memories:
            if m.get("confidence", 1.0) < confidence_gate:
                m["stale"] = True

        # Cache results
        self._cache_manager.put_memories(cache_key, memories)

        return memories[:limit]

    async def record_change(self, file_path: str, change_type: str) -> None:
        """Record a file change as working memory."""
        self._session_changes.append(
            {
                "file_path": file_path,
                "change_type": change_type,
                "timestamp": time.time(),
            }
        )

        # Auto-store if significant accumulation
        if len(self._session_changes) >= 5:
            files = [c["file_path"] for c in self._session_changes[-5:]]
            await self.store(
                content=f"Modified files: {', '.join(files)}",
                category="working",
                importance=0.3,
                file_paths=files,
            )

    async def pre_compact_snapshot(self, session_id: str) -> dict:
        """Create working memory snapshot before context compaction.

        This is a HARD GATE - must complete before compaction.
        """
        prompt_parts = []

        # Store accumulated changes
        if self._session_changes:
            files = list({c["file_path"] for c in self._session_changes})
            await self.store(
                content=f"Session file changes before compaction: {', '.join(files[:20])}",
                category="working",
                importance=0.5,
                file_paths=files[:20],
            )
            prompt_parts.append(
                f"[ai] Auto-saved {len(files)} file changes."
            )

        # Build the mandatory prompt
        prompt = (
            "[ai Pre-Compact] Context is about to compress. "
            "REQUIRED: Store any decisions, discoveries, or reusable patterns "
            "from this work NOW via /ai:memory save. "
            "Run TaskList to check completed and in-progress tasks. "
            "For each, evaluate: did it produce a decision, gotcha, or pattern?\n"
        )

        if prompt_parts:
            prompt = "\n".join(prompt_parts) + "\n\n" + prompt

        return {
            "stored": bool(self._session_changes),
            "prompt": prompt,
        }

    async def session_stop(self, session_id: str) -> dict:
        """Handle session end - generate summary prompt.

        This is a HARD GATE - must complete before session ends.
        """
        # Store final change batch
        if self._session_changes:
            files = list({c["file_path"] for c in self._session_changes})
            await self.store(
                content=f"Session end file changes: {', '.join(files[:20])}",
                category="working",
                importance=0.4,
                file_paths=files[:20],
            )

        prompt = (
            "[ai Stop] Session ending. "
            "REQUIRED: Review your work this session. Run TaskList to see completed tasks. "
            "For EACH completed task, store via /ai:memory save:\n"
            "- Decisions made (with rationale and alternatives considered)\n"
            "- Gotchas discovered (things that weren't obvious)\n"
            "- Patterns learned (reusable approaches)\n"
            "- Architecture insights (how components connect)\n\n"
            "If nothing was learned, explicitly state why. "
            "Do NOT end session without storing learnings."
        )

        return {
            "stored": bool(self._session_changes),
            "prompt": prompt,
        }

    def _format_memory(self, item) -> dict | None:
        """Format a memory retrieval result into a dict."""
        try:
            if hasattr(item, "memory"):
                mem = item.memory
                return {
                    "content": getattr(mem, "content", str(mem)),
                    "created": str(
                        getattr(mem, "created_at", "unknown")
                    ),
                    "importance": getattr(mem, "importance", 0.5),
                    "confidence": getattr(
                        mem, "metadata", {}
                    ).get("confidence", 1.0)
                    if hasattr(mem, "metadata")
                    else 1.0,
                    "file_paths": getattr(
                        mem, "metadata", {}
                    ).get("file_paths", [])
                    if hasattr(mem, "metadata")
                    else [],
                    "category": getattr(
                        mem, "metadata", {}
                    ).get("category", "unknown")
                    if hasattr(mem, "metadata")
                    else "unknown",
                }
            elif isinstance(item, dict):
                return {
                    "content": item.get("content", ""),
                    "created": item.get("created", "unknown"),
                    "importance": item.get("importance", 0.5),
                    "confidence": item.get("confidence", 1.0),
                    "file_paths": item.get("file_paths", []),
                    "category": item.get("category", "unknown"),
                }
            else:
                return {
                    "content": str(item),
                    "created": "unknown",
                    "importance": 0.5,
                    "confidence": 1.0,
                    "file_paths": [],
                    "category": "unknown",
                }
        except Exception:
            return None
