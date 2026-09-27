"""Direct access tools for MCP server.

These tools provide low-level control over indexing, search, and graph operations.
They are intended for advanced use cases requiring granular control.
"""

import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from agentic_inquiry.database.filters import eq
from agentic_inquiry.database.filter_helpers import (
    file_path as file_path_filter,
    by_id,
    source_id as source_id_filter,
    target_id as target_id_filter,
)
from agentic_inquiry.mcp.utils.errors import MCPErrorHandler
from agentic_inquiry.mcp.utils.validation import validate_file_path, PathValidationError
from agentic_inquiry.onboard.gate import OnboardGateError, check_onboard_gate
from agentic_inquiry.onboard.metadata_service import OnboardMetadataService
from agentic_inquiry.utils import get_attr as _get_attr

logger = logging.getLogger(__name__)


async def index_files(
    services: dict,
    session_id: str,
    file_paths: List[str],
    force_reindex: bool = False,
    parser_options: Optional[Dict[str, Any]] = None,
) -> dict:
    """Index specific files with granular control.

    Provides fine-grained control over file indexing, allowing you to:
    - Index specific files rather than entire directories
    - Force reindexing of already-indexed files
    - Pass parser-specific options

    Args:
        services: Service dependency dict
        session_id: Session identifier
        file_paths: List of file paths to index
        force_reindex: Force reindexing even if file is already indexed
        parser_options: Optional parser-specific options

    Returns:
        Indexing results with per-file status

    Example:
        >>> result = await index_files(
        ...     services, "sess_123",
        ...     file_paths=["src/auth.py", "src/utils.py"],
        ...     force_reindex=True
        ... )
        >>> print(f"Indexed: {result['indexed']}, Failed: {result['failed']}")
    """
    import os
    from agentic_inquiry.parsers import create_parser_chain
    from agentic_inquiry.indexing.pipeline import IndexingPipeline

    session_manager = services["session_manager"]
    event_system = services["event_system"]
    config = services["config"]
    db_manager = services["storage"]

    # Validate session
    if not await session_manager.validate_session(session_id):
        return await MCPErrorHandler.handle(
            error=Exception(f"Session '{session_id}' not found or expired"),
            context={"session_id": session_id},
            services=services,
        )

    # Get session to extract project_id
    session = await session_manager.get_session(session_id, include_history=False)
    project_id = session.project_id

    # Get project root
    project_root = Path(os.getcwd())

    # Onboard gate check (missing onboard is a warning, not a block)
    try:
        metadata_svc = await OnboardMetadataService.from_config(
            config,
            workspace=str(project_root),
            project_id=project_id,
        )
        staleness = await check_onboard_gate(
            metadata_svc,
            project_root,
            config,
            skip_gate=force_reindex,
        )
        if staleness and staleness.is_stale:
            logger.warning("Onboard stale during index_files: %s", staleness.message)
        await metadata_svc.close()
    except OnboardGateError as e:
        return {
            "status": "blocked",
            "error": str(e),
            "error_type": "onboard_gate",
            "suggestion": "Run /ai:onboard first to create baseline documentation.",
        }
    except Exception as e:
        # Don't block indexing if metadata service fails to initialize
        logger.warning("Onboard gate check failed (non-blocking): %s", e)

    # Validate file_paths parameter
    if not file_paths or not isinstance(file_paths, list):
        return {
            "status": "failed",
            "error": "file_paths must be a non-empty list of file paths",
            "error_type": "validation_error",
        }

    # Create indexing pipeline
    pipeline_kwargs = {
        "db_manager": db_manager,
        "config": config,
        "project_id": project_id,
        "event_system": event_system,
    }
    if hasattr(db_manager, "embedding_registry"):
        pipeline_kwargs["registry"] = db_manager.embedding_registry

    indexing_pipeline = IndexingPipeline(**pipeline_kwargs)

    # Track start
    await event_system.emit(
        "mcp.tool.started",
        source="mcp_tool",
        tool_name="index_files",
        session_id=session_id,
        file_count=len(file_paths),
    )

    # Process each file
    indexed_count = 0
    failed_count = 0
    skipped_count = 0
    file_results: List[dict] = []
    error_results: List[dict] = []

    chain = create_parser_chain()

    for file_path_str in file_paths:
        try:
            # Validate path for security
            try:
                file_path = validate_file_path(
                    file_path_str, project_root, must_exist=False
                )
            except PathValidationError as e:
                failed_count += 1
                error_results.append(
                    {
                        "file": file_path_str,
                        "error": "path_validation",
                        "message": str(e),
                    }
                )
                continue

            if not file_path.exists():
                failed_count += 1
                error_results.append(
                    {
                        "file": file_path_str,
                        "error": "file_not_found",
                        "message": f"File not found: {file_path}",
                    }
                )
                continue

            if not file_path.is_file():
                failed_count += 1
                error_results.append(
                    {
                        "file": file_path_str,
                        "error": "not_a_file",
                        "message": f"Path is not a file: {file_path}",
                    }
                )
                continue

            # Check if already indexed (unless force_reindex)
            if not force_reindex:
                try:
                    existing = await db_manager.advanced_filter(
                        table_name="document_chunks",
                        filters=file_path_filter(str(file_path)),
                        limit=1,
                        project_id=project_id,
                    )
                    if existing:
                        skipped_count += 1
                        file_results.append(
                            {
                                "file": file_path_str,
                                "status": "skipped",
                                "reason": "already_indexed",
                            }
                        )
                        continue
                except Exception as e:
                    # S5-002: Log table access failure (likely table doesn't exist yet)
                    logger.debug(
                        "Could not check existing index for '%s': %s", file_path_str, e
                    )

            # Parse and index
            parse_kwargs = parser_options or {}
            parse_kwargs["db_manager"] = db_manager
            parse_kwargs["embedding_service"] = indexing_pipeline.embedding_service
            parse_kwargs["project_id"] = project_id

            parsed_doc = await chain.parse(str(file_path), **parse_kwargs)
            await indexing_pipeline.process_document(parsed_doc)

            indexed_count += 1
            file_results.append(
                {
                    "file": file_path_str,
                    "status": "indexed",
                    "chunks": len(parsed_doc.chunks),
                }
            )

        except Exception as e:
            logger.error("Failed to index file %s: %s", file_path_str, e)
            failed_count += 1
            error_results.append(
                {"file": file_path_str, "error": type(e).__name__, "message": str(e)}
            )

    # Flush pending relationships
    relationships_created = await indexing_pipeline.flush_pending_relationships()

    # Determine overall status
    if indexed_count > 0 and failed_count == 0:
        status = "completed"
    elif indexed_count > 0 and failed_count > 0:
        status = "partial"
    elif indexed_count == 0 and skipped_count > 0:
        status = "skipped"
    else:
        status = "failed"

    # Track completion
    await event_system.emit(
        "mcp.tool.completed",
        source="mcp_tool",
        tool_name="index_files",
        session_id=session_id,
        indexed=indexed_count,
        failed=failed_count,
    )

    return {
        "status": status,
        "indexed": indexed_count,
        "failed": failed_count,
        "skipped": skipped_count,
        "files": file_results,
        "errors": error_results,
        "relationships_created": relationships_created,
    }


