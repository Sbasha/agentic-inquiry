"""Information retrieval tools for MCP server.

These tools provide project and session information.
"""

import fnmatch
import logging
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Any, Dict, List, Optional, Pattern

from agentic_inquiry.database.filter_helpers import by_type
from agentic_inquiry.utils import get_attr as _get_attr

logger = logging.getLogger(__name__)

# Maximum regex pattern length to prevent complexity attacks
MAX_REGEX_PATTERN_LENGTH = 200

# Patterns that could cause catastrophic backtracking (ReDoS)
# These detect nested quantifiers and other dangerous constructs
_REDOS_DANGEROUS_PATTERNS = [
    re.compile(r"\(\.\*\)\+"),  # (.*)+
    re.compile(r"\(\.\+\)\+"),  # (.+)+
    re.compile(r"\([^)]*\+[^)]*\)\+"),  # (...+...)+
    re.compile(r"\([^)]*\*[^)]*\)\+"),  # (...*...)+
    re.compile(r"\([^)]*\+[^)]*\)\*"),  # (...+...)*
    re.compile(r"\([^)]*\*[^)]*\)\*"),  # (...*...)*
    re.compile(r"\(\?:.*\)\{.*,\}"),  # Non-capturing with repetition
]

# Maximum time allowed for a single regex.search() call in seconds
REGEX_SEARCH_TIMEOUT_SECONDS = 0.1  # 100ms


def _safe_regex_search(
    pattern: Pattern[str], text: str, timeout: float = REGEX_SEARCH_TIMEOUT_SECONDS
) -> bool:
    """Execute regex.search() with a timeout to prevent ReDoS attacks.

    Args:
        pattern: Compiled regex pattern
        text: Text to search
        timeout: Maximum time in seconds (default 100ms)

    Returns:
        True if pattern matches, False if no match or timeout
    """

    def _search():
        return pattern.search(text) is not None

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_search)
            return future.result(timeout=timeout)
    except FuturesTimeoutError:
        logger.warning(
            "Regex search timed out after %sms for pattern: %s",
            int(timeout * 1000),
            pattern.pattern[:50],
        )
        return False
    except Exception as e:
        logger.warning("Regex search failed: %s", e)
        return False


def _is_safe_regex_pattern(pattern: str) -> tuple[bool, str]:
    """Validate regex pattern for safety against ReDoS attacks.

    Returns:
        Tuple of (is_safe, error_message). If safe, error_message is empty.
    """
    if len(pattern) > MAX_REGEX_PATTERN_LENGTH:
        return (
            False,
            f"Pattern too long ({len(pattern)} chars, max {MAX_REGEX_PATTERN_LENGTH})",
        )

    for dangerous in _REDOS_DANGEROUS_PATTERNS:
        if dangerous.search(pattern):
            return (
                False,
                "Pattern contains constructs that could cause catastrophic backtracking",
            )

    return True, ""


async def get_events(
    services: dict, session_id: str, event_types: Optional[list] = None, limit: int = 50
) -> dict:
    """Retrieve event log for a session.

    Returns chronological log of all tool calls, searches, and operations
    performed during the session. Useful for debugging and understanding
    agent decision-making.

    Args:
        services: Service dependency dict
        session_id: Session identifier
        event_types: Optional filter by event types
        limit: Maximum number of events to return

    Returns:
        List of events with timestamps and details

    Example:
        >>> result = await get_events(
        ...     services, "sess_123",
        ...     event_types=["mcp.tool.started", "mcp.tool.completed"],
        ...     limit=20
        ... )
        >>> for event in result["events"]:
        ...     print(f"{event['timestamp']}: {event['event_type']}")
    """
    session_manager = services["session_manager"]

    # Validate session
    if not await session_manager.validate_session(session_id):
        return {
            "error": f"Session '{session_id}' not found or expired",
            "suggestion": "Use a valid session_id or create a new session",
        }

    try:
        # Get session which includes events and history
        session = await session_manager.get_session(session_id, include_history=True)

        # Extract events from history and session events
        events = []

        # Add history items (tool calls)
        for item in session.history or []:
            if event_types is None or item.get("event_type") in event_types:
                events.append(
                    {
                        "timestamp": item.get("timestamp"),
                        "event_type": item.get("event_type", "tool_call"),
                        "tool_name": item.get("tool"),
                        "details": item.get("params", {}),
                    }
                )

        # Add session lifecycle/async events
        for item in session.events or []:
            if event_types is None or item.get("event_type") in event_types:
                events.append(
                    {
                        "timestamp": item.get("timestamp"),
                        "event_type": item.get("event_type"),
                        "details": item.get("data", {}),
                    }
                )

        # Sort by timestamp
        events.sort(key=lambda x: x.get("timestamp", ""), reverse=False)

        # Limit results
        if limit > 0:
            events = events[-limit:]

        return {"events": events, "total": len(events), "session_id": session_id}

    except Exception as e:
        logger.error("Failed to get events: %s", e, exc_info=True)
        return {"error": str(e), "suggestion": "Ensure session_id is valid"}


