"""Analysis tools for MCP server.

These tools provide code analysis capabilities:
- Understanding code entities with dependencies
- Analyzing impact of changes
- Finding patterns in the codebase
"""

import asyncio
import logging
import time
from typing import Optional

from agentic_inquiry.config import Config
from agentic_inquiry.mcp.utils.project_state import check_project_state

logger = logging.getLogger(__name__)


async def understand_entity(
    services: dict,
    session_id: str,
    entity: str,
    entity_type: Optional[str] = None,
    include_dependencies: bool = True,
    include_usage: bool = True,
    trace_depth: int = 0,
    timeout_ms: Optional[int] = None
) -> dict:
    """Deep dive into a code entity (class, function, module).

    Returns entity definition, documentation, dependencies (what it uses),
    and usage examples (what uses it). Enables understanding of component
    relationships and architecture.

    Entity Types:
        Code: function, class, module, method, variable
        Docs: section, page, heading
        Memory: memory_observation, memory_insight

    Note: Entity type should be consistent across all tools.
    If entity was indexed as 'function', use 'function' not 'method'.
    Use list_entities to verify the exact entity_type before querying.

    Args:
        services: Service dependency dict
        session_id: Session identifier
        entity: Entity name or identifier (e.g., "SearchService", "hybrid_search")
        entity_type: Optional entity type filter (class, function, method, etc.)
        include_dependencies: Include what this entity depends on
        include_usage: Include code that uses this entity
        timeout_ms: Optional timeout in milliseconds. If None, uses config default (5000ms).
            Set to 0 to disable timeout.

    Returns:
        Entity details with dependencies and usage information

    Example:
        >>> result = await understand_entity(
        ...     services, "sess_123",
        ...     entity="SearchService",
        ...     include_dependencies=True
        ... )
        >>> print(result["entity"]["entity_type"])  # class
        >>> print(result["dependencies"])  # What it imports/uses
    """
    from agentic_inquiry.mcp.utils.errors import MCPErrorHandler
    from agentic_inquiry.mcp.services.entity_resolver import EntityNotFoundError
    from agentic_inquiry.mcp.utils.validation import (
        EntityNameValidationError,
        validate_entity_name,
        extract_entity_name_from_id,
    )

    session_manager = services["session_manager"]
    entity_resolver = services["entity_resolver"]
    event_system = services["event_system"]

    # Extract entity name from full ID if provided (e.g., "class::project::/path::Name")
    # This allows users to pass entity IDs from graph_traverse directly
    original_entity = entity
    entity_name, is_full_id = extract_entity_name_from_id(entity)

    # Validate extracted entity name (security: prevent path traversal, enforce length limits)
    try:
        entity_name = validate_entity_name(entity_name, field_name="entity")
    except EntityNameValidationError as e:
        return await MCPErrorHandler.handle(
            error=e,
            context={"session_id": session_id, "entity": original_entity},
            services=services
        )

    # Use original entity for resolution if it was a full ID, otherwise use validated name
    entity = original_entity if is_full_id else entity_name

    # Validate session
    if not await session_manager.validate_session(session_id):
        return await MCPErrorHandler.handle(
            error=Exception(f"Session '{session_id}' not found or expired"),
            context={"session_id": session_id},
            services=services
        )

    # Get session to extract project_id
    session = await session_manager.get_session(session_id, include_history=False)
    project_id = session.project_id

    # P1-3: Check project state for stale index
    db_manager = services["storage"]
    project_state = await check_project_state(db_manager, project_id)

    # Track start
    await event_system.emit(
        "mcp.tool.started",
        source="mcp_tool",
        tool_name="understand_entity",
        session_id=session_id,
        entity=entity
    )

    try:
        # Start timing for performance instrumentation
        start_time = time.perf_counter()

        # Get timeout from config or parameter
        config: Config = services["config"]
        graph_timeouts = config.search.graph_search.timeouts
        if timeout_ms is not None:
            effective_timeout_ms = timeout_ms if timeout_ms > 0 else 999999
        else:
            effective_timeout_ms = graph_timeouts.understand_entity_ms
        timeout_seconds = effective_timeout_ms / 1000.0

        # Resolve entity using EntityResolver (with timeout)
        entity_resolution_start = time.perf_counter()
        try:
            entity_def = await asyncio.wait_for(
                entity_resolver.resolve_entity(
                    entity_name=entity,
                    project_id=project_id,
                    entity_type=entity_type,
                    include_relationships=True
                ),
                timeout=timeout_seconds
            )
        except asyncio.TimeoutError:
            logger.warning("Entity resolution timed out after %.1fms", effective_timeout_ms)
            return {
                "error": "timeout",
                "message": f"Entity resolution timed out after {effective_timeout_ms}ms",
                "suggestion": "Try with a higher timeout_ms value"
            }
        entity_resolution_time_ms = (time.perf_counter() - entity_resolution_start) * 1000

        # Calculate remaining time for subsequent operations
        remaining_ms = effective_timeout_ms - entity_resolution_time_ms
        if remaining_ms <= 0:
            remaining_ms = 100  # Minimum time for remaining ops

        # Get dependencies if requested (with timeout)
        graph_traversal_start = time.perf_counter()
        dependencies = []
        if include_dependencies and entity_def:
            try:
                dep_refs = await asyncio.wait_for(
                    entity_resolver.get_entity_dependencies(
                        entity_id=entity_def.entity_id,
                        project_id=project_id,
                        depth=1
                    ),
                    timeout=remaining_ms / 1000.0
                )
                dependencies = [
                    {
                        "name": dep.name,
                        "entity_type": dep.entity_type,
                        "file_path": dep.file_path,
                        "relationship_type": dep.relationship_type
                    }
                    for dep in dep_refs
                ]
            except asyncio.TimeoutError:
                logger.debug("Dependencies lookup timed out, skipping")

        # Update remaining time
        remaining_ms = remaining_ms - (time.perf_counter() - graph_traversal_start) * 1000
        if remaining_ms <= 0:
            remaining_ms = 100

        # Get usage examples if requested (with timeout)
        usage_examples = []
        if include_usage and entity_def:
            try:
                usage_refs = await asyncio.wait_for(
                    entity_resolver.get_entity_usages(
                        entity_id=entity_def.entity_id,
                        project_id=project_id,
                        limit=10
                    ),
                    timeout=remaining_ms / 1000.0
                )
                usage_examples = [
                    {
                        "file_path": usage.file_path,
                        "line_number": usage.line_number,
                        "context": usage.context,
                        "usage_type": usage.usage_type
                    }
                    for usage in usage_refs
                ]
            except asyncio.TimeoutError:
                logger.debug("Usage lookup timed out, skipping")
        graph_traversal_time_ms = (time.perf_counter() - graph_traversal_start) * 1000

        # Trace dependency chains (#85: Narrative entity understanding)
        # When trace_depth > 0, follow the most important dependency paths
        # and format them as readable chains for architecture understanding.
        dependency_chains = []
        if trace_depth > 0 and entity_def and dependencies:
            try:
                # Follow each import/call dependency up to trace_depth hops
                for dep in dependencies[:3]:  # Top 3 deps only
                    if dep.get("relationship_type") not in ("imports", "calls", "inherits", "defines"):
                        continue
                    chain = [{"name": entity_def.name, "type": entity_def.entity_type}]
                    chain.append({
                        "name": dep["name"],
                        "type": dep.get("entity_type", ""),
                        "via": dep["relationship_type"],
                    })
                    # Follow one more hop if trace_depth >= 2
                    if trace_depth >= 2:
                        try:
                            # Resolve dep name to canonical ID for 2nd hop
                            dep_resolved = await asyncio.wait_for(
                                entity_resolver.resolve_entity(
                                    entity_name=dep["name"],
                                    project_id=project_id,
                                ),
                                timeout=1.0,
                            )
                            dep_id = dep_resolved.entity_id if dep_resolved else dep["name"]
                            sub_deps = await asyncio.wait_for(
                                entity_resolver.get_entity_dependencies(
                                    entity_id=dep_id,
                                    project_id=project_id,
                                    depth=1,
                                ),
                                timeout=1.0,
                            )
                            for sd in sub_deps[:2]:
                                if sd.relationship_type in ("imports", "calls", "inherits", "defines"):
                                    chain.append({
                                        "name": sd.name,
                                        "type": sd.entity_type,
                                        "via": sd.relationship_type,
                                    })
                                    break  # One sub-dep per chain
                        except Exception:
                            pass
                    if len(chain) >= 2:
                        # Format as narrative
                        narrative = " → ".join(
                            f"{c['via']} → {c['name']}" if 'via' in c else c['name']
                            for c in chain
                        )
                        dependency_chains.append({
                            "chain": chain,
                            "narrative": narrative,
                            "depth": len(chain) - 1,
                        })
            except Exception as e:
                logger.debug("Trace chain failed: %s", e)

        # Track success
        await event_system.emit(
            "mcp.tool.completed",
            source="mcp_tool",
            tool_name="understand_entity",
            session_id=session_id,
            entity=entity
        )

        # Calculate total results for meta
        result_count = 1 + len(dependencies) + len(usage_examples)

        # Add performance metadata
        execution_time_ms = (time.perf_counter() - start_time) * 1000

        return {
            "entity": {
                "name": entity_def.name,
                "entity_type": entity_def.entity_type,
                "file_path": entity_def.file_path,
                "line_start": entity_def.line_start,
                "line_end": entity_def.line_end,
                "content": entity_def.content,
                "documentation": entity_def.docstring,
            },
            "dependencies": dependencies,
            "dependency_chains": dependency_chains if dependency_chains else None,
            "usage_examples": usage_examples,
            "metadata": entity_def.metadata,
            "meta": {
                "execution_time_ms": round(execution_time_ms, 2),
                "entity_resolution_time_ms": round(entity_resolution_time_ms, 2),
                "graph_traversal_time_ms": round(graph_traversal_time_ms, 2),
                "result_count": result_count
            }
        }

    except EntityNotFoundError as e:
        # Handle entity not found with suggestions
        await event_system.emit(
            "mcp.tool.failed",
            source="mcp_tool",
            tool_name="understand_entity",
            error=str(e)
        )
        logger.warning("Entity not found: %s", e)

        # P1-3: Enhance error with stale index guidance
        suggestions = list(e.suggestions) if e.suggestions else []
        if project_state.get("is_empty") or project_state.get("is_incomplete"):
            suggestions.insert(0, "Project index may be stale. Run add_knowledge() to refresh.")
        if project_state.get("warnings"):
            suggestions = project_state["warnings"] + suggestions

        return await MCPErrorHandler.handle(
            error=e,
            context={
                "session_id": session_id,
                "entity": entity,
                "suggestions": suggestions
            },
            services=services
        )
    except Exception as e:
        # Track failure
        await event_system.emit(
            "mcp.tool.failed",
            source="mcp_tool",
            tool_name="understand_entity",
            error=str(e)
        )
        logger.error("Failed to understand entity: %s", e, exc_info=True)
        return await MCPErrorHandler.handle(
            error=e,
            context={
                "session_id": session_id,
                "entity": entity
            },
            services=services
        )