async def search_code(
    services: dict,
    session_id: str,
    query: str,
    language: Optional[str] = None,
    symbol_type: Optional[str] = None,
    limit: int = 20,
) -> dict:
    """Code-only search with syntax awareness.

    Searches only code content (not documentation), with optional filtering
    by programming language and symbol type.

    Args:
        services: Service dependency dict
        session_id: Session identifier
        query: Code search query
        language: Filter by programming language (python, javascript, etc.)
        symbol_type: Filter by symbol type (class, function, method, etc.)
        limit: Maximum results to return

    Returns:
        Code search results with syntax metadata

    Example:
        >>> result = await search_code(
        ...     services, "sess_123",
        ...     query="authentication",
        ...     language="python",
        ...     symbol_type="function"
        ... )
    """
    import time
    from agentic_inquiry.mcp.utils.validation import (
        validate_limit,
        validate_query_length,
        create_validation_error_response,
        QueryValidationError,
    )

    session_manager = services["session_manager"]
    search_service = services["search_service"]
    embedding_service = services["embedding_service"]
    event_system = services["event_system"]

    # Validate query length (DoS protection - S5-001)
    try:
        query = validate_query_length(query, field_name="query")
    except QueryValidationError as e:
        return create_validation_error_response(
            field="query",
            error=e,
            context={"session_id": session_id},
            provided_value=query[:100] if query else None,
            expected_type="non-empty string (max 10,000 chars)",
            example='query="authentication"',
        )

    # Validate parameters
    try:
        limit = validate_limit(limit, min_value=1, max_value=100)
    except ValueError as e:
        return {"status": "failed", "error": str(e), "error_type": "validation_error"}

    # Validate session
    if not await session_manager.validate_session(session_id):
        return await MCPErrorHandler.handle(
            error=Exception(f"Session '{session_id}' not found or expired"),
            context={"session_id": session_id},
            services=services,
        )

    # Get session to extract project_id
    session = await session_manager.get_session(session_id, include_history=False)
    project_id = session.project_id

    # Track start
    start_time = time.time()
    await event_system.emit(
        "mcp.tool.started",
        source="mcp_tool",
        tool_name="search_code",
        session_id=session_id,
        query=query,
    )

    try:
        # Build filters for code-only search
        filters: Dict[str, Any] = {
            "content_type": "CODE"  # Only search code chunks
        }
        if language:
            filters["language"] = language.lower()

        # Generate query embedding
        query_vector = await embedding_service.embed_async(query)

        # Execute hybrid search with code filters
        results = await search_service.hybrid_search(
            query_vector=query_vector.tolist(),
            query_fts=query,
            project_id=project_id,
            limit=limit * 2,  # Get extra to filter by symbol_type
            filters=filters,
        )

        # Filter by symbol_type if specified
        if symbol_type and results:
            symbol_type_lower = symbol_type.lower()
            results = [
                r
                for r in results
                if any(
                    s.lower() == symbol_type_lower or symbol_type_lower in s.lower()
                    for s in (r.data.get("symbols") or [])
                )
                or r.data.get("entity_type", "").lower() == symbol_type_lower
            ]

        # Format results
        formatted_results = []
        for result in results[:limit]:
            formatted_results.append(
                {
                    "file_path": result.data.get("file_path", ""),
                    "content": result.data.get("content", ""),
                    "score": result.score,
                    "line_start": result.data.get("line_start"),
                    "line_end": result.data.get("line_end"),
                    "language": result.data.get("language"),
                    "symbols": result.data.get("symbols", []),
                    "entity_type": result.data.get("entity_type"),
                    "entity_name": result.data.get("entity_name"),
                    "metadata": {
                        k: v
                        for k, v in (result.data.get("metadata") or {}).items()
                        if k in {"complexity", "imports", "decorators"}
                    },
                }
            )

        search_time_ms = int((time.time() - start_time) * 1000)

        # Track success
        await event_system.emit(
            "mcp.tool.completed",
            source="mcp_tool",
            tool_name="search_code",
            session_id=session_id,
            count=len(formatted_results),
        )

        return {
            "results": formatted_results,
            "total": len(formatted_results),
            "query": query,
            "filters": {"language": language, "symbol_type": symbol_type},
            "search_time_ms": search_time_ms,
        }

    except Exception as e:
        await event_system.emit(
            "mcp.tool.failed", source="mcp_tool", tool_name="search_code", error=str(e)
        )
        logger.error("Failed to search code: %s", e, exc_info=True)
        return await MCPErrorHandler.handle(
            error=e,
            context={"session_id": session_id, "query": query},
            services=services,
        )


