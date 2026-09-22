"""Memory management tools for MCP server.

These tools provide persistent memory capabilities for AI agents:
- Saving observations and insights
- Recalling relevant past memories
"""

import logging
from typing import Optional, List, Union

logger = logging.getLogger(__name__)


async def save_memory(
    services: dict,
    session_id: str,
    summary: str,
    content: str,
    importance: Union[str, float] = "medium",
    tags: Optional[List[str]] = None
) -> dict:
    """Save an observation or insight to memory.

    Stores the memory in the appropriate tier (working/episodic/semantic)
    based on importance. High-importance memories are more likely to be
    preserved during consolidation.

    Args:
        services: Service dependency dict
        session_id: Session identifier
        summary: Brief summary of the memory (used for recall)
        content: Full memory content/details
        importance: Memory importance - either categorical ("low", "medium", "high")
                   or numeric (0.0-1.0). Categorical values map to: low=0.5, medium=0.8, high=0.9
        tags: Optional tags for categorization

    Returns:
        Memory metadata including ID and tier placement

    Example:
        >>> result = await save_memory(
        ...     services, "sess_123",
        ...     summary="SearchService uses hybrid approach",
        ...     content="Combines vector + FTS with RRF",
        ...     importance="high",  # or importance=0.85
        ...     tags=["architecture", "search"]
        ... )
        >>> memory_id = result["memory_id"]
    """
    from agentic_inquiry.mcp.utils.errors import MCPErrorHandler
    
    session_manager = services["session_manager"]
    memory_system = services["memory_system"]
    event_system = services["event_system"]

    # Validate session
    if not await session_manager.validate_session(session_id):
        return await MCPErrorHandler.handle(
            error=Exception(f"Session '{session_id}' not found or expired"),
            context={"session_id": session_id},
            services=services
        )

    # Track start
    await event_system.emit(
        "mcp.tool.started",
        source="mcp_tool",
        tool_name="save_memory",
        session_id=session_id
    )

    try:
        # P2-1 Fix: Support both categorical and numeric importance
        if isinstance(importance, (int, float)):
            # Direct numeric importance (0.0-1.0)
            importance_score = float(importance)
            if not 0.0 <= importance_score <= 1.0:
                return await MCPErrorHandler.handle(
                    error=ValueError(f"Numeric importance must be between 0.0 and 1.0, got {importance_score}"),
                    context={"session_id": session_id, "importance": importance},
                    services=services
                )
        else:
            # Map categorical importance string to numeric value
            # "medium" maps to 0.8 (episodic tier) to ensure persistence.
            # Values < 0.7 route to volatile WorkingMemory (in-memory only).
            importance_map = {
                "low": 0.5,
                "medium": 0.8,
                "high": 0.9
            }
            importance_score = importance_map.get(str(importance).lower(), 0.8)

        # Get session to extract project_id
        session = await session_manager.get_session(session_id, include_history=False)
        project_id = session.project_id

        # Create memory context
        from agentic_inquiry.memory.models import MemoryContext
        context = MemoryContext(
            agent_id="mcp_user",
            session_id=session_id,
            conversation_id=session_id,  # Use session as conversation for simplicity
            project_id=project_id,
            metadata={"tags": tags or []}
        )

        # Store memory
        memory = await memory_system.store(
            content=content,
            context=context,
            importance=importance_score,
            summary=summary,
            metadata={
                "session_id": session_id,
                "tags": tags or []
            }
        )

        # Track success (generic tool event)
        await event_system.emit(
            "mcp.tool.completed",
            source="mcp_tool",
            tool_name="save_memory",
            session_id=session_id,
            memory_id=memory.id
        )

        # P2-2 Fix: Emit specific memory.saved event for event tracking
        await event_system.emit(
            "memory.saved",
            source="memory_system",
            session_id=session_id,
            memory_id=memory.id,
            tier=memory.tier,
            importance=importance_score,
            summary=summary,
            tags=tags or []
        )

        # P2-2 Fix: Add event to session for get_events visibility
        await session_manager.add_event(
            session_id=session_id,
            event_type="memory.saved",
            data={
                "memory_id": memory.id,
                "tier": memory.tier,
                "importance": importance_score,
                "summary": summary
            }
        )

        return {
            "status": "saved",
            "memory_id": memory.id,
            "tier": memory.tier,
            "importance": importance_score,
            "summary": summary,
            "tags": tags or []
        }

    except Exception as e:
        # Track failure
        await event_system.emit(
            "mcp.tool.failed",
            source="mcp_tool",
            tool_name="save_memory",
            error=str(e)
        )
        logger.error("Failed to save memory: %s", e, exc_info=True)
        return await MCPErrorHandler.handle(
            error=e,
            context={
                "session_id": session_id,
                "summary": summary,
                "importance": importance
            },
            services=services
        )