async def get_project_info(services: dict, session_id: str) -> dict:
    """Get comprehensive project information and statistics.

    Returns project metadata, indexing statistics, file counts, entity counts,
    memory statistics, storage metrics, and top keywords from indexed content.
    Provides overview of what's been indexed and available for search.

    **IMPORTANT:** This tool returns `recent_indexing_events` - the most recent
    indexing events for this project. If the last event is `indexing_started`
    without a corresponding `indexing_completed`, indexing is still in progress
    and relationship counts may be incomplete (relationships are batched and
    flushed at the END of indexing). The `indexing_completed` event contains
    the final `relationships_created` count in its data.

    Args:
        services: Service dependency dict
        session_id: Session identifier

    Returns:
        Project statistics, metadata, and top keywords including:
        - project_id: Project identifier
        - statistics: Counts for chunks, entities, relationships, memories
        - status: Boolean flags for indexed content
        - recent_indexing_events: Last 5 indexing events (started/completed/failed)
            with event_type, timestamp, and data (including relationships_created)
        - top_keywords: Most common keywords in indexed content
        - guidance: Suggested next steps
        - storage_metrics: (optional) Storage statistics

    Example:
        >>> result = await get_project_info(services, "sess_123")
        >>> print(f"Chunks indexed: {result['statistics']['chunks_indexed']}")
        >>> # Check recent events to see if indexing completed
        >>> for event in result['recent_indexing_events']:
        ...     if event['event_type'] == 'indexing_completed':
        ...         print(f"Final relationships: {event['data'].get('relationships_created')}")
    """
    from agentic_inquiry.mcp.utils.project_state import check_project_state

    session_manager = services["session_manager"]
    db_manager = services["storage"]
    memory_system = services["memory_system"]
    event_system = services.get("event_system")

    # Validate session
    if not await session_manager.validate_session(session_id):
        return {
            "error": f"Session '{session_id}' not found or expired",
            "suggestion": "Use a valid session_id or create a new session",
        }

    try:
        # Get session to extract project_id
        session = await session_manager.get_session(session_id, include_history=False)
        project_id = session.project_id

        # Check project state (includes chunk and entity counts)
        project_state = await check_project_state(db_manager, project_id)
        chunks_count = project_state["chunk_count"]
        entities_count = project_state["entity_count"]

        # Get recent indexing events (let caller interpret state)
        recent_indexing_events = []
        if event_system and hasattr(event_system, "store"):
            try:
                events = await event_system.store.query_events(
                    project_id=project_id,
                    event_types=[
                        "indexing_started",
                        "indexing_completed",
                        "indexing_failed",
                    ],
                    limit=5,
                )
                for evt in events:
                    recent_indexing_events.append(
                        {
                            "event_type": evt.event_type,
                            "timestamp": evt.timestamp.isoformat()
                            if hasattr(evt.timestamp, "isoformat")
                            else str(evt.timestamp),
                            "data": evt.metadata or {},
                        }
                    )
            except Exception as e:
                logger.debug("Could not fetch indexing events: %s", e)

        # Get memory statistics
        memory_stats = await memory_system.get_stats()

        # Get storage metrics (with caching to avoid performance impact)
        storage_metrics = None
        cache_manager = services.get("cache_manager")
        cache_key = f"storage_metrics:{project_id}"

        if cache_manager:
            storage_metrics = cache_manager.get(cache_key)

        if not storage_metrics:
            try:
                # Get DB manager for direct access to table statistics
                # Note: db_manager is StorageFacade, need to get underlying LanceDB manager
                if hasattr(db_manager, "get_db_manager"):
                    lance_manager = db_manager.get_db_manager()
                    if hasattr(lance_manager, "get_table_statistics"):
                        table_stats = await lance_manager.get_table_statistics()

                        # Calculate total size from tables that have size info
                        total_size = sum(
                            stats.get("size_bytes", 0)
                            for stats in table_stats.values()
                            if stats.get("status") == "success"
                            and stats.get("size_bytes")
                        )

                        # Build storage metrics response
                        storage_metrics = {
                            "tables": table_stats,
                            "total_size_bytes": total_size if total_size > 0 else None,
                        }

                        # Cache the results (60 second TTL as per spec)
                        if cache_manager:
                            cache_manager.set(cache_key, storage_metrics, ttl=60)

                        logger.debug(
                            "Collected storage metrics for project %s: %d tables, total_size=%s",
                            project_id,
                            len(table_stats),
                            total_size if total_size > 0 else "unknown",
                        )
            except Exception as e:
                logger.warning(
                    "Failed to collect storage metrics for project %s: %s",
                    project_id,
                    e,
                )
                storage_metrics = None

        # Count relationships for this project (with breakdown by type)
        relationships_by_type: Dict[str, int] = {}
        relationships_count = 0
        try:
            # Get relationship counts grouped by type
            if hasattr(db_manager, "count_relationships_by_type"):
                relationships_by_type = await db_manager.count_relationships_by_type(
                    project_id=project_id
                )
                relationships_count = sum(relationships_by_type.values())
            else:
                # Fallback: Use count_records for total count only
                relationships_count = await db_manager.count_records(
                    table_name="graph_relationships", project_id=project_id
                )

            logger.debug(
                "Project statistics for %s: chunks=%d, entities=%d, relationships=%d, by_type=%s",
                project_id,
                chunks_count,
                entities_count,
                relationships_count,
                relationships_by_type,
            )
        except Exception as e:
            logger.error(
                "Failed to get relationship count for project %s: %s",
                project_id,
                e,
                exc_info=True,
            )
            relationships_count = 0

        # Extract top keywords from indexed content (with caching)
        top_keywords = []
        if chunks_count > 0:
            try:
                # Check cache first
                cache_manager = services.get("cache_manager")
                cache_key = f"keywords:{project_id}"

                if cache_manager:
                    top_keywords = cache_manager.get(cache_key)

                if not top_keywords:
                    # Extract keywords if not cached
                    from agentic_inquiry.mcp.utils.keyword_extractor import (
                        KeywordExtractor,
                    )

                    keyword_extractor = KeywordExtractor()
                    top_keywords = await keyword_extractor.extract_top_keywords(
                        db_manager=db_manager, project_id=project_id, limit=50
                    )

                    # Cache the results (5 minute TTL)
                    if cache_manager:
                        cache_manager.set(cache_key, top_keywords)

                    logger.debug(
                        "Extracted %d keywords for project %s",
                        len(top_keywords),
                        project_id,
                    )
            except Exception as e:
                logger.error(
                    "Failed to extract keywords for project %s: %s",
                    project_id,
                    e,
                    exc_info=True,
                )
                top_keywords = []

        response = {
            "project_id": project_id,
            "statistics": {
                "total_chunks": chunks_count,
                "chunks_indexed": chunks_count,  # backward compat alias
                "entities_created": entities_count,
                "relationships_created": relationships_count,
                "relationships_by_type": relationships_by_type,
                "memories_stored": (
                    memory_stats.get("working_memory", {}).get("size", 0)
                    + memory_stats.get("episodic_memory", {}).get("size", 0)
                    + memory_stats.get("semantic_memory", {}).get("size", 0)
                ),
                "working_memories": memory_stats.get("working_memory", {}).get(
                    "size", 0
                ),
                "episodic_memories": memory_stats.get("episodic_memory", {}).get(
                    "size", 0
                ),
                "semantic_memories": memory_stats.get("semantic_memory", {}).get(
                    "size", 0
                ),
            },
            "status": {
                "indexed": chunks_count > 0,
                "has_entities": entities_count > 0,
                "has_relationships": relationships_count > 0,
                "has_memories": (
                    memory_stats.get("working_memory", {}).get("size", 0)
                    + memory_stats.get("episodic_memory", {}).get("size", 0)
                    + memory_stats.get("semantic_memory", {}).get("size", 0)
                )
                > 0,
            },
            "recent_indexing_events": recent_indexing_events,
            "top_keywords": top_keywords,
            "guidance": {
                "next_steps": _generate_guidance(
                    chunks_count, entities_count, memory_stats
                )
            },
        }

        # Add storage metrics if available
        if storage_metrics:
            response["storage_metrics"] = storage_metrics

        # Add warnings if project is empty or incomplete
        if project_state["warnings"]:
            response["warnings"] = project_state["warnings"]

        return response

    except Exception as e:
        logger.error("Failed to get project info: %s", e, exc_info=True)
        return {"error": str(e), "suggestion": "Ensure project is initialized"}