async def analyze_impact(
    services: dict,
    session_id: str,
    entity: str,
    max_depth: int = 2,
    timeout_ms: Optional[int] = None,
    page: int = 0,
    page_size: int = 10,
    summary_only: bool = False
) -> dict:
    """Analyze the impact of changing a code entity.

    Traverses dependency graph to find all code that would be affected
    by changes to the specified entity. Returns impact radius with
    file counts and affected components.

    Results are paginated by default to keep context concise. Use page/page_size
    to navigate through affected entities, or summary_only=True for just counts.

    Prerequisites:
        - Indexing must be complete (use add_knowledge first)
        - Relationships must be flushed (happens automatically after indexing pipeline completes)
        - Entity must exist in the index (verify with list_entities first)

    If relationships are empty, results will show no dependencies.
    To populate relationships, ensure the indexing pipeline completes fully.

    Args:
        services: Service dependency dict
        session_id: Session identifier
        entity: Entity name to analyze (e.g., "SearchService")
        max_depth: How many levels deep to traverse (default: 2)
        timeout_ms: Optional timeout in milliseconds. If not provided,
            uses config default (analyze_impact_ms). Set to 0 to disable.
        page: Page number for paginated results (0-indexed, default: 0)
        page_size: Number of entities per page (default: 10, max: 50)
        summary_only: If True, return only counts without entity details (default: False)

    Returns:
        Impact analysis with affected files and components, paginated

    Example:
        >>> # Get summary only (fastest, smallest context)
        >>> result = await analyze_impact(services, "sess_123", entity="StorageFacade", summary_only=True)
        >>> print(f"Would affect {result['impact_radius']} entities")
        >>>
        >>> # Get first page of details
        >>> result = await analyze_impact(services, "sess_123", entity="StorageFacade", page=0, page_size=10)
        >>> print(result["affected_entities"])  # First 10
        >>>
        >>> # Get next page
        >>> result = await analyze_impact(services, "sess_123", entity="StorageFacade", page=1, page_size=10)
    """
    from agentic_inquiry.mcp.utils.errors import MCPErrorHandler
    from agentic_inquiry.mcp.services.entity_resolver import EntityNotFoundError
    from agentic_inquiry.mcp.services.impact_analyzer import PartialResultsException
    from agentic_inquiry.mcp.utils.validation import (
        EntityNameValidationError,
        validate_entity_name,
        extract_entity_name_from_id,
    )

    session_manager = services["session_manager"]
    impact_analyzer = services["impact_analyzer"]
    event_system = services["event_system"]
    config: Config = services["config"]

    # Get timeout from config or parameter
    graph_timeouts = config.search.graph_search.timeouts
    if timeout_ms is not None:
        effective_timeout_ms = timeout_ms if timeout_ms > 0 else 999999
    else:
        effective_timeout_ms = graph_timeouts.analyze_impact_ms
    start_time = time.perf_counter()

    # Extract entity name from full ID if provided (e.g., "class::project::/path::Name")
    # This allows users to pass entity IDs from graph_traverse directly
    original_entity = entity
    entity_name, is_full_id = extract_entity_name_from_id(entity)

    # Validate extracted entity name (security: prevent path traversal, enforce length limits)
    try:
        entity_name = validate_entity_name(entity_name, field_name="entity")
    except EntityNameValidationError as e:
        return await MCPErrorHandler.handle(
            error=e,
            context={"session_id": session_id, "entity": original_entity},
            services=services
        )

    # Use original entity for resolution if it was a full ID, otherwise use validated name
    entity = original_entity if is_full_id else entity_name

    # Validate session
    if not await session_manager.validate_session(session_id):
        return await MCPErrorHandler.handle(
            error=Exception(f"Session '{session_id}' not found or expired"),
            context={"session_id": session_id},
            services=services
        )

    # Get session to extract project_id
    session = await session_manager.get_session(session_id, include_history=False)
    project_id = session.project_id

    # P1-3: Check project state for stale index
    db_manager = services["storage"]
    project_state = await check_project_state(db_manager, project_id)

    # Track start
    await event_system.emit(
        "mcp.tool.started",
        source="mcp_tool",
        tool_name="analyze_impact",
        session_id=session_id,
        entity=entity
    )

    try:
        # Calculate remaining time budget and deadline
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        remaining_seconds = max(0.1, (effective_timeout_ms - elapsed_ms) / 1000.0)
        deadline = time.time() + remaining_seconds

        # Use ImpactAnalyzer to analyze impact (with timeout and partial results support)
        try:
            impact = await asyncio.wait_for(
                impact_analyzer.analyze_impact(
                    entity_name=entity,
                    project_id=project_id,
                    depth=max_depth,
                    include_indirect=True,
                    deadline=deadline
                ),
                timeout=remaining_seconds
            )
        except PartialResultsException as e:
            # Return partial results with "partial": true flag
            logger.warning(
                "analyze_impact returned partial results after %.1fms for entity=%s (completed depth: %d)",
                e.elapsed_ms, entity, e.partial_results.get("completed_depth", 0)
            )
            await event_system.emit(
                "mcp.tool.completed",
                source="mcp_tool",
                tool_name="analyze_impact",
                session_id=session_id,
                partial=True,
                completed_depth=e.partial_results.get("completed_depth", 0)
            )

            # Format partial affected_entities with pagination
            partial_entities = e.partial_results.get("affected_entities", [])
            all_partial_entities = [
                {
                    "name": ref.name,
                    "entity_type": ref.entity_type,
                    "file_path": ref.file_path,
                    "relationship_type": ref.relationship_type
                }
                for ref in partial_entities
                if not (ref.file_path.startswith("builtin://") or
                        ref.file_path.startswith("external://"))
            ]

            # Apply pagination to partial results
            page_size_clamped = max(1, min(page_size, 50))
            total_partial = len(all_partial_entities)
            start_idx = page * page_size_clamped
            end_idx = start_idx + page_size_clamped
            paginated_entities = all_partial_entities[start_idx:end_idx] if not summary_only else []

            # Format partial relationship_types
            relationship_types_dict = e.partial_results.get("relationship_types", {})

            partial_response: dict = {
                "partial": True,
                "timeout_after_ms": e.elapsed_ms,
                "entity": entity,
                "impact_radius": len(partial_entities),
                "relationship_types": relationship_types_dict,
                "completed_depth": e.partial_results.get("completed_depth", 0),
                "requested_depth": max_depth,
                "incoming_completed": e.partial_results.get("incoming_completed", False),
                "outgoing_completed": e.partial_results.get("outgoing_completed", False),
                "pagination": {
                    "page": page,
                    "page_size": page_size_clamped,
                    "total_entities": total_partial,
                    "has_more": end_idx < total_partial,
                    "summary_only": summary_only
                },
                "message": f"Analysis timed out after {e.elapsed_ms}ms. Returning partial results.",
                "suggestion": "Try summary_only=True for faster results, or reduce max_depth"
            }

            if not summary_only:
                partial_response["affected_entities"] = paginated_entities

            return partial_response
        except asyncio.TimeoutError:
            # Fallback for hard timeout (shouldn't happen if deadline is respected)
            logger.warning(
                "analyze_impact timed out after %.1fms for entity=%s (hard timeout)",
                effective_timeout_ms, entity
            )
            await event_system.emit(
                "mcp.tool.failed",
                source="mcp_tool",
                tool_name="analyze_impact",
                error="timeout"
            )
            return {
                "error": "timeout",
                "message": f"Impact analysis timed out after {effective_timeout_ms}ms",
                "entity": entity,
                "suggestion": "Try reducing max_depth or increasing timeout_ms"
            }

        # Enforce page_size limits
        page_size = max(1, min(page_size, 50))  # Clamp between 1 and 50
        page = max(0, page)  # Ensure non-negative

        # Format affected_files as dict with entity counts
        # Filter out builtins and externals from file paths
        affected_files_dict = {
            file_path: count
            for file_path, count in impact.affected_files.items()
            if not (file_path.startswith("builtin://") or
                    file_path.startswith("external://"))
        }

        # Format affected_entities list (full list for counting)
        # Filter out builtins and externals from affected entities
        all_affected_entities = [
            {
                "name": ref.name,
                "entity_type": ref.entity_type,
                "file_path": ref.file_path,
                "relationship_type": ref.relationship_type
            }
            for ref in impact.affected_entities
            if not (ref.file_path.startswith("builtin://") or
                    ref.file_path.startswith("external://"))
        ]

        # Apply pagination
        total_entities = len(all_affected_entities)
        start_idx = page * page_size
        end_idx = start_idx + page_size
        affected_entities_list = all_affected_entities[start_idx:end_idx] if not summary_only else []
        has_more = end_idx < total_entities

        # Format relationship_types
        relationship_types_dict = {
            rel_type: count
            for rel_type, count in impact.relationship_types.items()
        }

        # Track success
        await event_system.emit(
            "mcp.tool.completed",
            source="mcp_tool",
            tool_name="analyze_impact",
            session_id=session_id,
            entity=entity,
            impact_radius=impact.impact_radius
        )

        # Get indexed content statistics for scope context
        # Note: db_manager already retrieved for project state check (P1-3)
        try:
            indexed_entities_count = await db_manager.count_records(
                table_name="graph_entities",
                project_id=project_id
            )
            indexed_chunks_count = await db_manager.count_records(
                table_name="document_chunks",
                project_id=project_id
            )
        except Exception:
            indexed_entities_count = 0
            indexed_chunks_count = 0

        # Build response with pagination
        response: dict = {
            "entity": entity,
            "impact_radius": impact.impact_radius,
            "file_count": len(affected_files_dict),
            "relationship_types": relationship_types_dict,
            "traversal_depth": impact.traversal_depth,
            "guidance": {
                "risk_level": "high" if impact.impact_radius > 10 else "medium" if impact.impact_radius > 5 else "low",
                "recommendation": f"Changing this entity would affect {impact.impact_radius} entities across {len(affected_files_dict)} files"
            }
        }

        # Add pagination metadata
        response["pagination"] = {
            "page": page,
            "page_size": page_size,
            "total_entities": total_entities,
            "has_more": has_more,
            "summary_only": summary_only
        }

        # Only include detailed lists if not summary_only
        if not summary_only:
            response["affected_entities"] = affected_entities_list
            response["affected_files"] = affected_files_dict
            if has_more:
                response["hint"] = f"Use page={page + 1} to see next {min(page_size, total_entities - end_idx)} entities"
        else:
            response["hint"] = "Use summary_only=False to see affected entity details"

        # Add scope info (compact)
        response["scope"] = {
            "indexed_entities": indexed_entities_count,
            "indexed_chunks": indexed_chunks_count
        }

        # Add warning when no affected entities found
        if impact.impact_radius == 0:
            response["warning"] = {
                "message": "No affected entities found in indexed content",
                "possible_causes": [
                    "Entity may be referenced in files not yet indexed",
                    "Relationships may not be extracted from all file types",
                    "Only a subset of the codebase may be indexed"
                ],
                "suggestions": [
                    "Index the full codebase: add_knowledge(source='.', content_type='directory')",
                    "Check what's indexed: get_project_info()",
                    "Search for usages: search_knowledge(query='imports " + entity + "')"
                ]
            }

        # Add dependency trees only if not summary_only (they're large)
        if not summary_only:
            if impact.dependency_tree:
                response["dependency_tree"] = impact.dependency_tree.to_dict()

            # Add incoming impact tree (what depends on this entity - reverse impact)
            if impact.incoming_tree:
                response["incoming_impact"] = impact.incoming_tree.to_dict()

        return response

    except EntityNotFoundError as e:
        # Handle entity not found with suggestions
        await event_system.emit(
            "mcp.tool.failed",
            source="mcp_tool",
            tool_name="analyze_impact",
            error=str(e)
        )
        logger.warning("Entity not found: %s", e)

        # P1-3: Enhance error with stale index guidance
        suggestions = list(e.suggestions) if e.suggestions else []
        if project_state.get("is_empty") or project_state.get("is_incomplete"):
            suggestions.insert(0, "Project index may be stale. Run add_knowledge() to refresh.")
        if project_state.get("warnings"):
            suggestions = project_state["warnings"] + suggestions

        return await MCPErrorHandler.handle(
            error=e,
            context={
                "session_id": session_id,
                "entity": entity,
                "suggestions": suggestions
            },
            services=services
        )
    except Exception as e:
        # Track failure
        await event_system.emit(
            "mcp.tool.failed",
            source="mcp_tool",
            tool_name="analyze_impact",
            error=str(e)
        )
        logger.error("Failed to analyze impact: %s", e, exc_info=True)
        return await MCPErrorHandler.handle(
            error=e,
            context={
                "session_id": session_id,
                "entity": entity,
                "max_depth": max_depth
            },
            services=services
        )