async def search_docs(
    services: dict,
    session_id: str,
    query: str,
    doc_type: Optional[str] = None,
    limit: int = 20,
) -> dict:
    """Documentation-only search.

    Searches only documentation content (markdown, docstrings, comments),
    excluding code implementations.

    Args:
        services: Service dependency dict
        session_id: Session identifier
        query: Documentation search query
        doc_type: Filter by doc type (markdown, docstring, comment, readme)
        limit: Maximum results to return

    Returns:
        Documentation search results

    Example:
        >>> result = await search_docs(
        ...     services, "sess_123",
        ...     query="authentication setup",
        ...     doc_type="markdown"
        ... )
    """
    import time
    from agentic_inquiry.mcp.utils.validation import (
        validate_limit,
        validate_query_length,
        create_validation_error_response,
        QueryValidationError,
    )

    session_manager = services["session_manager"]
    search_service = services["search_service"]
    embedding_service = services["embedding_service"]
    event_system = services["event_system"]

    # Validate query length (DoS protection - S5-001)
    try:
        query = validate_query_length(query, field_name="query")
    except QueryValidationError as e:
        return create_validation_error_response(
            field="query",
            error=e,
            context={"session_id": session_id},
            provided_value=query[:100] if query else None,
            expected_type="non-empty string (max 10,000 chars)",
            example='query="authentication setup"',
        )

    # Validate parameters
    try:
        limit = validate_limit(limit, min_value=1, max_value=100)
    except ValueError as e:
        return {"status": "failed", "error": str(e), "error_type": "validation_error"}

    # Validate session
    if not await session_manager.validate_session(session_id):
        return await MCPErrorHandler.handle(
            error=Exception(f"Session '{session_id}' not found or expired"),
            context={"session_id": session_id},
            services=services,
        )

    # Get session to extract project_id
    session = await session_manager.get_session(session_id, include_history=False)
    project_id = session.project_id

    # Track start
    start_time = time.time()
    await event_system.emit(
        "mcp.tool.started",
        source="mcp_tool",
        tool_name="search_docs",
        session_id=session_id,
        query=query,
    )

    try:
        # Build filters for documentation search
        # Documentation types: markdown files, docstrings, comments
        doc_extensions = {".md", ".rst", ".txt", ".mdx"}
        doc_content_types = {"DOCUMENTATION", "DOCSTRING", "COMMENT", "OTHER"}

        # Generate query embedding
        query_vector = await embedding_service.embed_async(query)

        # Execute hybrid search
        # We'll filter results post-search since content_type filtering may vary
        results = await search_service.hybrid_search(
            query_vector=query_vector.tolist(),
            query_fts=query,
            project_id=project_id,
            limit=limit * 3,  # Get extra to filter
            boost_overview=True,  # Boost README and docs
        )

        # Filter to documentation only
        doc_results = []
        for result in results:
            file_path = result.data.get("file_path", "")
            content_type = result.data.get("content_type", "").upper()
            language = result.data.get("language", "").lower()

            # Check if it's documentation
            is_doc = False

            # Check file extension
            if any(file_path.lower().endswith(ext) for ext in doc_extensions):
                is_doc = True

            # Check content type
            if content_type in doc_content_types:
                is_doc = True

            # Check language (markdown, rst, etc.)
            if language in {"markdown", "rst", "text", "plaintext"}:
                is_doc = True

            # Check for README files
            if "readme" in file_path.lower():
                is_doc = True

            if not is_doc:
                continue

            # Filter by doc_type if specified
            if doc_type:
                doc_type_lower = doc_type.lower()
                if (
                    doc_type_lower == "markdown"
                    and language != "markdown"
                    and not file_path.endswith(".md")
                ):
                    continue
                if doc_type_lower == "docstring" and content_type != "DOCSTRING":
                    continue
                if doc_type_lower == "comment" and content_type != "COMMENT":
                    continue
                if doc_type_lower == "readme" and "readme" not in file_path.lower():
                    continue

            doc_results.append(result)

            if len(doc_results) >= limit:
                break

        # Format results
        formatted_results = []
        for result in doc_results:
            formatted_results.append(
                {
                    "file_path": result.data.get("file_path", ""),
                    "content": result.data.get("content", ""),
                    "score": result.score,
                    "line_start": result.data.get("line_start"),
                    "line_end": result.data.get("line_end"),
                    "doc_type": result.data.get("content_type", "").lower(),
                    "section_title": result.data.get("metadata", {}).get(
                        "section_title"
                    ),
                    "heading_level": result.data.get("metadata", {}).get(
                        "heading_level"
                    ),
                }
            )

        search_time_ms = int((time.time() - start_time) * 1000)

        # Track success
        await event_system.emit(
            "mcp.tool.completed",
            source="mcp_tool",
            tool_name="search_docs",
            session_id=session_id,
            count=len(formatted_results),
        )

        return {
            "results": formatted_results,
            "total": len(formatted_results),
            "query": query,
            "filters": {"doc_type": doc_type},
            "search_time_ms": search_time_ms,
        }

    except Exception as e:
        await event_system.emit(
            "mcp.tool.failed", source="mcp_tool", tool_name="search_docs", error=str(e)
        )
        logger.error("Failed to search docs: %s", e, exc_info=True)
        return await MCPErrorHandler.handle(
            error=e,
            context={"session_id": session_id, "query": query},
            services=services,
        )


