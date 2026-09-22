"""agv Daemon Service Orchestrator.

Wires together all managers and provides the high-level API
that route handlers call. Handles lazy initialization.
"""

import asyncio
import logging
import re

logger = logging.getLogger("agv.daemon.orchestrator")

# Patterns for classifying bash commands
TEST_PATTERNS = re.compile(
    r"(pytest|unittest|jest|mocha|cargo test|go test|mvn test|gradle test)",
    re.IGNORECASE,
)
BUILD_PATTERNS = re.compile(
    r"(make|build|compile|cargo build|go build|mvn package|gradle build|npm run build|tsc)",
    re.IGNORECASE,
)
GIT_PATTERNS = re.compile(
    r"(git commit|git push|git merge|git rebase|git cherry-pick)",
    re.IGNORECASE,
)
DEPLOY_PATTERNS = re.compile(
    r"(deploy|kubectl|docker push|helm|terraform apply)",
    re.IGNORECASE,
)

# File importance patterns
CONFIG_PATTERNS = re.compile(
    r"(config|settings|\.env|\.yaml|\.yml|\.toml|\.json|Makefile|Dockerfile|docker-compose)",
    re.IGNORECASE,
)
ENTRY_PATTERNS = re.compile(
    r"(main\.|index\.|app\.|server\.|__main__|manage\.py|wsgi|asgi)",
    re.IGNORECASE,
)
TEST_FILE_PATTERNS = re.compile(
    r"(test_|_test\.|\.test\.|spec\.|\.spec\.)", re.IGNORECASE
)