async def find_patterns(
    services: dict,
    session_id: str,
    pattern_type: str = "auto",
    limit: int = 10,
    timeout_ms: Optional[int] = None
) -> dict:
    """Find recurring patterns in the codebase.

    Analyzes code to identify design patterns, architectural patterns,
    naming conventions, and anti-patterns. Helps understand project
    structure and conventions.

    Args:
        services: Service dependency dict
        session_id: Session identifier
        pattern_type: Pattern to find: "auto" (detect), "architectural",
                      "design", "naming", or "antipattern"
        limit: Maximum number of patterns to return
        timeout_ms: Optional timeout in milliseconds. If not provided,
            uses config default (find_patterns_ms). Set to 0 to disable.

    Returns:
        Discovered patterns with examples and prevalence

    Example:
        >>> result = await find_patterns(
        ...     services, "sess_123",
        ...     pattern_type="architectural"
        ... )
        >>> for pattern in result["patterns"]:
        ...     print(f"{pattern['name']}: {pattern['count']} occurrences")
    """
    from agentic_inquiry.mcp.utils.errors import MCPErrorHandler
    
    session_manager = services["session_manager"]
    pattern_analyzer = services["pattern_analyzer"]
    event_system = services["event_system"]
    config: Config = services["config"]

    # Get timeout from config or parameter
    graph_timeouts = config.search.graph_search.timeouts
    if timeout_ms is not None:
        effective_timeout_ms = timeout_ms if timeout_ms > 0 else 999999
    else:
        effective_timeout_ms = graph_timeouts.find_patterns_ms
    start_time = time.perf_counter()

    # Validate session
    if not await session_manager.validate_session(session_id):
        return await MCPErrorHandler.handle(
            error=Exception(f"Session '{session_id}' not found or expired"),
            context={"session_id": session_id},
            services=services
        )

    # Get session to extract project_id
    session = await session_manager.get_session(session_id, include_history=False)
    project_id = session.project_id

    # Track start
    await event_system.emit(
        "mcp.tool.started",
        source="mcp_tool",
        tool_name="find_patterns",
        session_id=session_id,
        pattern_type=pattern_type
    )

    try:
        # P1-2 Fix: Check project state and provide feedback if insufficient data
        from agentic_inquiry.mcp.utils.project_state import check_project_state
        db_manager = services["storage"]
        project_state = await check_project_state(db_manager, project_id)

        # Calculate remaining time budget
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        remaining_seconds = max(0.1, (effective_timeout_ms - elapsed_ms) / 1000.0)

        # Find patterns (with timeout)
        try:
            patterns = await asyncio.wait_for(
                pattern_analyzer.find_patterns(
                    project_id=project_id,
                    pattern_type=pattern_type if pattern_type != "auto" else None,
                    limit=limit
                ),
                timeout=remaining_seconds
            )
        except asyncio.TimeoutError:
            logger.warning(
                "find_patterns timed out after %.1fms for pattern_type=%s",
                effective_timeout_ms, pattern_type
            )
            await event_system.emit(
                "mcp.tool.failed",
                source="mcp_tool",
                tool_name="find_patterns",
                error="timeout"
            )
            return {
                "error": "timeout",
                "message": f"Pattern analysis timed out after {effective_timeout_ms}ms",
                "pattern_type": pattern_type,
                "suggestion": "Try reducing limit or increasing timeout_ms"
            }

        # Track success
        await event_system.emit(
            "mcp.tool.completed",
            source="mcp_tool",
            tool_name="find_patterns",
            session_id=session_id,
            count=len(patterns)
        )

        # Build response with recommendations if empty
        response = {
            "patterns": patterns,
            "total": len(patterns),
            "pattern_type": pattern_type
        }

        # P1-2 Fix: Add helpful feedback when no patterns found
        if len(patterns) == 0:
            recommendations = []
            if project_state["is_empty"]:
                recommendations.append(
                    "No indexed content. Use add_knowledge() to index your codebase first."
                )
            elif project_state["chunk_count"] < 50:
                recommendations.append(
                    f"Only {project_state['chunk_count']} chunks indexed. "
                    "Pattern detection needs more content (50+ chunks recommended)."
                )
            else:
                recommendations.append(
                    "No patterns detected for this pattern type. "
                    "Try pattern_type='auto' to search all categories."
                )
            response["recommendations"] = recommendations
            response["message"] = "No patterns found - see recommendations"

        return response

    except Exception as e:
        # Track failure
        await event_system.emit(
        "mcp.tool.failed",
        source="mcp_tool",
            tool_name="find_patterns",
            error=str(e)
        )
        logger.error("Failed to find patterns: %s", e, exc_info=True)
        return await MCPErrorHandler.handle(
            error=e,
            context={
                "session_id": session_id,
                "pattern_type": pattern_type,
                "limit": limit
            },
            services=services
        )