async def graph_traverse(
    services: dict,
    session_id: str,
    start_id: str,
    relationship_types: Optional[List[str]] = None,
    max_depth: int = 2,
    direction: str = "both",
    timeout_ms: Optional[int] = None,
) -> dict:
    """Custom graph navigation and relationship traversal.

    Traverses the knowledge graph starting from an entity, following
    relationships to discover connected entities.

    Args:
        services: Service dependency dict
        session_id: Session identifier
        start_id: Starting entity ID or name
        relationship_types: List of relationship types to follow (None = all)
        max_depth: Maximum traversal depth (1-5)
        direction: Traversal direction: "outbound", "inbound", or "both"
        timeout_ms: Optional timeout in milliseconds. If not provided,
            uses config default (graph_traverse_ms). Set to 0 to disable.

    Returns:
        Graph traversal results with nodes, edges, and paths

    Example:
        >>> result = await graph_traverse(
        ...     services, "sess_123",
        ...     start_id="SearchService",
        ...     relationship_types=["imports", "calls"],
        ...     max_depth=2,
        ...     direction="outbound"
        ... )
    """
    from agentic_inquiry.config import Config

    session_manager = services["session_manager"]
    db_manager = services["storage"]
    event_system = services["event_system"]
    config: Config = services["config"]

    # Get timeout from config or parameter
    graph_timeouts = config.search.graph_search.timeouts
    if timeout_ms is not None:
        effective_timeout_ms = timeout_ms if timeout_ms > 0 else 999999
    else:
        effective_timeout_ms = graph_timeouts.graph_traverse_ms

    # Validate parameters
    if max_depth < 1 or max_depth > 5:
        return {
            "status": "failed",
            "error": "max_depth must be between 1 and 5",
            "error_type": "validation_error",
        }

    valid_directions = {"outbound", "inbound", "both"}
    if direction.lower() not in valid_directions:
        return {
            "status": "failed",
            "error": f"direction must be one of: {', '.join(valid_directions)}",
            "error_type": "validation_error",
        }

    # Validate session
    if not await session_manager.validate_session(session_id):
        return await MCPErrorHandler.handle(
            error=Exception(f"Session '{session_id}' not found or expired"),
            context={"session_id": session_id},
            services=services,
        )

    # Get session to extract project_id
    session = await session_manager.get_session(session_id, include_history=False)
    project_id = session.project_id

    # Track start
    await event_system.emit(
        "mcp.tool.started",
        source="mcp_tool",
        tool_name="graph_traverse",
        session_id=session_id,
        start_id=start_id,
    )

    try:
        # Start timing for performance instrumentation
        start_time = time.perf_counter()

        def check_timeout() -> bool:
            """Return True if timeout exceeded."""
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            return elapsed_ms >= effective_timeout_ms

        # Find the starting entity
        start_entity = None

        # Try by ID first
        try:
            entities = await db_manager.advanced_filter(
                table_name="graph_entities",
                filters=by_id("id", start_id),
                limit=1,
                project_id=project_id,
            )
            if entities:
                start_entity = entities[0]
        except Exception as e:
            # S5-002: Log entity ID lookup failure
            logger.debug("Entity lookup by ID '%s' failed: %s", start_id, e)

        # Try by name if not found by ID
        if not start_entity:
            try:
                entities = await db_manager.advanced_filter(
                    table_name="graph_entities",
                    filters=eq("name", start_id),
                    limit=1,
                    project_id=project_id,
                )
                if entities:
                    start_entity = entities[0]
            except Exception as e:
                # S5-002: Log entity name lookup failure
                logger.debug("Entity lookup by name '%s' failed: %s", start_id, e)

        # Try case-insensitive name match
        if not start_entity:
            try:
                all_entities = await db_manager.advanced_filter(
                    table_name="graph_entities",
                    filters={},
                    limit=1000,
                    project_id=project_id,
                )
                for entity in all_entities:
                    if _get_attr(entity, "name", "").lower() == start_id.lower():
                        start_entity = entity
                        break
            except Exception as e:
                # S5-002: Log case-insensitive entity lookup failure
                logger.debug(
                    "Case-insensitive entity lookup for '%s' failed: %s", start_id, e
                )

        if not start_entity:
            return {
                "status": "failed",
                "error": f"Entity '{start_id}' not found",
                "error_type": "entity_not_found",
                "suggestions": [
                    "Check the entity name or ID",
                    "Use list_entities() to see available entities",
                    "Use find_similar() to search for similar entities",
                ],
            }

        # Check timeout after entity lookup
        if check_timeout():
            logger.warning(
                "graph_traverse timed out during entity lookup after %.1fms",
                (time.perf_counter() - start_time) * 1000,
            )
            return {
                "error": "timeout",
                "message": f"Graph traversal timed out after {effective_timeout_ms}ms during entity lookup",
                "start_id": start_id,
                "suggestion": "Try reducing max_depth or increasing timeout_ms",
            }

        # BFS traversal
        nodes: Dict[str, dict] = {}
        edges: List[dict] = []
        paths: List[List[str]] = []
        visited: set = set()
        timed_out = False

        start_entity_id = _get_attr(start_entity, "id") or _get_attr(
            start_entity, "name"
        )
        start_type = _get_attr(start_entity, "type")
        nodes[start_entity_id] = {
            "id": start_entity_id,
            "name": _get_attr(start_entity, "name"),
            "type": start_type,
            "entity_type": start_type,
            "file_path": _get_attr(start_entity, "file_path"),
            "depth": 0,
        }

        # Queue: (entity_id, current_depth, path)
        queue = [(start_entity_id, 0, [start_entity_id])]
        visited.add(start_entity_id)

        while queue:
            # Check timeout at each BFS iteration
            if check_timeout():
                timed_out = True
                logger.warning(
                    "graph_traverse timed out during BFS after %.1fms (nodes=%d, edges=%d)",
                    (time.perf_counter() - start_time) * 1000,
                    len(nodes),
                    len(edges),
                )
                break

            current_id, current_depth, current_path = queue.pop(0)

            if current_depth >= max_depth:
                continue

            # Get relationships
            try:
                # Build relationship query based on direction
                if direction.lower() == "outbound":
                    relationships = await db_manager.advanced_filter(
                        table_name="graph_relationships",
                        filters=source_id_filter(current_id),
                        limit=100,
                        project_id=project_id,
                    )
                elif direction.lower() == "inbound":
                    relationships = await db_manager.advanced_filter(
                        table_name="graph_relationships",
                        filters=target_id_filter(current_id),
                        limit=100,
                        project_id=project_id,
                    )
                else:  # both
                    outbound = await db_manager.advanced_filter(
                        table_name="graph_relationships",
                        filters=source_id_filter(current_id),
                        limit=100,
                        project_id=project_id,
                    )
                    inbound = await db_manager.advanced_filter(
                        table_name="graph_relationships",
                        filters=target_id_filter(current_id),
                        limit=100,
                        project_id=project_id,
                    )
                    relationships = outbound + inbound

                # Filter by relationship types if specified
                if relationship_types:
                    rel_types_lower = [rt.lower() for rt in relationship_types]
                    relationships = [
                        r
                        for r in relationships
                        if _get_attr(r, "type", "").lower() in rel_types_lower
                    ]

                # Process relationships
                for rel in relationships:
                    # Check timeout periodically during relationship processing
                    if check_timeout():
                        timed_out = True
                        break

                    source_id = _get_attr(rel, "source_id")
                    target_id = _get_attr(rel, "target_id")
                    rel_type = _get_attr(rel, "type")

                    # Determine the neighbor
                    if source_id == current_id:
                        neighbor_id = target_id
                        edge_direction = "outbound"
                    else:
                        neighbor_id = source_id
                        edge_direction = "inbound"

                    # Add edge
                    edges.append(
                        {
                            "source": source_id,
                            "target": target_id,
                            "type": rel_type,
                            "relationship_type": rel_type,
                            "direction": edge_direction,
                            "metadata": _get_attr(rel, "metadata", {}),
                        }
                    )

                    # Add neighbor node if not visited
                    if neighbor_id not in visited:
                        visited.add(neighbor_id)

                        # Get neighbor entity details
                        neighbor_entity = None
                        try:
                            neighbor_entities = await db_manager.advanced_filter(
                                table_name="graph_entities",
                                filters=by_id("id", neighbor_id),
                                limit=1,
                                project_id=project_id,
                            )
                            if neighbor_entities:
                                neighbor_entity = neighbor_entities[0]
                        except Exception as e:
                            # S5-002: Log neighbor ID lookup failure
                            logger.debug(
                                "Neighbor entity lookup by ID '%s' failed: %s",
                                neighbor_id,
                                e,
                            )

                        if not neighbor_entity:
                            # Try by name
                            try:
                                neighbor_entities = await db_manager.advanced_filter(
                                    table_name="graph_entities",
                                    filters=eq("name", neighbor_id),
                                    limit=1,
                                    project_id=project_id,
                                )
                                if neighbor_entities:
                                    neighbor_entity = neighbor_entities[0]
                            except Exception as e:
                                # S5-002: Log neighbor name lookup failure
                                logger.debug(
                                    "Neighbor entity lookup by name '%s' failed: %s",
                                    neighbor_id,
                                    e,
                                )

                        neighbor_type = (
                            _get_attr(neighbor_entity, "type")
                            if neighbor_entity
                            else "unknown"
                        )
                        nodes[neighbor_id] = {
                            "id": neighbor_id,
                            "name": _get_attr(neighbor_entity, "name")
                            if neighbor_entity
                            else neighbor_id,
                            "type": neighbor_type,
                            "entity_type": neighbor_type,
                            "file_path": _get_attr(neighbor_entity, "file_path")
                            if neighbor_entity
                            else None,
                            "depth": current_depth + 1,
                        }

                        new_path = current_path + [neighbor_id]
                        paths.append(new_path)
                        queue.append((neighbor_id, current_depth + 1, new_path))

                # Break out of main loop if timed out during relationship processing
                if timed_out:
                    break

            except Exception as e:
                logger.debug("Error traversing from %s: %s", current_id, e)
                continue

        # Track success
        await event_system.emit(
            "mcp.tool.completed",
            source="mcp_tool",
            tool_name="graph_traverse",
            session_id=session_id,
            nodes=len(nodes),
            edges=len(edges),
        )

        # Calculate execution time
        execution_time_ms = (time.perf_counter() - start_time) * 1000

        result = {
            "start_entity": {
                "id": start_entity_id,
                "name": _get_attr(start_entity, "name"),
                "type": _get_attr(start_entity, "type"),
                "entity_type": _get_attr(start_entity, "type"),
            },
            "nodes": list(nodes.values()),
            "edges": edges,
            "paths": paths[:50],  # Limit paths returned
            "traversal_stats": {
                "total_nodes": len(nodes),
                "total_edges": len(edges),
                "total_paths": len(paths),
                "max_depth_reached": max(n["depth"] for n in nodes.values())
                if nodes
                else 0,
            },
            "parameters": {
                "max_depth": max_depth,
                "direction": direction,
                "relationship_types": relationship_types,
            },
            "meta": {
                "execution_time_ms": round(execution_time_ms, 2),
                "result_count": len(nodes) + len(edges),
            },
        }

        # Add timeout warning if traversal was cut short
        if timed_out:
            result["warning"] = {
                "message": f"Traversal timed out after {effective_timeout_ms}ms",
                "partial_results": True,
                "suggestion": "Increase timeout_ms or reduce max_depth for complete results",
            }

        return result

    except Exception as e:
        await event_system.emit(
            "mcp.tool.failed",
            source="mcp_tool",
            tool_name="graph_traverse",
            error=str(e),
        )
        logger.error("Failed to traverse graph: %s", e, exc_info=True)
        return await MCPErrorHandler.handle(
            error=e,
            context={"session_id": session_id, "start_id": start_id},
            services=services,
        )