class ServiceOrchestrator:
    """Coordinates all daemon managers."""

    def __init__(
        self,
        workspace: str,
        project_id: str,
        config: dict,
    ) -> None:
        self.workspace = workspace
        self.project_id = project_id
        self.config = config

        # Managers (created lazily)
        self._context_manager = None
        self._memory_manager = None
        self._cache_manager = None
        self._version_manager = None

        # State
        self.initialized = False
        self.turn_count = 0
        self._checkpoint_interval = config.get("checkpoints", {}).get(
            "interval_turns", 5
        )
        self._init_lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Lazy initialization of agv services."""
        if self.initialized:
            return

        async with self._init_lock:
            if self.initialized:
                return

            logger.info(
                "Initializing orchestrator for %s (project=%s)",
                self.workspace,
                self.project_id,
            )

            try:
                from .managers.cache import CacheManager
                from .managers.context import ContextManager
                from .managers.memory import MemoryManager
                from .managers.version import VersionManager

                self._cache_manager = CacheManager(self.config)
                self._version_manager = VersionManager(
                    workspace=self.workspace,
                    config=self.config,
                )
                self._memory_manager = MemoryManager(
                    workspace=self.workspace,
                    project_id=self.project_id,
                    config=self.config,
                    cache_manager=self._cache_manager,
                    version_manager=self._version_manager,
                )
                self._context_manager = ContextManager(
                    workspace=self.workspace,
                    project_id=self.project_id,
                    config=self.config,
                    memory_manager=self._memory_manager,
                    cache_manager=self._cache_manager,
                )

                await self._memory_manager.initialize()
                await self._context_manager.initialize()

                self.initialized = True
                logger.info("Orchestrator initialized successfully")
            except Exception:
                logger.exception("Failed to initialize orchestrator")
                raise

    async def shutdown(self) -> None:
        """Graceful shutdown."""
        if self._memory_manager:
            await self._memory_manager.shutdown()
        if self._context_manager:
            await self._context_manager.shutdown()
        logger.info("Orchestrator shut down")

    # --- Context Assembly ---

    async def assemble_context(
        self,
        prompt: str,
        session_id: str,
    ) -> dict:
        """Analyze signals and assemble context for injection."""
        return await self._context_manager.assemble(prompt, session_id)

    # --- Memory Operations ---

    async def store_memory(
        self,
        content: str,
        category: str = "observation",
        importance: float = 0.7,
        metadata: dict | None = None,
        file_paths: list[str] | None = None,
        entity_names: list[str] | None = None,
    ) -> str:
        """Store a memory with git versioning."""
        return await self._memory_manager.store(
            content=content,
            category=category,
            importance=importance,
            metadata=metadata,
            file_paths=file_paths,
            entity_names=entity_names,
        )

    async def recall_memories(
        self,
        query: str,
        limit: int = 5,
        include_global: bool = False,
    ) -> list[dict]:
        """Recall memories for a query."""
        return await self._memory_manager.recall(
            query=query,
            limit=limit,
            include_global=include_global,
        )

    # --- Turn & Checkpoints ---

    def increment_turn(self) -> int:
        """Increment and return turn counter."""
        self.turn_count += 1
        # Sync turn counter to context manager for deduplication
        if self._context_manager:
            self._context_manager._current_turn = self.turn_count
        return self.turn_count

    def is_checkpoint_due(self) -> bool:
        """Check if a memory checkpoint is due."""
        return (
            self.turn_count > 0
            and self.turn_count % self._checkpoint_interval == 0
        )

    # --- Cache ---

    def invalidate_cache(self, file_paths: list[str]) -> None:
        """Invalidate caches affected by file changes."""
        if self._cache_manager:
            self._cache_manager.invalidate(file_paths)

    async def prefetch(
        self, queries: list[str], session_id: str
    ) -> None:
        """Background prefetch for predicted queries."""
        if not self._context_manager:
            return
        for query in queries[:3]:  # Cap at 3
            try:
                await self._context_manager.assemble(query, session_id)
            except Exception:
                logger.debug("Prefetch failed for query: %s", query[:50])

    # --- File Classification ---

    def classify_file_importance(self, file_path: str) -> str | None:
        """Classify a file's importance for memory suggestions."""
        if not file_path:
            return None

        if CONFIG_PATTERNS.search(file_path):
            return "config"
        if ENTRY_PATTERNS.search(file_path):
            return "entry_point"
        if TEST_FILE_PATTERNS.search(file_path):
            return "test"
        return None

    # --- Bash Classification ---

    def classify_bash_command(
        self, command: str, exit_code: int, output: str
    ) -> dict:
        """Classify a bash command for memory capture."""
        category = "general"
        should_capture = False
        prompt = None

        if TEST_PATTERNS.search(command):
            category = "test"
            if exit_code != 0:
                should_capture = True
                prompt = (
                    "[agv Memory] Tests failed. Store the failure context: "
                    "which tests, root cause, and fix approach."
                )
            else:
                should_capture = True
                prompt = (
                    "[agv Memory] Tests passed. If this validates a significant "
                    "change, store what was tested and why."
                )
        elif BUILD_PATTERNS.search(command):
            category = "build"
            if exit_code != 0:
                should_capture = True
                prompt = (
                    "[agv Memory] Build failed. Store the error and resolution."
                )
        elif GIT_PATTERNS.search(command):
            category = "git"
            should_capture = True
            prompt = (
                "[agv Memory] Git operation completed. If this represents a "
                "significant milestone, store the context."
            )
        elif DEPLOY_PATTERNS.search(command):
            category = "deploy"
            should_capture = True
            prompt = (
                "[agv Memory] Deployment operation. Store the deployment "
                "context and any issues encountered."
            )

        return {
            "category": category,
            "exit_code": exit_code,
            "should_capture": should_capture,
            "prompt": prompt,
        }

    # --- Task Transitions ---

    def get_task_transition_prompt(
        self, task_id: str, status: str, subject: str
    ) -> str | None:
        """Generate a memory prompt for task status transitions."""
        if status == "completed":
            return (
                f"[agv Memory] Task completed: \"{subject}\". "
                "REQUIRED: If this task produced a decision with rationale, "
                "a gotcha worth avoiding, or a reusable pattern — store it now "
                "via /agv:memory save."
            )
        elif status == "in_progress":
            return (
                f"[agv Memory] Starting task: \"{subject}\". "
                "Note your approach and key assumptions."
            )
        elif status == "pending":
            return (
                f"[agv Memory] Task moved to pending: \"{subject}\". "
                "Note why — blocked, deprioritized, or needs rework?"
            )
        return None

    # --- Pre-Compact & Stop ---

    async def pre_compact_snapshot(self, session_id: str) -> dict:
        """Create working memory snapshot before compaction."""
        return await self._memory_manager.pre_compact_snapshot(session_id)

    async def session_stop(self, session_id: str) -> dict:
        """Handle session end - summary generation."""
        return await self._memory_manager.session_stop(session_id)

    # --- File Change Tracking ---

    async def record_file_change(
        self, file_path: str, change_type: str
    ) -> None:
        """Record a file change event for memory and cache."""
        # Invalidate relevant caches
        if self._cache_manager:
            self._cache_manager.invalidate([file_path])

        # Store as working memory if significant
        if self._memory_manager and self.classify_file_importance(file_path):
            await self._memory_manager.record_change(file_path, change_type)