async def get_server_info(
    services: dict, limit: int = 50, sort_by: str = "last_indexed"
) -> dict:
    """Get comprehensive server configuration and available projects.

    This tool provides discovery information about the MCP server including:
    - Server metadata (name, version, description)
    - Default project_id configured at startup
    - List of available projects with statistics (limited and sorted)
    - Project_id format requirements and normalization rules
    - Enabled tool categories
    - Usage guidelines

    No session_id required - this is server-level information accessible
    immediately for discovery purposes.

    Args:
        services: Service dependency dict
        limit: Maximum number of projects to return (default: 50)
        sort_by: Sort order for projects - "last_indexed" (default) or "name"

    Returns:
        Server information dictionary with:
        - server: Server metadata
        - default_project: Default project configuration
        - available_projects: List of projects with stats (limited and sorted)
        - project_id_rules: Format requirements
        - tools: Enabled tool categories
        - usage_guidelines: Getting started tips

    Example:
        >>> info = await get_server_info(services, limit=10)
        >>> print(info["default_project"]["project_id"])
        'agentic-inquiry'
        >>> print(info["available_projects"])
        [{'project_id': 'agentic-inquiry', 'chunks': 1234, ...}, ...]

    Performance:
        - Results are cached for 60 seconds
        - Cache key: "server_info:v1:{limit}:{sort_by}"
        - Projects sorted by last_indexed (most recent first) by default
        - Limit prevents performance issues with large deployments
    """
    from time import time

    # Simple time-based cache
    cache_key = f"server_info:v1:{limit}:{sort_by}"
    now = time()

    # Check cache
    if hasattr(get_server_info, "_cache"):
        if cache_key in get_server_info._cache:
            cached_data, cached_time = get_server_info._cache[cache_key]
            if now - cached_time < 60:  # 60 second TTL
                logger.debug(
                    "Returning cached server info (age: %.1fs)", now - cached_time
                )
                return cached_data
    else:
        get_server_info._cache = {}  # type: ignore[attr-defined]

    try:
        # Get server configuration
        server_config = services.get("server_config", {})
        db_manager = services["storage"]
        session_manager = services["session_manager"]

        # Build server metadata
        server_metadata = {
            "name": server_config.get("server_name", "Agentic Inquiry MCP Server"),
            "version": server_config.get("server_version", "1.0.0"),
            "description": server_config.get(
                "server_description", "Intelligent search and knowledge management"
            ),
        }

        # Get default project
        default_project_id = server_config.get("default_project_id", "agentic-inquiry")
        default_project = {
            "project_id": default_project_id,
            "description": "Default project configured at server startup",
        }

        # Discover available projects from database
        available_projects = []
        try:
            # Query for unique project_ids from document_chunks table
            # Get all chunks to extract unique project_ids
            # Note: LanceDB doesn't have a native DISTINCT, so we need to fetch and deduplicate
            all_chunks = await db_manager.advanced_filter(
                table_name="document_chunks",
                filters={},
                limit=None,  # Get all to find unique projects
            )

            # Extract unique project_ids with their last indexed timestamp
            project_data = {}
            for chunk in all_chunks:
                project_id = chunk.get("project_id")
                if project_id:
                    created_at = chunk.get("created_at")
                    if project_id not in project_data:
                        project_data[project_id] = created_at
                    elif created_at and (
                        not project_data[project_id]
                        or created_at > project_data[project_id]
                    ):
                        project_data[project_id] = created_at

            # Convert to list of tuples for sorting
            project_list = [
                (pid, last_indexed) for pid, last_indexed in project_data.items()
            ]

            # Sort projects
            if sort_by == "name":
                project_list.sort(
                    key=lambda x: x[0]
                )  # Sort by project_id alphabetically
            else:  # "last_indexed" (default)
                project_list.sort(
                    key=lambda x: x[1] or "", reverse=True
                )  # Most recent first

            # Limit results
            project_list = project_list[:limit]

            # Gather statistics for each project
            for project_id, last_indexed in project_list:
                try:
                    stats = await session_manager.get_project_statistics(project_id)

                    project_info = {
                        "project_id": project_id,
                        "total_chunks": stats.total_chunks,
                        "total_files": stats.total_files,
                        "total_entities": sum(stats.entity_counts.values())
                        if stats.entity_counts
                        else 0,
                        "last_indexed": last_indexed.isoformat()
                        if last_indexed
                        else None,
                        "index_health": stats.index_health,
                        "languages": stats.languages if stats.languages else {},
                    }
                    available_projects.append(project_info)

                except Exception as e:
                    logger.warning(
                        "Failed to get statistics for project %s: %s", project_id, e
                    )
                    # Add basic info even if stats fail
                    available_projects.append(
                        {
                            "project_id": project_id,
                            "total_chunks": 0,
                            "total_files": 0,
                            "total_entities": 0,
                            "last_indexed": last_indexed.isoformat()
                            if last_indexed
                            else None,
                            "index_health": "unknown",
                            "languages": {},
                        }
                    )

        except Exception as e:
            logger.warning("Failed to discover projects: %s", e)
            # Return empty list if discovery fails
            available_projects = []

        # Project ID format rules
        project_id_rules = {
            "format": "alphanumeric with hyphens and underscores",
            "pattern": "^[a-zA-Z0-9_-]+$",
            "length": "1-64 characters",
            "normalization": "converted to lowercase",
            "examples": ["my-project", "project_123", "my_project"],
        }

        # Enabled tool categories
        tools = {
            "cognitive_tools": [
                "session",
                "memory",
                "search",
                "analysis",
                "context",
                "knowledge",
                "info",
            ],
            "direct_access_tools": [],  # Empty if disabled
        }

        # Usage guidelines
        usage_guidelines = {
            "getting_started": [
                "1. Create a session with create_session(project_id='...')",
                "2. Index content with add_knowledge(...)",
                "3. Search with search_knowledge(...)",
            ],
            "project_discovery": "Use available_projects to see what's indexed",
            "project_mismatch": "If using different project_id than default, ensure it exists",
        }

        # Build response
        result = {
            "server": server_metadata,
            "default_project": default_project,
            "available_projects": available_projects,
            "project_id_rules": project_id_rules,
            "tools": tools,
            "usage_guidelines": usage_guidelines,
        }

        # Cache result
        get_server_info._cache[cache_key] = (result, now)  # type: ignore[attr-defined]

        logger.info(
            "Generated server info with %d projects (limit=%d, sort_by=%s)",
            len(available_projects),
            limit,
            sort_by,
        )

        return result

    except Exception as e:
        logger.error("Failed to get server info: %s", e, exc_info=True)
        return {
            "error": str(e),
            "suggestion": "Check server configuration and database connectivity",
        }