async def get_by_id(
    services: dict, session_id: str, ids: List[str], include_content: bool = True
) -> dict:
    """Bulk entity retrieval by ID.

    Retrieves multiple entities by their IDs in a single request.
    Efficient for fetching specific known entities.

    Args:
        services: Service dependency dict
        session_id: Session identifier
        ids: List of entity IDs to retrieve
        include_content: Include full content (default: True)

    Returns:
        Retrieved entities and list of not found IDs

    Example:
        >>> result = await get_by_id(
        ...     services, "sess_123",
        ...     ids=["entity_123", "entity_456", "chunk_789"]
        ... )
        >>> for entity in result["entities"]:
        ...     print(f"{entity['id']}: {entity['type']}")
    """
    session_manager = services["session_manager"]
    db_manager = services["storage"]
    event_system = services["event_system"]

    # Validate parameters
    if not ids or not isinstance(ids, list):
        return {
            "status": "failed",
            "error": "ids must be a non-empty list",
            "error_type": "validation_error",
        }

    if len(ids) > 100:
        return {
            "status": "failed",
            "error": "Maximum 100 IDs per request",
            "error_type": "validation_error",
        }

    # Validate session
    if not await session_manager.validate_session(session_id):
        return await MCPErrorHandler.handle(
            error=Exception(f"Session '{session_id}' not found or expired"),
            context={"session_id": session_id},
            services=services,
        )

    # Get session to extract project_id
    session = await session_manager.get_session(session_id, include_history=False)
    project_id = session.project_id

    # Track start
    await event_system.emit(
        "mcp.tool.started",
        source="mcp_tool",
        tool_name="get_by_id",
        session_id=session_id,
        id_count=len(ids),
    )

    try:
        entities = []
        not_found = []

        # Try to find each ID in different tables
        tables_to_search = ["graph_entities", "document_chunks"]

        for entity_id in ids:
            found = False

            for table_name in tables_to_search:
                try:
                    # Determine the ID field based on table
                    id_field = "id"

                    results = await db_manager.advanced_filter(
                        table_name=table_name,
                        filters=eq(id_field, entity_id),
                        limit=1,
                        project_id=project_id,
                    )

                    if results:
                        result = results[0]
                        # Use correct field per table schema
                        type_field = (
                            "type" if table_name == "graph_entities" else "content_type"
                        )
                        entity_data = {
                            "id": entity_id,
                            "type": _get_attr(result, type_field, "unknown"),
                            "source_table": table_name,
                        }

                        if table_name == "graph_entities":
                            entity_data.update(
                                {
                                    "name": _get_attr(result, "name"),
                                    "file_path": _get_attr(result, "file_path"),
                                    "line_start": _get_attr(result, "line_start"),
                                    "line_end": _get_attr(result, "line_end"),
                                    "parent": _get_attr(result, "parent_name"),
                                    "docstring": _get_attr(result, "docstring"),
                                }
                            )
                        else:  # document_chunks
                            entity_data.update(
                                {
                                    "file_path": _get_attr(result, "file_path"),
                                    "line_start": _get_attr(result, "line_start"),
                                    "line_end": _get_attr(result, "line_end"),
                                    "language": _get_attr(result, "language"),
                                    "symbols": _get_attr(result, "symbols", []),
                                }
                            )
                            if include_content:
                                entity_data["content"] = _get_attr(
                                    result, "content", ""
                                )

                        # Add metadata
                        if _get_attr(result, "metadata"):
                            entity_data["metadata"] = _get_attr(result, "metadata")

                        entities.append(entity_data)
                        found = True
                        break

                except Exception as e:
                    logger.debug(
                        "Error searching %s for %s: %s", table_name, entity_id, e
                    )
                    continue

            if not found:
                not_found.append(entity_id)

        # Track success
        await event_system.emit(
            "mcp.tool.completed",
            source="mcp_tool",
            tool_name="get_by_id",
            session_id=session_id,
            found=len(entities),
            not_found=len(not_found),
        )

        return {
            "entities": entities,
            "found_count": len(entities),
            "not_found": not_found,
            "not_found_count": len(not_found),
        }

    except Exception as e:
        await event_system.emit(
            "mcp.tool.failed", source="mcp_tool", tool_name="get_by_id", error=str(e)
        )
        logger.error("Failed to get entities by ID: %s", e, exc_info=True)
        return await MCPErrorHandler.handle(
            error=e,
            context={"session_id": session_id, "id_count": len(ids)},
            services=services,
        )