async def recall_memories(
    services: dict,
    session_id: str,
    query: str,
    limit: int = 10,
    min_importance: float = 0.0
) -> dict:
    """Recall relevant memories based on semantic similarity.

    Searches across all memory tiers (working, episodic, semantic) to find
    memories most relevant to the query. Results are ranked by both
    semantic similarity and importance scores.

    Args:
        services: Service dependency dict
        session_id: Session identifier
        query: Query to find relevant memories
        limit: Maximum number of memories to return
        min_importance: Minimum importance threshold (0.0-1.0)

    Returns:
        List of relevant memories with metadata

    Example:
        >>> result = await recall_memories(
        ...     services, "sess_123",
        ...     query="architecture patterns",
        ...     limit=5
        ... )
        >>> for memory in result["memories"]:
        ...     print(f"{memory['summary']}: {memory['importance']}")
    """
    from agentic_inquiry.mcp.utils.errors import MCPErrorHandler
    from agentic_inquiry.mcp.utils.validation import (
        validate_query_length,
        create_validation_error_response,
        QueryValidationError
    )

    session_manager = services["session_manager"]
    memory_system = services["memory_system"]
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
            example='query="architecture patterns"'
        )

    # Validate session
    if not await session_manager.validate_session(session_id):
        return await MCPErrorHandler.handle(
            error=Exception(f"Session '{session_id}' not found or expired"),
            context={"session_id": session_id},
            services=services
        )

    # Track start
    await event_system.emit(
        "mcp.tool.started",
        source="mcp_tool",
        tool_name="recall_memories",
        session_id=session_id,
        query=query
    )

    try:
        # Get session to extract project_id
        session = await session_manager.get_session(session_id, include_history=False)
        project_id = session.project_id

        # Create memory context for retrieval
        from agentic_inquiry.memory.models import MemoryContext
        context = MemoryContext(
            agent_id="mcp_user",
            session_id=session_id,
            conversation_id=session_id,
            project_id=project_id
        )

        # Contextual memory enrichment (#84): boost recall with recent entity context
        # If the session has recently accessed entities, append their names to the
        # query so memories about related entities rank higher.
        enriched_query = query
        try:
            history = await session_manager.get_session(session_id, include_history=True)
            recent_entities = set()
            for event in (history.events or [])[-20:]:  # Last 20 events
                if hasattr(event, 'data') and isinstance(event.data, dict):
                    for key in ("entity", "entity_name", "start_id"):
                        if key in event.data and event.data[key]:
                            recent_entities.add(str(event.data[key]))
            if recent_entities:
                entity_context = " ".join(list(recent_entities)[:5])
                enriched_query = f"{query} {entity_context}"
                logger.debug("Memory recall enriched with entity context: %s", entity_context)
        except Exception:
            pass  # Non-fatal — fall back to original query

        # Retrieve memories
        memories_response = await memory_system.retrieve(
            query=enriched_query,
            context=context,
            limit=limit,
            strategy="ambiguity_aware"
        )
        
        # Handle ambiguity response (RetrievalEngine returns Dict when strategy=ambiguity_aware)
        clarification_request = None
        ambiguity_info = None
        if isinstance(memories_response, dict):
            memories = memories_response["results"]
            ambiguity_info = memories_response["ambiguity"]
            clarification_request = memories_response.get("clarification_question")
        else:
            memories = memories_response

        # Filter by importance if specified
        if min_importance > 0.0:
            memories = [
                m for m in memories
                if m.item.importance >= min_importance
            ]

        # Format results
        results = []
        for retrieval_result in memories:
            memory = retrieval_result.item
            results.append({
                "memory_id": memory.id,
                "summary": memory.summary or "",  # Use top-level summary field
                "content": memory.content,
                "importance": memory.importance,
                "tier": memory.tier.value,
                "tags": memory.metadata.get("tags", []),
                "created_at": memory.created_at.isoformat(),
                "access_count": memory.access_count,
                "relevance_score": retrieval_result.relevance_score
            })

        # Track success (generic tool event)
        await event_system.emit(
            "mcp.tool.completed",
            source="mcp_tool",
            tool_name="recall_memories",
            session_id=session_id,
            count=len(results)
        )

        # P2-2 Fix: Emit specific memory.recalled event for event tracking
        await event_system.emit(
            "memory.recalled",
            source="memory_system",
            session_id=session_id,
            query=query,
            result_count=len(results),
            min_importance=min_importance,
            limit=limit
        )

        # P2-2 Fix: Add event to session for get_events visibility
        await session_manager.add_event(
            session_id=session_id,
            event_type="memory.recalled",
            data={
                "query": query,
                "result_count": len(results),
                "min_importance": min_importance
            }
        )

        response: dict = {
            "memories": results,
            "total": len(results),
            "query": query
        }
        
        if clarification_request:
            response["clarification_needed"] = True
            response["clarification_request"] = clarification_request
            response["ambiguity_info"] = ambiguity_info
            
        return response

    except Exception as e:
        # Track failure
        await event_system.emit(
            "mcp.tool.failed",
            source="mcp_tool",
            tool_name="recall_memories",
            error=str(e)
        )
        logger.error("Failed to recall memories: %s", e, exc_info=True)
        return await MCPErrorHandler.handle(
            error=e,
            context={
                "session_id": session_id,
                "query": query,
                "limit": limit
            },
            services=services
        )


__all__ = [
    "save_memory",
    "recall_memories"
]