def _generate_guidance(
    chunks_count: int, entities_count: int, memory_stats: dict
) -> list:
    """Generate guidance based on project state."""
    guidance = []

    if chunks_count == 0:
        guidance.append("Project not yet indexed. Use add_knowledge to index files.")
    elif chunks_count < 100:
        guidance.append(
            "Small project indexed. Consider indexing more files for better search results."
        )
    else:
        guidance.append("Project indexed and ready for semantic search.")

    if entities_count == 0:
        guidance.append(
            "No code entities found. Index code files to enable entity analysis."
        )
    else:
        guidance.append(f"{entities_count} code entities available for analysis.")

    total_memories = (
        memory_stats.get("working_memory", {}).get("size", 0)
        + memory_stats.get("episodic_memory", {}).get("size", 0)
        + memory_stats.get("semantic_memory", {}).get("size", 0)
    )
    if total_memories == 0:
        guidance.append("No memories saved yet. Use save_memory to capture insights.")
    else:
        guidance.append(f"{total_memories} memories stored and available for recall.")

    return guidance


def _path_matches(entity_path: str, filter_path: str, normalized_filter: str) -> bool:
    """Check if entity path matches the filter path using flexible matching.

    Tries multiple strategies in order:
    1. Exact match
    2. Endswith (for relative paths like "search/service.py")
    3. Contains (for partial path segments)
    4. Normalized path comparison (handles ./ and ../)

    Args:
        entity_path: The file path from the entity
        filter_path: The original filter path provided by user
        normalized_filter: The normalized version of filter_path

    Returns:
        True if the entity path matches the filter
    """
    import os

    if not entity_path:
        return False

    # Exact match
    if entity_path == filter_path:
        return True

    # Endswith match (for relative paths)
    if entity_path.endswith(filter_path):
        return True

    # Contains match (for partial paths)
    if filter_path in entity_path:
        return True

    # Normalized path comparison
    normalized_entity = os.path.normpath(entity_path)
    if normalized_entity == normalized_filter:
        return True

    if normalized_entity.endswith(normalized_filter):
        return True

    return False


