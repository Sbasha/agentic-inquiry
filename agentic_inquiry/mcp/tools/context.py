"""Context building tools for MCP server.

These tools assemble relevant context for AI agents, respecting token budgets.
"""

import logging
import time
from typing import List

logger = logging.getLogger(__name__)


def _generate_empty_context_suggestions(query: str, has_memories: bool) -> List[str]:
    """Generate helpful suggestions when context is empty.
    
    Args:
        query: The search query that returned no results
        has_memories: Whether any memories were found
        
    Returns:
        List of suggestion strings
    """
    suggestions = []
    
    # Suggest checking indexed content
    suggestions.append(
        "No code or documentation found. Check that content has been indexed "
        "with 'add_knowledge' tool."
    )
    
    # Suggest broader search
    suggestions.append(
        f"Try a broader search query. Current query: '{query}'"
    )
    
    # Suggest saving memories if none exist
    if not has_memories:
        suggestions.append(
            "No memories found. Save important insights with 'save_memory' "
            "for future recall."
        )
    
    # Suggest checking project
    suggestions.append(
        "Verify you're searching the correct project with 'get_session_status'."
    )
    
    return suggestions


async def build_context(
    services: dict,
    session_id: str,
    query: str,
    focus: str = "balanced",
    depth: str = "focused",
    max_tokens: int = 4000,
    include_overview: bool = False
) -> dict:
    """Build focused context for a task or query.

    Intelligently assembles relevant code, documentation, and memories
    while respecting token budgets. Uses search, entity resolution, and
    memory recall to gather exactly what's needed.

    Args:
        services: Service dependency dict
        session_id: Session identifier
        query: Task or question to build context for
        focus: Context emphasis: "code", "documentation", "balanced"
        depth: Context depth: "minimal", "focused" (default), "comprehensive"
        max_tokens: Maximum tokens to use (default: 4000)
        include_overview: If True, prioritize overview content (README, docs, architecture)

    Returns:
        Assembled context with code, docs, and memories

    Example:
        >>> result = await build_context(
        ...     services, "sess_123",
        ...     query="implement search filter for file types",
        ...     focus="code",
        ...     depth="focused",
        ...     max_tokens=2000
        ... )
        >>> print(result["context"]["code"])  # Relevant code snippets
        >>> print(result["context"]["memories"])  # Related insights
    """
    from agentic_inquiry.mcp.utils.errors import MCPErrorHandler
    from agentic_inquiry.mcp.utils.validation import (
        validate_query_length,
        create_validation_error_response,
        QueryValidationError
    )

    session_manager = services["session_manager"]
    context_builder = services["context_builder"]
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
            example='query="implement search filter"'
        )

    # Validate session
    if not await session_manager.validate_session(session_id):
        return await MCPErrorHandler.handle(
            error=Exception(f"Session '{session_id}' not found or expired"),
            context={
                "session_id": session_id,
                "query": query,
                "focus": focus,
                "depth": depth,
                "max_tokens": max_tokens
            },
            services=services
        )

    # Track start
    await event_system.emit(
        "mcp.tool.started",
        source="mcp_tool",
        tool_name="build_context",
        session_id=session_id,
        query=query
    )

    try:
        # Start timing for performance instrumentation
        start_time = time.perf_counter()

        # Build context using ContextBuilder
        context_build_start = time.perf_counter()
        context_result = await context_builder.build_context(
            query=query,
            session_id=session_id,
            focus="all" if focus == "balanced" else focus,
            depth=depth,
            max_tokens=max_tokens,
            include_overview=include_overview
        )
        context_build_time_ms = (time.perf_counter() - context_build_start) * 1000

        # Extract context data
        context_data = context_result.get("context", {})
        code_items = context_data.get("code", [])
        doc_items = context_data.get("documentation", [])
        memory_items = context_data.get("memories", [])
        
        # Check if context is empty
        is_empty = (
            not code_items and 
            not doc_items and 
            not memory_items
        )
        
        # Track if fallback was used
        fallback_used = False
        
        # Fallback strategy: if context is empty, try basic search
        if is_empty:
            logger.warning(
                "ContextBuilder returned empty context for query='%s', "
                "attempting fallback to basic search",
                query
            )
            
            fallback_used = True
            
            # Get search service for fallback
            search_service = services["search_service"]
            session = await session_manager.get_session(session_id)
            
            if session:
                try:
                    # Get query vector for hybrid search
                    # For server-side embedding backends, pass raw query text
                    capabilities = services.get("capabilities")
                    if capabilities is None:
                        from agentic_inquiry.storage.capabilities import get_capabilities_for_backend
                        db_manager = services["storage"]
                        _backend = db_manager.get_backend_type() if hasattr(db_manager, 'get_backend_type') else "lancedb"
                        capabilities = get_capabilities_for_backend(_backend)

                    if capabilities.uses_server_side_embedding:
                        query_vector = query  # Raw text for server-side embedding
                    else:
                        query_vector_array = await search_service.embedding_service.embed_async(query)
                        query_vector = query_vector_array.tolist()

                    # Perform hybrid search as fallback
                    search_results = await search_service.hybrid_search(
                        query_vector=query_vector,
                        query_fts=query,
                        limit=10,
                        project_id=session.project_id,
                        boost_overview=include_overview
                    )
                    
                    # Convert search results to context format
                    if search_results:
                        logger.info(
                            "Fallback search returned %d results",
                            len(search_results)
                        )
                        
                        # Categorize results by type
                        for result in search_results:
                            # Handle both SearchResult objects and plain dicts
                            data = result.data if hasattr(result, 'data') else result
                            result_id = getattr(result, 'id', data.get('id', ''))
                            result_distance = getattr(result, 'distance', data.get('distance', 1.0))

                            result_type = data.get("chunk_type", "")

                            # Create context item
                            item = {
                                "id": result_id,
                                "name": data.get("name", "Unknown"),
                                "summary": data.get("content", "")[:200],
                                "relevance_score": max(0.0, 1.0 - (result_distance if result_distance is not None else 1.0)),
                                "location": data.get("file_path", ""),
                                "snippet": data.get("content", "")[:300],
                                "metadata": {
                                    "language": data.get("language", ""),
                                    "line_start": data.get("start_line"),
                                    "line_end": data.get("end_line")
                                }
                            }

                            # Add to appropriate category
                            if result_type in ["function", "class", "method"]:
                                code_items.append(item)
                            elif result_type in ["heading", "section", "paragraph"]:
                                doc_items.append(item)
                    else:
                        logger.warning("Fallback search also returned no results")
                        
                except Exception as fallback_error:
                    logger.error(
                        "Fallback search failed: %s",
                        fallback_error,
                        exc_info=True
                    )
        
        # Generate suggestions for empty or sparse context
        suggestions = context_result.get("suggestions", [])
        
        # Check if context is still empty after fallback
        is_still_empty = (
            not code_items and 
            not doc_items
        )
        
        # Add suggestions for empty context
        if is_still_empty:
            suggestions.extend(_generate_empty_context_suggestions(
                query=query,
                has_memories=bool(memory_items)
            ))
        
        # Get token usage
        token_usage_data = context_result.get("token_usage", {})
        used_tokens = token_usage_data.get("estimated_tokens", 0)
        
        # Track success
        total_items = len(code_items) + len(doc_items) + len(memory_items)
        await event_system.emit(
            "mcp.tool.completed",
            source="mcp_tool",
            tool_name="build_context",
            session_id=session_id,
            items_count=total_items
        )

        # Add performance metadata
        execution_time_ms = (time.perf_counter() - start_time) * 1000

        return {
            "context": {
                "code": code_items,
                "documentation": doc_items,
                "memories": memory_items
            },
            "summary": context_result.get("summary", f"Found {total_items} items"),
            "token_usage": {
                "used": used_tokens,
                "budget": max_tokens,
                "remaining": max_tokens - used_tokens
            },
            "suggestions": suggestions,
            "fallback_used": fallback_used,
            "meta": {
                "execution_time_ms": round(execution_time_ms, 2),
                "context_build_time_ms": round(context_build_time_ms, 2),
                "result_count": total_items
            }
        }

    except Exception as e:
        # Track failure
        await event_system.emit(
        "mcp.tool.failed",
        source="mcp_tool",
            tool_name="build_context",
            error=str(e)
        )
        logger.error("Failed to build context: %s", e, exc_info=True)
        return await MCPErrorHandler.handle(
            error=e,
            context={
                "session_id": session_id,
                "query": query,
                "max_tokens": max_tokens
            },
            services=services
        )


__all__ = ["build_context"]