async def compare_patterns(
    services: dict,
    session_id: str,
    target: str,
    reference_pattern: str = "",
    reference_type: Optional[str] = None,
) -> dict:
    """Compare a target entity's structure against similar entities (#83).

    Extracts the relationship signature (imports, inherits, calls) of the
    target entity and compares it against entities matching the reference
    pattern. Returns a structural diff showing what's present, missing,
    or extra compared to the reference group.

    Use cases:
    - Code review: "Does NewEmbedder follow the same pattern as existing embedders?"
    - Compliance: "Does this service implement the same interfaces as its siblings?"

    Args:
        services: Service dependency dict
        session_id: Session identifier
        target: Entity name to analyze (e.g., "NewEmbedder")
        reference_pattern: Name pattern for reference entities (e.g., "*Embedder")
        reference_type: Entity type filter for references (e.g., "class")

    Returns:
        Structural comparison with present/missing/extra relationships
    """
    session_manager = services["session_manager"]
    entity_resolver = services["entity_resolver"]

    if not await session_manager.validate_session(session_id):
        from agentic_inquiry.mcp.utils.errors import MCPErrorHandler
        return await MCPErrorHandler.handle(
            error=Exception(f"Session '{session_id}' not found or expired"),
            context={"session_id": session_id},
            services=services
        )

    session = await session_manager.get_session(session_id, include_history=False)
    project_id = session.project_id

    try:
        # Get target entity's relationship signature
        target_deps = await entity_resolver.get_entity_dependencies(
            entity_id=target, project_id=project_id, depth=1
        )
        target_sig = {
            (d.relationship_type, d.name) for d in target_deps
        }

        # Find reference entities matching pattern
        from agentic_inquiry.mcp.tools.info import list_entities
        refs_result = await list_entities(
            services, session_id,
            entity_type=reference_type,
            pattern=reference_pattern,
            limit=10,
        )
        ref_entities = refs_result.get("entities", [])
        # Exclude the target itself
        ref_entities = [e for e in ref_entities if e.get("name") != target]

        if not ref_entities:
            return {
                "target": target,
                "reference_pattern": reference_pattern,
                "status": "no_references",
                "message": f"No reference entities found matching '{reference_pattern}'",
            }

        # Build aggregate signature from reference entities
        ref_sigs = []
        common_relationships: dict[str, int] = {}  # relationship -> count of refs that have it
        for ref in ref_entities[:5]:
            ref_name = ref.get("name", "")
            try:
                ref_deps = await entity_resolver.get_entity_dependencies(
                    entity_id=ref_name, project_id=project_id, depth=1
                )
                ref_sig = {(d.relationship_type, d.name) for d in ref_deps}
                ref_sigs.append(ref_sig)
                for rel_type, dep_name in ref_sig:
                    key = f"{rel_type}:{dep_name}"
                    common_relationships[key] = common_relationships.get(key, 0) + 1
            except Exception:
                continue

        if not ref_sigs:
            return {
                "target": target,
                "reference_pattern": reference_pattern,
                "status": "no_reference_data",
                "message": "Could not resolve dependencies for reference entities",
            }

        # Identify common patterns (present in >50% of references)
        threshold = len(ref_sigs) / 2
        expected = {
            k for k, count in common_relationships.items() if count >= threshold
        }
        target_keys = {f"{rt}:{name}" for rt, name in target_sig}

        present = expected & target_keys
        missing = expected - target_keys
        extra = target_keys - expected

        # Format results
        def parse_key(k):
            parts = k.split(":", 1)
            return {"relationship": parts[0], "entity": parts[1]} if len(parts) == 2 else {"raw": k}

        compliance_pct = round(len(present) / max(len(expected), 1) * 100)

        return {
            "target": target,
            "reference_pattern": reference_pattern,
            "reference_count": len(ref_sigs),
            "compliance_score": compliance_pct,
            "present": [parse_key(k) for k in sorted(present)],
            "missing": [parse_key(k) for k in sorted(missing)],
            "extra": [parse_key(k) for k in sorted(extra)],
            "summary": (
                f"{target} matches {compliance_pct}% of the pattern from {len(ref_sigs)} "
                f"reference entities. {len(missing)} relationships missing, "
                f"{len(extra)} extra relationships not in the reference pattern."
            ),
        }

    except Exception as e:
        logger.error("Pattern comparison failed: %s", e, exc_info=True)
        return {"error": str(e), "target": target}


__all__ = [
    "understand_entity",
    "analyze_impact",
    "find_patterns",
    "compare_patterns"
]