async def get_recent_activity(
    services: dict, session_id: str, time_range_days: int = 7
) -> dict:
    """Get recent project activity and changes.

    Analyzes temporal patterns in the indexed content to show:
    - Recently modified files
    - Hot areas (frequently changed directories)
    - New files added
    - Stale areas (not changed recently)

    Args:
        services: Service dependency dict
        session_id: Session identifier
        time_range_days: Days to look back (1-90, default: 7)

    Returns:
        Recent activity information

    Example:
        >>> result = await get_recent_activity(
        ...     services, "sess_123",
        ...     time_range_days=7
        ... )
        >>> for file in result["recent_activity"]["modified_files"]:
        ...     print(f"{file['path']}: {file['change_frequency']} changes")
    """
    from datetime import datetime, timedelta

    session_manager = services["session_manager"]
    db_manager = services["storage"]
    event_system = services["event_system"]
    config = services["config"]

    # Validate parameters
    if time_range_days < 1 or time_range_days > 90:
        return {
            "status": "failed",
            "error": "time_range_days must be between 1 and 90",
            "error_type": "validation_error",
        }

    # Validate session
    if not await session_manager.validate_session(session_id):
        return await MCPErrorHandler.handle(
            error=Exception(f"Session '{session_id}' not found or expired"),
            context={"session_id": session_id},
            services=services,
        )

    # Get session to extract project_id
    session = await session_manager.get_session(session_id, include_history=False)
    project_id = session.project_id

    # Track start
    await event_system.emit(
        "mcp.tool.started",
        source="mcp_tool",
        tool_name="get_recent_activity",
        session_id=session_id,
        time_range_days=time_range_days,
    )

    try:
        # Try to use TemporalAnalyzer if available
        try:
            from agentic_inquiry.mcp.services.temporal_analyzer import TemporalAnalyzer

            analyzer = TemporalAnalyzer(db_manager, config)
            activity = await analyzer.get_recent_activity(project_id, time_range_days)

            # Track success
            await event_system.emit(
                "mcp.tool.completed",
                source="mcp_tool",
                tool_name="get_recent_activity",
                session_id=session_id,
            )

            return {
                "recent_activity": activity,
                "time_range_days": time_range_days,
                "project_id": project_id,
            }

        except ImportError:
            logger.debug("TemporalAnalyzer not available, using fallback")

        # Fallback: Analyze based on indexed chunks
        # Note: cutoff_date would be used for filtering if chunks had timestamps
        # For now, we analyze all indexed content
        _ = datetime.now() - timedelta(days=time_range_days)  # Reserved for future use

        # Get all indexed chunks
        try:
            chunks = await db_manager.advanced_filter(
                table_name="document_chunks",
                filters={},
                limit=5000,
                project_id=project_id,
            )
        except Exception:
            chunks = []

        if not chunks:
            return {
                "recent_activity": {
                    "modified_files": [],
                    "hot_areas": [],
                    "new_files": [],
                    "stale_areas": [],
                    "message": "No indexed content found",
                },
                "time_range_days": time_range_days,
                "project_id": project_id,
            }

        # Group by file path
        file_info: Dict[str, dict] = {}
        for chunk in chunks:
            file_path = _get_attr(chunk, "file_path", "")
            if not file_path:
                continue

            if file_path not in file_info:
                file_info[file_path] = {
                    "path": file_path,
                    "chunks": 0,
                    "last_indexed": _get_attr(chunk, "indexed_at"),
                    "language": _get_attr(chunk, "language"),
                }
            file_info[file_path]["chunks"] += 1

            # Track most recent
            indexed_at = _get_attr(chunk, "indexed_at")
            if indexed_at and (
                not file_info[file_path]["last_indexed"]
                or indexed_at > file_info[file_path]["last_indexed"]
            ):
                file_info[file_path]["last_indexed"] = indexed_at

        # Sort files by last indexed
        sorted_files = sorted(
            file_info.values(),
            key=lambda x: x.get("last_indexed") or "",  # file_info values are dicts
            reverse=True,
        )

        # Analyze directory activity
        dir_activity: Dict[str, int] = {}
        for file in sorted_files:
            parts = Path(file["path"]).parts
            if len(parts) > 1:
                dir_path = str(Path(*parts[:-1])) + "/"
                dir_activity[dir_path] = dir_activity.get(dir_path, 0) + 1

        hot_areas = [
            {"directory": d, "file_count": c}
            for d, c in sorted(dir_activity.items(), key=lambda x: x[1], reverse=True)[
                :10
            ]
        ]

        # Track success
        await event_system.emit(
            "mcp.tool.completed",
            source="mcp_tool",
            tool_name="get_recent_activity",
            session_id=session_id,
        )

        return {
            "recent_activity": {
                "modified_files": sorted_files[:20],
                "hot_areas": hot_areas,
                "new_files": sorted_files[:10],  # Most recently indexed
                "stale_areas": [],  # Would need file system access for real staleness
                "total_files": len(file_info),
                "total_chunks": len(chunks),
            },
            "time_range_days": time_range_days,
            "project_id": project_id,
        }

    except Exception as e:
        await event_system.emit(
            "mcp.tool.failed",
            source="mcp_tool",
            tool_name="get_recent_activity",
            error=str(e),
        )
        logger.error("Failed to get recent activity: %s", e, exc_info=True)
        return await MCPErrorHandler.handle(
            error=e, context={"session_id": session_id}, services=services
        )


