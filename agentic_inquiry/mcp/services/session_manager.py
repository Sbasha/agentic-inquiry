"""Session lifecycle management for MCP server.

This module provides session management functionality including:
- Session creation with project statistics
- Hybrid persistence (memory + database)
- Session validation and retrieval
- Session cleanup and expiry management
- Session regeneration for security (SEC-005)
- Audit logging for session changes

SEC-005: Implements session fixation prevention with:
- Session ID regeneration on project change
- Audit logging for session lifecycle events
- Max session age enforcement
"""

import asyncio
import uuid
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, List, Literal, TYPE_CHECKING

from agentic_inquiry.database.filters import eq
from agentic_inquiry.mcp.models.session import Session, ProjectStatistics
from agentic_inquiry.config import Config
from agentic_inquiry.events.models import EventStatus
from agentic_inquiry.mcp.services.persistence.protocol import SessionStorageProtocol
from agentic_inquiry.storage.facade import StorageFacade
from agentic_inquiry.utils import get_attr as _get_attr

if TYPE_CHECKING:
    from agentic_inquiry.memory.system import MemorySystem
    from agentic_inquiry.events.system import EventSystem

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages agent work sessions.

    Responsibilities:
    - Create and track sessions
    - Session validation
    - Session state management
    - Log file management
    - Project statistics gathering
    - Hybrid persistence (memory + DB)
    """

    def __init__(
        self,
        db_manager: StorageFacade,
        config: Config,
        memory_system: Optional["MemorySystem"] = None,
        event_system: Optional["EventSystem"] = None,
        storage: Optional[SessionStorageProtocol] = None
    ):
        """Initialize session manager.

        Args:
            db_manager: StorageFacade instance providing unified storage access
            config: Configuration object
            memory_system: Optional memory system for tracking memories
            event_system: Optional event system for emitting session events
            storage: Optional session storage backend (defaults based on backend type)
        """
        self.db_manager: StorageFacade = db_manager
        self.config = config
        self.memory_system = memory_system
        self.event_system = event_system

        # Backend type is retrieved from the facade
        backend_type = self.db_manager._backend_type

        # Initialize storage backend based on backend type
        if storage is None:
            if backend_type == "lancedb":
                from agentic_inquiry.mcp.services.persistence.lancedb_backend import (
                    LanceDBSessionStorage,
                )
                self.storage: SessionStorageProtocol = LanceDBSessionStorage(db_manager)
            else:
                # CLI-first architecture: agents invoke CLI commands, context lives
                # in the agent conversation. In-memory sessions are sufficient.
                from agentic_inquiry.mcp.services.persistence.memory_backend import (
                    InMemorySessionStorage,
                )
                self.storage = InMemorySessionStorage()
                logger.info(
                    "Using InMemorySessionStorage for %s backend - sessions will NOT persist",
                    backend_type
                )
        else:
            self.storage = storage

        # In-memory cache for active sessions
        self.active_sessions: Dict[str, Session] = {}

        # Session expiry configuration from config
        self.session_ttl_hours = config.mcp.session.ttl_hours

        # Log directory
        self.log_dir = Path.home() / ".agentic-inquiry" / "logs" / "sessions"
        self.log_dir.mkdir(parents=True, exist_ok=True)
    
    async def create_session(
        self,
        project_id: str,
        description: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create new session and return metadata.
        
        Implements Requirement 1: Session Management
        - Creates session with unique ID
        - Gathers project statistics
        - Returns appropriate status and guidance
        
        Args:
            project_id: Project identifier
            description: Optional session description
            
        Returns:
            Session metadata dictionary with:
            - session_id: Unique session identifier
            - project_id: Project identifier
            - status: "empty", "partial", or "ready"
            - statistics: Project statistics
            - log_file: Path to session log file
            - guidance: Helpful message based on project state
            - next_steps: List of suggested actions
        """
        # Generate unique session ID
        session_id = str(uuid.uuid4())
        
        # Create log file
        log_file = self.log_dir / f"{session_id}.log"
        
        # Gather project statistics
        statistics = await self._gather_project_statistics(project_id)
        
        # Create session object
        now = datetime.now()
        session = Session(
            session_id=session_id,
            project_id=project_id,
            created_at=now,
            last_active=now,
            description=description,
            log_file=log_file,
            status="active"  # Set initial status
            # state, is_expired, and history use defaults from model
        )
        
        # Store in memory cache
        self.active_sessions[session_id] = session
        
        # Persist to database
        await self._persist_session(session)
        
        # Emit session.created event
        if self.event_system:
            await self.event_system.emit(
                "session.created",
                source="SessionManager",
                status=EventStatus.COMPLETED,
                session_id=session_id,
                project_id=project_id,
                description=description,
                created_at=now.isoformat()
            )
        
        # Determine status and guidance
        status, guidance, next_steps = self._generate_session_guidance(statistics)
        
        logger.info("Created session %s for project %s with status %s", session_id, project_id, status)

        # Audit log: Session created
        await self._audit_log(
            "session.created",
            session_id=session_id,
            project_id=project_id,
            description=description
        )

        return {
            "session_id": session_id,
            "project_id": project_id,
            "created_at": now.isoformat(),
            "state": session.state.value,  # Session lifecycle state
            "status": status,  # Index status
            "statistics": statistics.to_dict(),
            "log_file": str(log_file),
            "guidance": guidance,
            "next_steps": next_steps
        }

    async def regenerate_session(
        self,
        old_session_id: str,
        new_project_id: Optional[str] = None,
        reason: str = "security"
    ) -> Dict[str, Any]:
        """Regenerate session with new ID (SEC-005: Session fixation prevention).

        Creates a new session ID while preserving session state and history.
        Used when:
        - Project changes (potential cross-project data leakage prevention)
        - Authentication events
        - Explicit security refresh requested

        Args:
            old_session_id: Current session identifier
            new_project_id: Optional new project ID (if changing projects)
            reason: Reason for regeneration (for audit log)

        Returns:
            New session metadata with fresh session_id

        Raises:
            ValueError: If old session not found or expired
        """
        # Load old session
        old_session = await self.get_session(old_session_id, include_history=True)

        if not old_session:
            raise ValueError(f"Session {old_session_id} not found")

        if old_session.is_expired:
            raise ValueError(f"Session {old_session_id} has expired")

        # Enforce max session age (1 hour for regeneration)
        session_age_hours = (datetime.now() - old_session.created_at).total_seconds() / 3600
        max_age_hours = getattr(self.config.mcp.session, 'max_age_hours', 1.0)
        if session_age_hours > max_age_hours:
            # Audit log: Session age exceeded
            await self._audit_log(
                "session.age_exceeded",
                session_id=old_session_id,
                project_id=old_session.project_id,
                age_hours=session_age_hours,
                max_age_hours=max_age_hours
            )
            raise ValueError(
                f"Session {old_session_id} exceeds max age ({session_age_hours:.1f}h > {max_age_hours}h). "
                "Please create a new session."
            )

        # Determine project ID for new session
        project_id = new_project_id or old_session.project_id
        project_changed = project_id != old_session.project_id

        # Generate new session ID
        new_session_id = str(uuid.uuid4())

        # Create new log file
        log_file = self.log_dir / f"{new_session_id}.log"

        # Create new session preserving relevant state
        now = datetime.now()
        new_session = Session(
            session_id=new_session_id,
            project_id=project_id,
            created_at=now,  # Fresh creation time for security
            last_active=now,
            description=old_session.description,
            log_file=log_file,
            status="active",
            # Preserve history only if same project (prevent data leakage)
            history=[] if project_changed else old_session.history,
            # Preserve context state only if same project
            context_state={} if project_changed else old_session.context_state,
            events=[]  # Fresh events for new session
        )

        # Mark old session as expired
        old_session.mark_expired()
        await self._persist_session(old_session)

        # Remove old session from memory cache
        if old_session_id in self.active_sessions:
            del self.active_sessions[old_session_id]

        # Store new session
        self.active_sessions[new_session_id] = new_session
        await self._persist_session(new_session)

        # Audit log: Session regenerated
        await self._audit_log(
            "session.regenerated",
            old_session_id=old_session_id,
            new_session_id=new_session_id,
            project_id=project_id,
            old_project_id=old_session.project_id,
            project_changed=project_changed,
            reason=reason,
            history_preserved=not project_changed
        )

        # Emit session events
        if self.event_system:
            await self.event_system.emit(
                "session.regenerated",
                source="SessionManager",
                status=EventStatus.COMPLETED,
                old_session_id=old_session_id,
                new_session_id=new_session_id,
                project_id=project_id,
                reason=reason
            )

        logger.info(
            "Regenerated session %s -> %s (project: %s, reason: %s)",
            old_session_id, new_session_id, project_id, reason
        )

        # Gather fresh statistics
        statistics = await self._gather_project_statistics(project_id)
        status, guidance, next_steps = self._generate_session_guidance(statistics)

        return {
            "session_id": new_session_id,
            "old_session_id": old_session_id,
            "project_id": project_id,
            "created_at": now.isoformat(),
            "state": new_session.state.value,
            "status": status,
            "statistics": statistics.to_dict(),
            "log_file": str(log_file),
            "guidance": guidance,
            "next_steps": next_steps,
            "regeneration_reason": reason,
            "project_changed": project_changed
        }

    async def change_project(
        self,
        session_id: str,
        new_project_id: str
    ) -> Dict[str, Any]:
        """Change project for a session, regenerating session ID for security.

        SEC-005: Regenerates session ID when project changes to prevent
        session fixation attacks and cross-project data leakage.

        Args:
            session_id: Current session identifier
            new_project_id: New project identifier

        Returns:
            New session metadata with regenerated session_id
        """
        return await self.regenerate_session(
            old_session_id=session_id,
            new_project_id=new_project_id,
            reason="project_change"
        )

    async def _audit_log(
        self,
        event_type: str,
        **kwargs: Any
    ) -> None:
        """Log event for audit purposes.
        
        Args:
            event_type: Type of event
            **kwargs: Additional event data
        """
        # Audit logging disabled for performance
        pass

        # Log to standard logger at INFO level for security audit
        logger.info("AUDIT: %s - %s", event_type, kwargs)

        # Also emit as event if event system available
        if self.event_system:
            await self.event_system.emit(
                f"audit.{event_type}",
                source="SessionManager.audit",
                status=EventStatus.COMPLETED,
                **kwargs
            )

    async def validate_session(self, session_id: str) -> bool:
        """Check if session is valid.
        
        Args:
            session_id: Session identifier
            
        Returns:
            True if session exists and is not expired
        """
        # Check memory cache first
        if session_id in self.active_sessions:
            cached_session = self.active_sessions[session_id]
            if not cached_session.is_expired:
                return True

        # Check database
        db_session = await self._load_session_from_db(session_id)
        if db_session and not db_session.is_expired:
            # Cache it
            self.active_sessions[session_id] = db_session
            return True

        return False

    async def track_tool_call(
        self,
        session_id: str,
        tool_name: str,
        params: Dict[str, Any]
    ) -> bool:
        """Track a tool call in session history.

        Args:
            session_id: Session identifier
            tool_name: Name of the tool being called
            params: Parameters passed to the tool

        Returns:
            True if tracking succeeded, False otherwise
        """
        session = await self.get_session(session_id)
        if not session:
            return False

        session.add_to_history(tool_name, params)
        self.active_sessions[session_id] = session
        await self._persist_session(session)
        return True

    async def get_session(
        self,
        session_id: str,
        include_history: bool = False
    ) -> Optional[Session]:
        """Retrieve session by ID.

        Args:
            session_id: Session identifier
            include_history: Whether to include full tool call history

        Returns:
            Session object or None if not found

        Raises:
            ValueError: If session_id is not a valid UUID format
        """
        # Validate session_id format (prevents session fixation)
        from agentic_inquiry.mcp.utils.validation import (
            validate_session_id,
            SessionIDValidationError,
        )
        try:
            session_id = validate_session_id(session_id)
        except SessionIDValidationError as e:
            raise ValueError(str(e))

        # Check memory cache first
        if session_id in self.active_sessions:
            cached_session = self.active_sessions[session_id]
            if not include_history:
                # Return copy without history for efficiency
                session_copy = Session(
                    session_id=cached_session.session_id,
                    project_id=cached_session.project_id,
                    created_at=cached_session.created_at,
                    last_active=cached_session.last_active,
                    description=cached_session.description,
                    log_file=cached_session.log_file,
                    state=cached_session.state,
                    status=cached_session.status,
                    history=[]
                )
                return session_copy
            return cached_session

        # Load from database
        db_session = await self._load_session_from_db(session_id)
        if db_session:
            self.active_sessions[session_id] = db_session
            return db_session

        return None
    
    async def update_session(self, session: Session) -> None:
        """Update session in memory and database.
        
        Args:
            session: Session object to update
        """
        # Update in memory
        self.active_sessions[session.session_id] = session
        
        # Persist to database
        await self._persist_session(session)
        
        # Emit session.updated event
        if self.event_system:
            await self.event_system.emit(
                "session.updated",
                source="SessionManager",
                status=EventStatus.COMPLETED,
                session_id=session.session_id,
                project_id=session.project_id,
                last_active=session.last_active.isoformat()
            )

    async def _count_memories_safe(self, project_id: str) -> int:
        """Count memories for project with comprehensive error handling.
        
        Args:
            project_id: Project identifier
            
        Returns:
            Number of memories, or 0 if unavailable
        """
        # Check if memory system is initialized
        if self.memory_system is None:
            logger.warning("Memory system is None, cannot count memories")
            return 0
        
        # Check if episodic layer exists
        if not hasattr(self.memory_system, 'episodic'):
            logger.warning("Memory system missing episodic attribute")
            return 0
        
        if self.memory_system.episodic is None:  # type: ignore[attr-defined]
            logger.warning("Episodic memory layer is None")
            return 0
        
        try:
            # Try to count via database
            count = await self.db_manager.count_records(
                table_name="memory_episodic",
                filters={"project_id": project_id}
            )
            return count
        except AttributeError as e:
            logger.error("Memory system missing required methods: %s", e)
            return 0
        except Exception as e:
            logger.error("Error counting memories for project %s: %s", project_id, e)
            return 0
    
    async def _gather_project_statistics(
        self,
        project_id: str
    ) -> ProjectStatistics:
        """Gather statistics about project's indexed content.
        
        Optimized to use count_records() for efficient counting without
        loading all data into memory. Uses asyncio.gather() for parallel
        execution of independent queries.
        
        Args:
            project_id: Project identifier
            
        Returns:
            ProjectStatistics object
        """
        # Initialize with default values
        stats = ProjectStatistics(
            total_chunks=0,
            total_memories=0,
            total_files=0,
            last_indexed=None,
            index_health="empty"
        )
        
        try:
            # Execute count queries in parallel for better performance
            try:
                stats.total_chunks, stats.total_memories, total_entities = await asyncio.gather(
                    self.db_manager.count_records(
                        table_name="document_chunks",
                        project_id=project_id,
                    ),
                    self._count_memories_safe(project_id),
                    self.db_manager.count_records(
                        table_name="graph_entities",
                        project_id=project_id,
                    ),
                    return_exceptions=False
                )
            except Exception as e:
                logger.error("Error gathering parallel statistics: %s", e)
                # Fall back to sequential if parallel fails
                try:
                    stats.total_chunks = await self.db_manager.count_records(
                        table_name="document_chunks",
                        filters={"project_id": project_id}
                    )
                except Exception:
                    stats.total_chunks = 0

                # Use safe memory counting
                stats.total_memories = await self._count_memories_safe(project_id)

                try:
                    total_entities = await self.db_manager.count_records(
                        table_name="graph_entities",
                        filters={"project_id": project_id}
                    )
                except Exception:
                    total_entities = 0
            
            # Now fetch detailed data only if we have chunks (more efficient)
            if stats.total_chunks > 0:
                # Fetch a sample of chunks for metadata analysis
                # Limit to reasonable number for language/file analysis
                sample_limit = min(1000, stats.total_chunks)
                chunks = await self.db_manager.advanced_filter(
                    table_name="document_chunks",
                    filters=eq("project_id", project_id),
                    limit=sample_limit
                )
                
                # Analyze unique files and languages from sample
                unique_files = set()
                languages: Dict[str, int] = {}
                
                for chunk in chunks:
                    file_path = chunk.get("file_path")
                    if file_path:
                        unique_files.add(file_path)
                        
                        # Track language distribution
                        language = chunk.get("language", "unknown")
                        languages[language] = languages.get(language, 0) + 1
                
                # If we sampled, estimate total files
                if sample_limit < stats.total_chunks:
                    # Estimate total unique files based on sample
                    sample_ratio = stats.total_chunks / sample_limit
                    estimated_files = int(len(unique_files) * sample_ratio)
                    stats.total_files = estimated_files
                    stats.indexed_file_count = estimated_files
                else:
                    stats.total_files = len(unique_files)
                    stats.indexed_file_count = len(unique_files)
                
                stats.languages = languages
                
                # Get last indexed timestamp from most recent chunk
                timestamps = [
                    chunk.get("created_at")
                    for chunk in chunks
                    if chunk.get("created_at")
                ]
                if timestamps:
                    # Convert to datetime if needed - filter out None values
                    valid_timestamps = [t for t in timestamps if t is not None]
                    latest = max(valid_timestamps) if valid_timestamps else None
                    if latest is not None:
                        if isinstance(latest, str):
                            stats.last_indexed = datetime.fromisoformat(latest)
                        else:
                            stats.last_indexed = latest
            else:
                stats.total_files = 0
                stats.indexed_file_count = 0
                stats.languages = {}
            
            # Count entities by type (only if we have entities)
            if total_entities > 0:
                try:
                    # Fetch sample of entities for type distribution
                    sample_limit = min(1000, total_entities)
                    entities = await self.db_manager.advanced_filter(
                        table_name="graph_entities",
                        filters=eq("project_id", project_id),
                        limit=sample_limit
                    )
                    entity_counts: Dict[str, int] = {}
                    for entity in entities:
                        entity_type = _get_attr(entity, "type", "unknown")  # Use canonical 'type' field
                        entity_counts[entity_type] = entity_counts.get(entity_type, 0) + 1
                    stats.entity_counts = entity_counts
                except Exception as e:
                    logger.debug("Could not count entities by type: %s", e)
                    stats.entity_counts = {}
            else:
                stats.entity_counts = {}
            
            # Determine index health
            if stats.is_empty():
                stats.index_health = "empty"
            elif stats.is_stale(days=30):
                stats.index_health = "stale"
            else:
                stats.index_health = "healthy"
            
        except Exception as e:
            logger.error("Error gathering project statistics: %s", e)
            stats.index_health = "empty"
        
        return stats

    async def get_project_statistics(
        self,
        project_id: str
    ) -> ProjectStatistics:
        """Get statistics about a project's indexed content.
        
        Public wrapper around _gather_project_statistics() for use by
        MCP tools that need project statistics without creating a session.
        
        Args:
            project_id: Project identifier
            
        Returns:
            ProjectStatistics object with information about:
            - total_chunks: Number of indexed document chunks
            - total_memories: Number of stored memories
            - total_files: Number of unique indexed files
            - index_health: Health status ("empty", "stale", "healthy")
            - languages: Distribution of programming languages
            - entity_counts: Count of entities by type
            - last_indexed: Timestamp of most recent indexing
            
        Example:
            >>> stats = await session_manager.get_project_statistics("my_project")
            >>> print(f"Project has {stats.total_chunks} chunks")
            >>> print(f"Health: {stats.index_health}")
        """
        return await self._gather_project_statistics(project_id)
    
    def _generate_session_guidance(
        self,
        statistics: ProjectStatistics
    ) -> tuple[Literal["empty", "partial", "ready"], str, List[str]]:
        """Generate guidance based on project statistics.
        
        Args:
            statistics: Project statistics
            
        Returns:
            Tuple of (status, guidance_message, next_steps)
        """
        if statistics.is_empty():
            return (
                "empty",
                "This project has no indexed content yet. Start by indexing your codebase.",
                [
                    "Use 'add_knowledge' to index files or directories",
                    "Index your main source directory first",
                    "Then index documentation and configuration files"
                ]
            )
        
        elif statistics.index_health == "stale":
            return (
                "partial",
                f"Project has {statistics.total_chunks} chunks but index is stale (last updated {statistics.last_indexed}).",
                [
                    "Consider re-indexing to capture recent changes",
                    "Use 'add_knowledge' to update specific files",
                    "Use 'search_knowledge' to explore existing content"
                ]
            )
        
        else:
            return (
                "ready",
                f"Project is ready with {statistics.total_chunks} chunks across {statistics.total_files} files.",
                [
                    "Use 'search_knowledge' to find relevant code and documentation",
                    "Use 'build_context' to assemble comprehensive context for tasks",
                    "Use 'understand_entity' to explore specific code symbols"
                ]
            )
    
    async def _persist_session(self, session: Session) -> None:
        """Persist session to storage backend.

        Delegates to self.storage.persist_session() for actual persistence.

        Args:
            session: Session to persist
        """
        try:
            await self.storage.persist_session(session)
        except Exception as e:
            logger.error("Error persisting session %s: %s", session.session_id, e)
            # Don't fail the operation - session is still in memory
    
    async def _load_session_from_db(self, session_id: str) -> Optional[Session]:
        """Load session from storage backend.

        Delegates to self.storage.load_session() for actual retrieval.

        Args:
            session_id: Session identifier

        Returns:
            Session object or None if not found
        """
        try:
            return await self.storage.load_session(session_id)
        except Exception as e:
            logger.error("Error loading session %s from storage: %s", session_id, e)
            return None
    
    async def list_sessions(
        self,
        project_id: Optional[str] = None,
        include_expired: bool = False,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """List sessions with optional filtering.

        Delegates to self.storage.list_sessions() for actual query.

        Args:
            project_id: Filter by project ID (optional)
            include_expired: Whether to include expired sessions
            limit: Maximum number of sessions to return

        Returns:
            List of session metadata dictionaries
        """
        try:
            sessions = await self.storage.list_sessions(
                project_id=project_id,
                include_expired=include_expired,
                limit=limit
            )

            # Emit session.queried event
            if self.event_system:
                await self.event_system.emit(
                    "session.queried",
                    source="SessionManager",
                    status=EventStatus.COMPLETED,
                    project_id=project_id,
                    include_expired=include_expired,
                    limit=limit,
                    results_count=len(sessions)
                )

            return sessions

        except Exception as e:
            logger.error("Error listing sessions: %s", e)
            return []
    
    async def resume_session(self, session_id: str) -> Dict[str, Any]:
        """Resume an existing session with state restoration.
        
        Args:
            session_id: Session identifier
            
        Returns:
            Session metadata with restored state
            
        Raises:
            ValueError: If session not found or expired
        """
        # Load session
        session = await self.get_session(session_id, include_history=True)
        
        if not session:
            raise ValueError(f"Session {session_id} not found")
        
        if session.is_expired:
            raise ValueError(f"Session {session_id} has expired")
        
        # Update last_active
        session.update_activity()
        await self.update_session(session)
        
        # Gather current project statistics
        statistics = await self._gather_project_statistics(session.project_id)
        
        # Generate status and guidance
        status, guidance, next_steps = self._generate_session_guidance(statistics)
        
        logger.info("Resumed session %s for project %s", session_id, session.project_id)
        
        return {
            "session_id": session.session_id,
            "project_id": session.project_id,
            "status": status,
            "statistics": statistics.to_dict(),
            "log_file": str(session.log_file),
            "guidance": guidance,
            "next_steps": next_steps,
            "state": session.context_state,  # Return context_state dict for multi-turn refinement
            "history_count": len(session.history),
            "created_at": session.created_at.isoformat(),
            "last_active": session.last_active.isoformat()
        }
    
    async def get_session_history(
        self,
        session_id: str,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get tool call history for a session.
        
        Args:
            session_id: Session identifier
            limit: Maximum number of history entries to return (most recent)
            
        Returns:
            List of tool call history entries
        """
        session = await self.get_session(session_id, include_history=True)
        
        if not session:
            return []
        
        history = session.history
        
        if limit and limit > 0:
            # Return most recent entries
            history = history[-limit:]
        
        return history
    
    async def add_event(
        self,
        session_id: str,
        event_type: str,
        data: Dict[str, Any]
    ) -> None:
        """Add an event to the session's event list.
        
        Args:
            session_id: Session identifier
            event_type: Type of event (e.g., "indexing_started", "indexing_completed")
            data: Event data dictionary
        """
        # Get session from memory (don't load from DB to avoid overhead)
        session = self.active_sessions.get(session_id)
        
        if not session:
            logger.warning("Cannot add event to non-existent session: %s", session_id)
            return
        
        # Create event with timestamp
        event = {
            "event_type": event_type,
            "timestamp": datetime.now().isoformat(),
            "data": data
        }
        
        # Add to session events (in memory only for now)
        session.events.append(event)
        
        # Persist updated session to database
        try:
            await self._persist_session(session)
        except Exception as e:
            logger.error("Failed to persist session %s after adding event: %s", session_id, e)
        
        logger.info(
            "Added event to session %s: type=%s, total_events=%s",
            session_id,
            event_type,
            len(session.events)
        )
    
    async def get_events(
        self,
        session_id: str,
        event_type: Optional[str] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get events from a session.
        
        Args:
            session_id: Session identifier
            event_type: Optional filter by event type
            limit: Maximum number of events to return (most recent)
            
        Returns:
            List of events
        """
        # Get session from memory first
        session = self.active_sessions.get(session_id)
        
        if not session:
            logger.debug("Session %s not in memory, trying to load from DB", session_id)
            session = await self.get_session(session_id, include_history=False)
        
        if not session:
            logger.warning("Session %s not found for get_events", session_id)
            return []
        
        events = session.events
        logger.debug("Retrieved %s events from session %s", len(events), session_id)
        
        # Filter by event type if specified
        if event_type:
            events = [e for e in events if e.get("event_type") == event_type]
        
        # Limit to most recent if specified
        if limit and limit > 0:
            events = events[-limit:]
        
        return events


class SessionCleanupManager:
    """Manages session cleanup and expiry.
    
    Responsibilities:
    - Identify expired sessions (48-hour TTL)
    - Archive session data
    - Clean up log files
    - Maintain database hygiene
    """
    
    def __init__(self, session_manager: SessionManager):
        """Initialize cleanup manager.

        Args:
            session_manager: SessionManager instance
        """
        self.session_manager = session_manager
        self.storage = session_manager.storage
        self.config = session_manager.config
        self.ttl_hours = session_manager.session_ttl_hours
    
    async def cleanup_expired_sessions(
        self,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """Find and clean up expired sessions.
        
        Args:
            dry_run: If True, only identify expired sessions without cleaning
            
        Returns:
            Cleanup summary with counts and details
        """
        logger.info("Starting session cleanup (dry_run=%s)", dry_run)
        
        # Find expired sessions
        expired_sessions = await self._find_expired_sessions()
        
        if dry_run:
            return {
                "dry_run": True,
                "expired_count": len(expired_sessions),
                "expired_sessions": [
                    {
                        "session_id": s["session_id"],
                        "project_id": s["project_id"],
                        "age_hours": s["age_hours"],
                        "inactive_hours": s["inactive_hours"]
                    }
                    for s in expired_sessions
                ]
            }
        
        # Clean up each expired session
        cleaned_count = 0
        archived_count = 0
        errors = []
        
        for session_info in expired_sessions:
            try:
                session_id = session_info["session_id"]
                
                # Archive session data
                archived = await self._archive_session(session_id)
                if archived:
                    archived_count += 1
                
                # Mark as expired in database
                await self._mark_session_expired(session_id)
                
                # Remove from memory cache
                if session_id in self.session_manager.active_sessions:
                    del self.session_manager.active_sessions[session_id]

                # Emit session.deleted event
                if self.session_manager.event_system:
                    await self.session_manager.event_system.emit(
                        "session.deleted",
                        source="SessionCleanup",
                        status=EventStatus.COMPLETED,
                        session_id=session_id,
                        project_id=session_info.get("project_id"),
                        reason="expired",
                        age_hours=session_info.get("age_hours"),
                        archived=archived
                    )

                cleaned_count += 1
                
            except Exception as e:
                logger.error("Error cleaning session %s: %s", session_id, e)
                errors.append({
                    "session_id": session_id,
                    "error": str(e)
                })
        
        logger.info("Cleaned %s expired sessions, archived %s", cleaned_count, archived_count)
        
        return {
            "dry_run": False,
            "expired_count": len(expired_sessions),
            "cleaned_count": cleaned_count,
            "archived_count": archived_count,
            "errors": errors
        }
    
    async def _find_expired_sessions(self) -> List[Dict[str, Any]]:
        """Find sessions that have exceeded TTL.

        Delegates to storage.find_expired_sessions() for actual query.

        Returns:
            List of expired session info dictionaries
        """
        try:
            return await self.storage.find_expired_sessions(
                ttl_hours=self.ttl_hours,
                limit=self.session_manager.config.mcp.query.max_limit
            )
        except Exception as e:
            logger.error("Error finding expired sessions: %s", e)
            return []
    
    async def _archive_session(self, session_id: str) -> bool:
        """Archive session data before cleanup.
        
        Args:
            session_id: Session identifier
            
        Returns:
            True if archived successfully
        """
        try:
            # Load full session
            session = await self.session_manager.get_session(
                session_id,
                include_history=True
            )
            
            if not session:
                return False
            
            # Create archive directory
            archive_dir = Path.home() / ".agentic-inquiry" / "archives" / "sessions"
            archive_dir.mkdir(parents=True, exist_ok=True)
            
            # Archive file path
            archive_file = archive_dir / f"{session_id}.json"
            
            # Write session data to archive
            import json
            with open(archive_file, 'w') as f:
                json.dump(session.to_dict(), f, indent=2)
            
            logger.debug("Archived session %s to %s", session_id, archive_file)
            return True
            
        except Exception as e:
            logger.error("Error archiving session %s: %s", session_id, e)
            return False
    
    async def _mark_session_expired(self, session_id: str) -> None:
        """Mark session as expired in storage.

        Delegates to storage.mark_session_expired() for actual update.

        Args:
            session_id: Session identifier
        """
        try:
            await self.storage.mark_session_expired(session_id)
            logger.debug("Marked session %s as expired", session_id)
        except Exception as e:
            logger.error("Error marking session %s as expired: %s", session_id, e)
    
    async def cleanup_old_archives(self, days: int = 90) -> Dict[str, Any]:
        """Remove archived sessions older than specified days.
        
        Args:
            days: Age threshold in days
            
        Returns:
            Cleanup summary
        """
        try:
            archive_dir = Path.home() / ".agentic-inquiry" / "archives" / "sessions"
            
            if not archive_dir.exists():
                return {"removed_count": 0, "errors": []}
            
            cutoff_time = datetime.now() - timedelta(days=days)
            removed_count = 0
            errors = []
            
            for archive_file in archive_dir.glob("*.json"):
                try:
                    # Check file modification time
                    mtime = datetime.fromtimestamp(archive_file.stat().st_mtime)
                    
                    if mtime < cutoff_time:
                        archive_file.unlink()
                        removed_count += 1
                        
                except Exception as e:
                    errors.append({
                        "file": str(archive_file),
                        "error": str(e)
                    })
            
            logger.info("Removed %s old archive files", removed_count)
            
            return {
                "removed_count": removed_count,
                "errors": errors
            }
            
        except Exception as e:
            logger.error("Error cleaning old archives: %s", e)
            return {"removed_count": 0, "errors": [{"error": str(e)}]}


__all__ = ["SessionManager", "SessionCleanupManager"]