async def list_entities(
    services: dict,
    session_id: str,
    entity_type: Optional[str] = None,
    file_path: Optional[str] = None,
    pattern: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """List indexed entities with optional filtering.

    Browse the knowledge graph entities by type, file, or name pattern.
    Useful for exploring what's been indexed and finding specific code elements.

    Args:
        services: Service dependency dict
        session_id: Session identifier
        entity_type: Filter by entity type: "class", "function", "method",
                    "module", "variable", "heading", "section", etc.
        file_path: Filter by file path (exact match or glob pattern like "*.py")
        pattern: Filter by entity name. Supports three modes (all case-insensitive):
                 - Substring match: "Graph" finds "GraphSearchService" (default)
                 - Glob pattern: "*Service" finds names ending with "Service"
                 - Regex pattern: "^Graph" or "Service$" for start/end anchors
        limit: Maximum number of entities to return (default: 50, max: 200)
        offset: Pagination offset (default: 0)

    Returns:
        Dictionary with:
        - entities: List of entity dictionaries
        - total_count: Total entities matching filters
        - returned_count: Number of entities returned
        - has_more: Whether more entities are available
        - filters_applied: Summary of filters used

    Example:
        >>> # List all classes
        >>> result = await list_entities(
        ...     services, "sess_123",
        ...     entity_type="class"
        ... )
        >>> for entity in result["entities"]:
        ...     print(f"{entity['name']} ({entity['file_path']})")

        >>> # Find all entities containing "Service" (substring match)
        >>> result = await list_entities(
        ...     services, "sess_123",
        ...     pattern="Service"
        ... )

        >>> # Find entities ending with "Service" (explicit glob)
        >>> result = await list_entities(
        ...     services, "sess_123",
        ...     pattern="*Service"
        ... )

        >>> # List entities in a specific file
        >>> result = await list_entities(
        ...     services, "sess_123",
        ...     file_path="agentic_inquiry/search/service.py"
        ... )
    """
    session_manager = services["session_manager"]
    db_manager = services["storage"]

    # Validate session
    if not await session_manager.validate_session(session_id):
        return {
            "error": f"Session '{session_id}' not found or expired",
            "suggestion": "Use a valid session_id or create a new session",
        }

    # Validate limit
    limit = min(limit, 200)  # Cap at 200

    try:
        # Get session to extract project_id
        session = await session_manager.get_session(session_id, include_history=False)
        project_id = session.project_id

        # Build Filter AST for optional type filter
        # Schema uses "type" field, not "entity_type"
        from agentic_inquiry.models.graph_entity import EntityType

        normalized_type = EntityType.normalize(entity_type) if entity_type else None
        type_filter = by_type(normalized_type) if normalized_type else None

        # Query entities from database
        # Use a large limit to ensure pattern filtering works across the full entity set.
        # With 12K+ entities, the default limit=100 silently truncates before pattern
        # filtering, causing entities like SearchService to be missed.
        all_entities = await db_manager.advanced_filter(
            table_name="graph_entities",
            filters=type_filter,
            limit=10000,  # Large enough for full-codebase entity sets
            project_id=project_id,
        )

        # Apply additional filters that database doesn't support natively
        filtered_entities = all_entities

        # Filter by file_path with flexible matching
        if file_path:
            import os

            if "*" in file_path or "?" in file_path:
                # Glob pattern
                filtered_entities = [
                    e
                    for e in filtered_entities
                    if fnmatch.fnmatch(_get_attr(e, "file_path", ""), file_path)
                ]
            else:
                # Flexible path matching: try multiple strategies
                # 1. Exact match
                # 2. Endswith (for relative paths like "search/service.py")
                # 3. Contains (for partial paths)
                # 4. Normalized path comparison (handle ./ and ../)
                normalized_filter = os.path.normpath(file_path)
                filtered_entities = [
                    e
                    for e in filtered_entities
                    if _path_matches(
                        _get_attr(e, "file_path", ""), file_path, normalized_filter
                    )
                ]

        # Filter by name pattern
        if pattern:
            if pattern.startswith("^") or pattern.endswith("$"):
                # Regex pattern - validate for safety first
                is_safe, error_msg = _is_safe_regex_pattern(pattern)
                if not is_safe:
                    return {
                        "error": f"Unsafe regex pattern: {error_msg}",
                        "suggestion": "Use a simpler pattern or glob syntax like '*Service*'",
                    }
                try:
                    regex = re.compile(pattern, re.IGNORECASE)
                    # Use safe regex search with timeout to prevent ReDoS
                    filtered_entities = [
                        e
                        for e in filtered_entities
                        if _safe_regex_search(regex, _get_attr(e, "name", ""))
                    ]
                except re.error:
                    return {
                        "error": f"Invalid regex pattern: {pattern}",
                        "suggestion": "Use a valid regex or glob pattern like '*Service*'",
                    }
            elif any(c in pattern for c in "*?[]"):
                # Explicit glob pattern - respect as-is, but make case-insensitive
                filtered_entities = [
                    e
                    for e in filtered_entities
                    if fnmatch.fnmatch(
                        _get_attr(e, "name", "").lower(), pattern.lower()
                    )
                ]
            else:
                # No glob chars - treat as substring match (auto-wrap)
                pattern_glob = f"*{pattern}*"
                filtered_entities = [
                    e
                    for e in filtered_entities
                    if fnmatch.fnmatch(
                        _get_attr(e, "name", "").lower(), pattern_glob.lower()
                    )
                ]

        # Deduplicate by id to prevent duplicate results
        seen_ids: set = set()
        unique_results: List[Dict[str, Any]] = []
        for entity in filtered_entities:
            entity_id = _get_attr(entity, "id")  # Use canonical 'id' field only
            if entity_id and entity_id not in seen_ids:
                seen_ids.add(entity_id)
                unique_results.append(entity)
        filtered_entities = unique_results

        # Get total count before pagination
        total_count = len(filtered_entities)

        # Apply pagination
        paginated_entities = filtered_entities[offset : offset + limit]

        # Format entities for response
        formatted_entities: List[Dict[str, Any]] = []
        for entity in paginated_entities:
            formatted_entities.append(
                {
                    "name": _get_attr(entity, "name", ""),
                    "type": _get_attr(entity, "type", ""),  # Schema uses "type" field
                    "file_path": _get_attr(entity, "file_path", ""),
                    "line_start": _get_attr(entity, "line_start"),
                    "line_end": _get_attr(entity, "line_end"),
                    "id": _get_attr(entity, "id", ""),  # Use canonical 'id' field
                    "metadata": _get_attr(entity, "metadata", {}),
                }
            )

        # Build filters summary
        filters_applied = {}
        if entity_type:
            filters_applied["entity_type"] = entity_type
        if file_path:
            filters_applied["file_path"] = file_path
        if pattern:
            filters_applied["pattern"] = pattern

        return {
            "entities": formatted_entities,
            "total_count": total_count,
            "returned_count": len(formatted_entities),
            "has_more": (offset + limit) < total_count,
            "offset": offset,
            "limit": limit,
            "filters_applied": filters_applied,
            "project_id": project_id,
        }

    except Exception as e:
        logger.error("Failed to list entities: %s", e, exc_info=True)
        return {
            "error": str(e),
            "suggestion": "Ensure project is indexed with add_knowledge",
        }


async def run_maintenance(
    services: dict, session_id: str, cleanup_hours: float = 1.0
) -> dict:
    """Run database maintenance to compact files and reclaim disk space.

    LanceDB uses MVCC (Multi-Version Concurrency Control), which creates new
    data files on every write operation. Without maintenance, storage grows
    unboundedly. This tool:

    1. Compacts files - merges small fragments into larger ones (improves query performance)
    2. Cleans up old versions - removes old data versions (reclaims disk space)

    Should be run:
    - After large indexing operations (runs automatically)
    - Periodically for heavily-used databases
    - When disk space needs to be reclaimed

    Args:
        services: Service dependency dict
        session_id: Session identifier
        cleanup_hours: Only remove versions older than this many hours (default: 1.0).
                      Higher values preserve more history for rollback.

    Returns:
        Maintenance results including:
        - compaction: Fragment reduction per table
        - cleanup: Version cleanup per table
        - summary: Total fragments reduced and versions removed

    Example:
        >>> result = await run_maintenance(services, "sess_123")
        >>> print(f"Fragments reduced: {result['summary']['fragments_reduced']}")
        >>> print(f"Versions removed: {result['summary']['versions_removed']}")
    """
    from datetime import timedelta

    session_manager = services["session_manager"]
    db_manager = services["storage"]

    # Validate session
    if not await session_manager.validate_session(session_id):
        return {
            "error": f"Session '{session_id}' not found or expired",
            "suggestion": "Use a valid session_id or create a new session",
        }

    try:
        # Run maintenance
        cleanup_older_than = timedelta(hours=cleanup_hours)
        result = await db_manager.run_maintenance(cleanup_older_than=cleanup_older_than)

        return {
            "status": "success",
            "compaction": result["compaction"],
            "cleanup": result["cleanup"],
            "summary": result["summary"],
            "cleanup_hours": cleanup_hours,
            "message": (
                f"Maintenance complete: reduced {result['summary']['fragments_reduced']} fragments, "
                f"removed {result['summary']['versions_removed']} old versions"
            ),
        }

    except Exception as e:
        logger.error("Database maintenance failed: %s", e, exc_info=True)
        return {
            "error": str(e),
            "suggestion": "Check database connection and permissions",
        }


__all__ = [
    "get_events",
    "get_project_info",
    "get_server_info",
    "list_entities",
    "run_maintenance",
]