async def save_onboard_report(
    services: dict,
    project_id: str,
    run_id: str,
    report_name: str,
    content: str,
) -> dict:
    """Save an onboard report via configured artifact storage.

    Routes to local filesystem or GCS based on ``config.onboard.artifact_storage``.

    Args:
        services: Service dependency dict.
        project_id: Project identifier.
        run_id: Onboard run identifier.
        report_name: Report name (e.g. ``EXPLORATION``, ``VALIDATION``, ``ONBOARD``).
        content: Report content (markdown).

    Returns:
        Dict with ``path`` (storage location) and ``storage_type``.
    """
    config = services["config"]

    # Input validation
    if not project_id or not project_id.strip():
        return {"status": "error", "error": "project_id must be non-empty"}
    if not run_id or not run_id.strip():
        return {"status": "error", "error": "run_id must be non-empty"}
    if not report_name or not report_name.strip():
        return {"status": "error", "error": "report_name must be non-empty"}
    if not content:
        return {"status": "error", "error": "content must be non-empty"}

    # Reject path traversal
    for field_name, field_value in [
        ("project_id", project_id),
        ("run_id", run_id),
        ("report_name", report_name),
    ]:
        if ".." in field_value or "/" in field_value or "\\" in field_value:
            return {
                "status": "error",
                "error": f"{field_name} must not contain path traversal characters",
            }
        if "\x00" in field_value:
            return {
                "status": "error",
                "error": f"{field_name} must not contain null bytes",
            }

    # Allowed report names
    allowed_names = {"EXPLORATION", "VALIDATION", "ONBOARD"}
    if report_name.upper() not in allowed_names:
        logger.warning(
            "Non-standard report name: %s (allowed: %s)",
            report_name,
            allowed_names,
        )

    try:
        from agentic_inquiry.onboard.artifact_storage import (
            create_onboard_artifact_storage,
        )

        storage = create_onboard_artifact_storage(config)
        path = await storage.save_report(project_id, run_id, report_name, content)

        storage_type = getattr(
            getattr(
                getattr(config, "onboard", None),
                "artifact_storage",
                None,
            ),
            "type",
            "local",
        )

        logger.info(
            "Saved onboard report %s for %s/%s via %s",
            report_name,
            project_id,
            run_id,
            storage_type,
        )

        return {
            "status": "success",
            "path": path,
            "storage_type": storage_type,
        }

    except ImportError as e:
        logger.error("GCS dependency missing: %s", e)
        return {
            "status": "error",
            "error": str(e),
            "error_type": "dependency_missing",
        }
    except Exception as e:
        logger.error("Failed to save onboard report: %s", e, exc_info=True)
        return {
            "status": "error",
            "error": str(e),
            "error_type": "storage_error",
        }


__all__ = [
    "index_files",
    "search_code",
    "search_docs",
    "graph_traverse",
    "get_by_id",
    "get_recent_activity",
    "save_onboard_report",
]
