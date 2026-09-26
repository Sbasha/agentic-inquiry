"""Search tools for MCP server.

These tools provide semantic search across indexed code and documentation.
"""

import asyncio
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Optional, List, Literal

from agentic_inquiry.mcp.utils.errors import MCPErrorHandler
from agentic_inquiry.mcp.utils.index_state import (
    IndexState,
    detect_index_state,
)
from agentic_inquiry.mcp.utils.fallback_search import (
    execute_fallback_search,
    is_structural_query,
    should_use_fallback,
    structural_search,
)
import numpy as np
from agentic_inquiry.database.filter_helpers import (
    combine_filters,
    by_type,
    id_in_list,
)
from agentic_inquiry.models.graph_entity import GraphEntity
from agentic_inquiry.utils.metacognition import ClarificationBuilder

logger = logging.getLogger(__name__)

# Content type enum for agentic content discovery (SDD-001)
# Exposes valid content types in tool schema for model-driven filtering
ContentType = Literal[
    "CODE", "PROSE", "TABLE", "HEADING", "LIST_ITEM", "IMAGE_CAPTION", "TITLE", "OTHER"
]

# Preview mode snippet length (SDD-001)
# Truncates content for token efficiency in preview_only mode
PREVIEW_SNIPPET_LENGTH = 100


def _to_entity_dict(entity) -> dict:
    """Convert GraphEntity or dict to a plain dict.

    GraphEntity uses @dataclass(slots=True) which means it has no __dict__.
    This helper normalizes results from database queries that may return
    either GraphEntity objects or dicts depending on the provider.
    """
    if isinstance(entity, dict):
        return entity
    if isinstance(entity, GraphEntity):
        return entity.to_dict()
    # Fallback for any other object with attributes
    return {
        "id": getattr(entity, "id", ""),
        "name": getattr(entity, "name", ""),
        "type": getattr(entity, "type", ""),
        "file_path": getattr(entity, "file_path", ""),
        "doc_id": getattr(entity, "doc_id", ""),
        "project_id": getattr(entity, "project_id", ""),
        "domain": getattr(entity, "domain", "code"),
        "line_start": getattr(entity, "line_start", -1),
        "line_end": getattr(entity, "line_end", -1),
        "parent_name": getattr(entity, "parent_name", ""),
        "docstring": getattr(entity, "docstring", ""),
        "_distance": getattr(entity, "_distance", None),
    }


def build_result_quality(
    index_status: str,
    progress_percent: Optional[float],
    strategy: str,
    result_count: int,
) -> dict:
    """Build result quality indicator for search response.

    Creates a quality indicator that communicates the reliability of search
    results based on the current index state. This helps users understand
    whether results may be incomplete due to ongoing indexing.

    Args:
        index_status: Current index status from IndexState enum value
            (e.g., "indexing", "sparse", "stale", "ready")
        progress_percent: Index completion percentage (0-100), or None if unknown
        strategy: Search strategy being used (from SearchStrategy enum value)
        result_count: Number of results returned by the search

    Returns:
        Dictionary containing:
        - level: Quality level ("full", "partial", or "limited")
        - coverage_percent: Index coverage as a float (0-100)
        - note: Human-readable explanation of result quality
        - strategy: The search strategy used
        - result_count: Number of results returned

    Quality Levels:
        - "full": Index is >= 80% complete, results are comprehensive
        - "partial": Index is 50-80% complete, results may be incomplete
        - "limited": Index is < 50% complete, limited results available

    Examples:
        >>> build_result_quality("indexing", 45.0, "hybrid_fallback", 8)
        {
            "level": "limited",
            "coverage_percent": 45.0,
            "note": "Limited results (45% indexed). More results available as indexing completes.",
            "strategy": "hybrid_fallback",
            "result_count": 8
        }
        >>> build_result_quality("ready", 100.0, "semantic_only", 15)
        {
            "level": "full",
            "coverage_percent": 100.0,
            "note": "Results from fully indexed codebase",
            "strategy": "semantic_only",
            "result_count": 15
        }
    """
    if progress_percent is None:
        progress_percent = 0.0

    # Determine quality level based on index progress
    if progress_percent >= 80:
        level = "full"
        note = "Results from fully indexed codebase"
    elif progress_percent >= 50:
        level = "partial"
        note = f"Results may be incomplete ({progress_percent:.0f}% indexed)"
    else:
        level = "limited"
        note = (
            f"Limited results ({progress_percent:.0f}% indexed). "
            "More results available as indexing completes."
        )

    return {
        "level": level,
        "coverage_percent": round(progress_percent, 1),
        "note": note,
        "strategy": strategy,
        "result_count": result_count,
    }


# Multi-pass search thresholds
THRESHOLD_HIGH = 0.5
THRESHOLD_MEDIUM = 0.35
THRESHOLD_LOW = 0.2

# Confidence level thresholds (ISS-W2-017)
CONFIDENCE_HIGH = 0.7
CONFIDENCE_MEDIUM = 0.5

# Code entity types for prioritization (ISS-W2-010/015)
# Uses plain structural types - domain is stored separately on GraphEntity
CODE_ENTITY_TYPES = frozenset(
    {
        "class",
        "function",
        "method",
        "module",
        "variable",
        "interface",
        "property",
        "constructor",
    }
)


def _classify_confidence(similarity: float) -> str:
    """Classify result confidence based on similarity score.

    ISS-W2-017: Add confidence level distinction to results.

    Args:
        similarity: Similarity score between 0.0 and 1.0

    Returns:
        Confidence level: "high", "medium", or "low"
    """
    if similarity >= CONFIDENCE_HIGH:
        return "high"
    if similarity >= CONFIDENCE_MEDIUM:
        return "medium"
    return "low"


def _determine_match_quality(similarity: float, is_fuzzy: bool = False) -> str:
    """Determine match quality label based on similarity score."""
    if is_fuzzy:
        return "fuzzy"
    if similarity >= THRESHOLD_HIGH:
        return "high"
    if similarity >= THRESHOLD_MEDIUM:
        return "medium"
    return "low"


def _generate_similar_recommendations(
    query: str, results: list, match_summary: dict, entity_type: Optional[str] = None
) -> dict:
    """Generate contextual recommendations based on search results.

    Args:
        query: Original search query
        results: List of found entities
        match_summary: Counts by match quality
        entity_type: Optional entity type filter used

    Returns:
        Dictionary with recommendations for refining searches
    """
    recommendations: dict[str, list[str]] = {
        "refine_query": [],
        "related_tools": [],
        "tips": [],
    }

    total_results = sum(match_summary.values())
    high_confidence = match_summary.get("high", 0)

    # Query refinement suggestions
    query_words = query.lower().split()
    if len(query_words) > 3:
        recommendations["refine_query"].append(
            f"Try shorter query: '{' '.join(query_words[:2])}'"
        )

    if len(query_words) == 1 and len(query) > 10:
        # Might be a class name - suggest splitting
        recommendations["refine_query"].append(
            "If searching for a class, try partial name (e.g., 'Search' instead of 'SearchService')"
        )

    # Extract potential entity names from results for suggestions
    if results:
        common_prefixes = set()
        for r in results[:5]:
            name = r.get("name", "")
            if "_" in name:
                prefix = name.split("_")[0]
                if len(prefix) > 2:
                    common_prefixes.add(prefix)

        if common_prefixes:
            prefix = list(common_prefixes)[0]
            recommendations["refine_query"].append(
                f"Related pattern found: try searching for '{prefix}'"
            )

    # Related tool suggestions
    if total_results == 0:
        recommendations["related_tools"] = [
            "search_knowledge(query='...') - Full-text search across all content",
            "list_entities() - Browse all indexed entities",
            "get_project_info() - Check what's indexed",
        ]
    elif high_confidence == 0:
        recommendations["related_tools"].append(
            "understand_entity(entity='...') - Deep dive into a specific entity"
        )
        recommendations["related_tools"].append(
            "search_knowledge(query='...') - Try content-based search"
        )
    else:
        # Good results - suggest next steps
        if results:
            top_entity = results[0].get("name", "")
            recommendations["related_tools"].append(
                f"understand_entity(entity='{top_entity}') - Explore this entity"
            )
            recommendations["related_tools"].append(
                f"analyze_impact(entity='{top_entity}') - See what depends on it"
            )

    # Tips based on results quality
    if total_results > 0 and high_confidence == 0:
        recommendations["tips"].append(
            "Results are medium/low confidence - consider verifying relevance"
        )

    if entity_type and total_results == 0:
        recommendations["tips"].append(
            f"No {entity_type} entities found - try without entity_type filter"
        )

    # Clean up empty lists
    return {k: v for k, v in recommendations.items() if v}


def _extract_metadata_fields(raw_metadata: Any, allowed_keys: set) -> dict:
    """Extract allowed fields from metadata dict.

    JSONB deserialization is now handled at the adapter layer (storage
    providers), so *raw_metadata* should already be a Python dict.  A
    defensive ``isinstance`` check is kept for backward-compatibility
    with any code path that may still pass a JSON string.
    """
    if isinstance(raw_metadata, str):
        import json as _json

        try:
            raw_metadata = _json.loads(raw_metadata)
        except (ValueError, TypeError):
            return {}
    if not isinstance(raw_metadata, dict):
        return {}
    return {k: v for k, v in raw_metadata.items() if k in allowed_keys}


def _fuzzy_name_match(query: str, entity_name: str) -> float:
    """Calculate fuzzy match score between query and entity name.

    Uses multiple strategies:
    1. Exact match (case-insensitive)
    2. Substring match
    3. Word overlap (for multi-word queries)
    4. CamelCase/snake_case word matching

    Returns:
        Score between 0.0 and 1.0
    """
    query_lower = query.lower()
    name_lower = entity_name.lower()

    # Exact match
    if query_lower == name_lower:
        return 1.0

    # Query is substring of name or vice versa
    if query_lower in name_lower:
        return 0.8 + (0.1 * len(query_lower) / len(name_lower))
    if name_lower in query_lower:
        return 0.7

    # Split into words (handle CamelCase and snake_case)
    def split_words(text: str) -> List[str]:
        # Split on underscores and camelCase boundaries
        expanded = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
        word_list = expanded.replace("_", " ").lower().split()
        return [w for w in word_list if len(w) > 1]

    query_words = set(split_words(query))
    name_words = set(split_words(entity_name))

    if not query_words or not name_words:
        return 0.0

    # Calculate word overlap
    common_words = query_words & name_words
    if common_words:
        overlap_score = len(common_words) / max(len(query_words), len(name_words))
        return 0.5 + (0.4 * overlap_score)

    # Partial word matching (any query word is substring of any name word)
    for qw in query_words:
        for nw in name_words:
            if qw in nw or nw in qw:
                return 0.4

    return 0.0


def diversify_entity_results(
    entities: list[dict], limit: int = 10, max_per_file: int = 2
) -> list[dict]:
    """Group entities by file and interleave to ensure diversity.

    This function addresses ISS-002 where find_similar(search_scope="entities")
    returns all results from the same file with identical similarity scores.
    By limiting entities per file and interleaving results from different files,
    we ensure users get a diverse set of results across the codebase.

    Args:
        entities: Sorted list of entities by similarity score
        limit: Maximum results to return
        max_per_file: Maximum entities from any single file

    Returns:
        Diversified list of entities
    """
    from collections import defaultdict

    file_groups: dict[str, list[dict]] = defaultdict(list)
    for entity in entities:
        file_path = entity.get("file_path", "")
        if len(file_groups[file_path]) < max_per_file:
            file_groups[file_path].append(entity)

    # Round-robin interleave from each file group
    result: List[dict] = []
    group_iters = [iter(group) for group in file_groups.values()]

    while group_iters and len(result) < limit:
        remaining_iters = []
        for it in group_iters:
            try:
                entity = next(it)
                result.append(entity)
                if len(result) >= limit:
                    break
                remaining_iters.append(it)
            except StopIteration:
                continue
        group_iters = remaining_iters

    return result


def _generate_usage_hints(results: list, query: str, related_keywords: list) -> dict:
    """Generate usage hints based on search results.

    Args:
        results: Formatted search results
        query: Original search query
        related_keywords: Related keywords extracted from results

    Returns:
        Dictionary with next_steps and related_tools
    """
    hints: dict[str, list[str]] = {"next_steps": [], "related_tools": []}

    # Analyze results to provide contextual hints
    if not results:
        return hints

    # Check if results contain code entities
    has_code = any(r.get("entity_type") or r.get("symbols") for r in results)
    has_docs = any(r.get("language") == "markdown" for r in results)

    # Generate next steps based on result types
    if has_code:
        # Found code - suggest entity understanding
        entities = []
        for r in results[:3]:  # Top 3 results
            if r.get("symbols"):
                entities.extend(r["symbols"][:2])  # First 2 symbols per result

        if entities:
            hints["next_steps"].append(
                f"Understand key entities: {', '.join(entities[:3])}"
            )
            hints["related_tools"].append("understand_entity")

    if has_docs:
        # Found documentation - suggest context building
        hints["next_steps"].append("Build comprehensive context with build_context()")
        hints["related_tools"].append("build_context")

    # Suggest refining with related keywords
    if related_keywords:
        hints["next_steps"].append(
            f"Refine search with related keywords: {', '.join(related_keywords[:5])}"
        )

    # Suggest impact analysis if code entities found
    if has_code:
        hints["next_steps"].append(
            "Analyze impact before making changes with analyze_impact()"
        )
        hints["related_tools"].append("analyze_impact")

    # Suggest saving insights
    hints["next_steps"].append("Save important findings with save_memory()")
    hints["related_tools"].append("save_memory")

    # Deduplicate related tools
    hints["related_tools"] = list(dict.fromkeys(hints["related_tools"]))

    return hints


async def _entities_from_semantic_search(
    db_manager,
    embedding_service,
    search_service,
    query: str,
    project_id: str,
    entity_type_lower: Optional[str] = None,
    limit: int = 20,
    query_vector: Optional[np.ndarray] = None,
) -> List[dict]:
    """Find entities by searching code chunks semantically, then extracting entities.

    This semantic bridge approach works when:
    - Entity embeddings (based on names) don't match semantic queries
    - User searches for functionality like "database connection management"
    - We need to find entities by what they DO, not what they're NAMED

    Strategy:
    1. Search code chunks semantically (these have rich content embeddings)
    2. Find entities defined in those file locations (batched query)
    3. Return entities with their semantic relevance scores

    Args:
        db_manager: Database manager for entity queries
        embedding_service: Embedding service for query vectorization
        search_service: Search service for hybrid search
        query: Semantic query text
        project_id: Project ID to filter results
        entity_type_lower: Optional entity type filter (lowercase)
        limit: Maximum entities to return
        query_vector: Pre-computed query embedding (avoids duplicate embedding generation)

    Returns:
        List of entity dicts with 'semantic_bridge_score' indicating relevance
    """
    try:
        # Step 1: Search code chunks semantically
        # Use pre-computed vector if provided to avoid duplicate embedding generation
        step1_start = time.perf_counter()
        if query_vector is None:
            query_vector = await embedding_service.embed_async(query)

        # Use soft content preference instead of hard filter (SDD-001)
        # This boosts CODE results while still allowing cross-content discovery
        # Performance optimization: use smaller limit for semantic bridge (SG-PERF-001)
        # to reduce search time while still finding relevant entity locations
        chunk_results = await search_service.hybrid_search(
            query_vector=query_vector
            if isinstance(query_vector, str)
            else query_vector.tolist(),
            query_fts=query,
            project_id=project_id,
            limit=min(limit, 10),  # Cap at 10 chunks for faster semantic bridge
            content_preference="CODE",  # Boost code, but include docs for discovery
            content_preference_weight=0.7,  # 70% boost for code content
            boost_overview=False,  # We want code, not docs
        )
        step1_time = (time.perf_counter() - step1_start) * 1000

        if not chunk_results:
            logger.debug("Semantic bridge: No chunks found for query '%s'", query)
            return []

        # Step 2: Extract unique file paths with their relevance scores
        step2_start = time.perf_counter()
        file_scores: dict[str, float] = {}
        for chunk in chunk_results:
            file_path = chunk.data.get("file_path", "")
            if not file_path:
                continue
            distance = chunk.distance if chunk.distance is not None else 1.0
            score = max(0.0, 1.0 - (distance / 2.0))
            # Keep best score per file
            if file_path not in file_scores or score > file_scores[file_path]:
                file_scores[file_path] = score
        step2_time = (time.perf_counter() - step2_start) * 1000

        if not file_scores:
            return []

        # Step 3: Find entities in those files using BATCHED query
        # Sort by score and take top files
        step3_start = time.perf_counter()
        top_files = sorted(file_scores.items(), key=lambda x: x[1], reverse=True)[
            :limit
        ]
        file_paths = [fp for fp, _ in top_files]

        # Use IN clause for all file paths in a single query (fixes N+1 problem)
        filter_ast = combine_filters(
            id_in_list("file_path", file_paths),
            by_type(entity_type_lower) if entity_type_lower else None,
        )

        try:
            all_entities = await db_manager.advanced_filter(
                table_name="graph_entities",
                filters=filter_ast,
                limit=limit * 10,  # Get enough entities across all files
                project_id=project_id,
            )
        except Exception as e:
            logger.debug("Failed to batch query entities: %s", e)
            all_entities = []
        step3_time = (time.perf_counter() - step3_start) * 1000

        # Log timing at INFO level for performance analysis
        if step1_time > 500 or step3_time > 500:
            logger.info(
                "Semantic bridge SLOW: step1(hybrid)=%.1fms, step2(paths)=%.1fms, step3(entities)=%.1fms, query='%s'",
                step1_time,
                step2_time,
                step3_time,
                query[:50],
            )
        else:
            logger.debug(
                "Semantic bridge timing: step1(hybrid)=%.1fms, step2(paths)=%.1fms, step3(entities)=%.1fms",
                step1_time,
                step2_time,
                step3_time,
            )

        # Calculate scores for each entity based on their file's semantic score
        entities_found = []
        for entity in all_entities:
            entity_dict = _to_entity_dict(entity)
            entity_file_path = entity_dict.get("file_path", "")
            file_semantic_score = file_scores.get(entity_file_path, 0.0)

            # Calculate entity-specific score (SG-002 fix)
            # Combine file semantic score with entity name relevance
            entity_name = entity_dict.get("name", "")
            name_similarity = _fuzzy_name_match(query, entity_name)

            # Weight: 60% file semantic score, 40% name similarity
            # This differentiates entities within the same file
            entity_score = file_semantic_score * 0.6 + name_similarity * 0.4

            entity_dict["semantic_bridge_score"] = entity_score
            entity_dict["_source"] = "semantic_bridge"
            entities_found.append(entity_dict)

        logger.debug(
            "Semantic bridge: Found %d entities from %d files (batched)",
            len(entities_found),
            len(file_scores),
        )
        return entities_found

    except Exception as e:
        logger.warning("Semantic bridge search failed: %s", e)
        return []


async def search_knowledge(
    services: dict,
    session_id: str,
    query: str,
    limit: int = 10,
    search_type: str = "hybrid",
    filters: Optional[dict] = None,
    content_type: Optional[ContentType] = None,
    preview_only: bool = False,
    include_impact: bool = False,
) -> dict:
    """Search across all indexed content in the project.

    Uses hybrid search (vector + BM25 with Reciprocal Rank Fusion) by default
    for best results. Returns ranked results with snippets and metadata.

    Args:
        services: Service dependency dict
        session_id: Session identifier
        query: Search query (natural language or keywords)
        limit: Maximum number of results to return
        search_type: Search algorithm: "hybrid" (default), "vector", or "fts"
        filters: Optional filters (file_path, language, entity_type, etc.)
        content_type: Filter to specific content type (SDD-001).
            Valid values: CODE, PROSE, TABLE, HEADING, LIST_ITEM, IMAGE_CAPTION, TITLE, OTHER.
            When specified, only results of this content type are returned.
            Leave None to search all content types.
        preview_only: If True, returns only metadata (id, path, type, score, snippet)
            without full content (SDD-001). Use fetch_content() to retrieve full text
            for selected results. Recommended for large result sets to save tokens.
        include_impact: If True, adds impact analysis for entity matches (#82).
            Shows how many files/components would be affected by changes to each
            matched entity. Useful for refactoring and code review workflows.

    Returns:
        Ranked search results with snippets and metadata.
        When preview_only=True, includes "preview": true and truncated snippets.

    Example:
        >>> # Full search with content
        >>> result = await search_knowledge(
        ...     services, "sess_123",
        ...     query="authentication implementation",
        ...     limit=5,
        ...     content_type="CODE"
        ... )
        >>> for item in result["results"]:
        ...     print(f"{item['file_path']}: {item['score']}")

        >>> # Preview mode for token efficiency
        >>> result = await search_knowledge(
        ...     services, "sess_123",
        ...     query="authentication",
        ...     limit=50,
        ...     preview_only=True  # Get metadata only
        ... )
        >>> # Then fetch full content for selected results
        >>> ids = [r["id"] for r in result["results"][:5]]
        >>> full = await fetch_content(services, session_id, ids=ids)
    """
    from agentic_inquiry.mcp.utils.validation import (
        validate_limit,
        validate_search_type,
        validate_query_length,
        create_validation_error_response,
        QueryValidationError,
    )
    from agentic_inquiry.mcp.utils.project_state import check_project_state

    session_manager = services["session_manager"]
    search_service = services["search_service"]
    event_system = services["event_system"]
    db_manager = services["storage"]
    config = services["config"]

    # Validate query length (DoS protection - S5-001)
    try:
        query = validate_query_length(query, field_name="query")
    except QueryValidationError as e:
        return create_validation_error_response(
            field="query",
            error=e,
            context={"session_id": session_id},
            provided_value=query[:100] if query else None,  # Truncate for display
            expected_type="non-empty string (max 10,000 chars)",
            example='query="how to authenticate users"',
        )

    # Validate parameters
    try:
        limit = validate_limit(limit, min_value=1, max_value=1000)
        search_type = validate_search_type(search_type)
    except ValueError as e:
        field = "limit" if "limit" in str(e) else "search_type"
        return create_validation_error_response(
            field=field,
            error=e,
            context={
                "session_id": session_id,
                "query": query,
                "limit": limit,
                "search_type": search_type,
            },
            provided_value=limit if field == "limit" else search_type,
            expected_type="integer (1-1000)" if field == "limit" else "string",
            expected_values=None if field == "limit" else ["hybrid", "vector", "fts"],
            example="limit=10" if field == "limit" else "search_type='hybrid'",
        )

    # Validate session
    if not await session_manager.validate_session(session_id):
        return await MCPErrorHandler.handle(
            error=Exception(f"Session '{session_id}' not found or expired"),
            context={"session_id": session_id},
            services=services,
        )

    # Track tool call in session history
    await session_manager.track_tool_call(
        session_id,
        "search_knowledge",
        {"query": query, "search_type": search_type, "limit": limit},
    )

    # Get session to extract project_id
    session = await session_manager.get_session(session_id, include_history=False)
    project_id = session.project_id

    # Check project state before searching
    project_state = await check_project_state(db_manager, project_id)

    # Detect index state for search response enrichment
    index_state_info = await detect_index_state(
        db_manager=db_manager,
        event_store=event_system.store,
        project_id=project_id,
        sparse_threshold=config.search.sparse_index.threshold,
    )

    # Track start
    await event_system.emit(
        "mcp.tool.started",
        source="mcp_tool",
        tool_name="search_knowledge",
        session_id=session_id,
        query=query,
        search_type=search_type,
    )

    try:
        # Start timing for performance instrumentation
        start_time = time.perf_counter()

        # Generate query embedding for vector/hybrid search
        # For server-side embedding backends (AlloyDB, RDS), pass the raw query
        # string so the database generates the embedding in the correct dimensions.
        embedding_start = time.perf_counter()
        capabilities = services.get("capabilities")
        if capabilities is None:
            # Fallback: derive capabilities from storage backend
            from agentic_inquiry.storage.capabilities import (
                get_capabilities_for_backend,
            )

            _backend = (
                db_manager.get_backend_type()
                if hasattr(db_manager, "get_backend_type")
                else "lancedb"
            )
            capabilities = get_capabilities_for_backend(_backend)

        if capabilities.uses_server_side_embedding:
            # Pass raw query text — PostgreSQL vector_search will use embedding() SQL function
            query_vector = query  # type: ignore[assignment]
            embedding_time_ms = 0.0
        else:
            embedding_service = services["embedding_service"]
            query_vector = await embedding_service.embed_async(query)
            embedding_time_ms = (time.perf_counter() - embedding_start) * 1000

        # Map entity_type filter to element_type for document_chunks
        if filters and "entity_type" in filters:
            from agentic_inquiry.models.graph_entity import EntityType

            filters = filters.copy()
            et = filters.pop("entity_type")
            filters["element_type"] = EntityType.normalize(et)

        # Apply content_type filter if specified (SDD-001)
        # This is explicit model-controlled filtering, not hidden logic
        if content_type:
            if filters is None:
                filters = {}
            else:
                filters = filters.copy()
            filters["content_type"] = content_type.upper()

        # Execute search based on type
        # query_vector is either a numpy array (.tolist()) or a raw string (server-side)
        qv = query_vector if isinstance(query_vector, str) else query_vector.tolist()
        query_start = time.perf_counter()
        if search_type == "vector":
            results = await search_service.vector_search(
                query_vector=qv, project_id=project_id, limit=limit, filters=filters
            )
        elif search_type == "fts":
            results = await search_service.fts_search(
                query_fts=query, project_id=project_id, limit=limit, filters=filters
            )
        else:  # hybrid (default)
            # Use the same code path as find_similar/build_context (no return_ambiguity)
            # to avoid the dict→SearchResult round-trip that fails on AlloyDB.
            # Ambiguity detection runs separately after results are available.
            results = await search_service.hybrid_search(
                query_vector=qv,
                query_fts=query,
                project_id=project_id,
                limit=limit,
                filters=filters,
            )
            ambiguity_info = {"ambiguous": False}

        query_time_ms = (time.perf_counter() - query_start) * 1000

        # Handle Ambiguity (Proactive Metacognition)
        clarification_request = None
        if search_type == "hybrid" and ambiguity_info.get("ambiguous"):
            clarification_request = ClarificationBuilder.build_question(
                ambiguity_info, query
            )
            logger.info("Ambiguity detected for search: %s", query)

        # Track the source of results for response
        search_source = "semantic"
        search_source_note = "Results from semantic search"

        # Check if fallback search is needed
        # Fallback is triggered when: results empty AND (status=indexing OR status=sparse)
        results_empty = len(results) == 0
        if should_use_fallback(index_state_info.status.value, results_empty):
            logger.debug(
                "Triggering fallback search: index_status=%s, results_empty=%s",
                index_state_info.status.value,
                results_empty,
            )

            # Get project root for file-based search
            project_root = Path(os.getcwd())

            # Check if this is a structural query (classes, functions, imports)
            if is_structural_query(query):
                # Use ast-grep for structural queries
                fallback_response = await structural_search(
                    query=query, project_root=project_root, limit=limit
                )
            else:
                # Use ripgrep/python_glob for text queries
                fallback_response = await execute_fallback_search(
                    query=query, project_root=project_root, limit=limit
                )

            # If fallback found results, convert them to search result format
            if fallback_response.get("results"):
                search_source = fallback_response.get("source", "fallback")
                search_source_note = fallback_response.get(
                    "source_note",
                    "Results from static text search (semantic index still building)",
                )

                # Convert FallbackResult objects to SearchResult-like format
                # Create mock results list that will be formatted below
                from agentic_inquiry.database.results import SearchResult

                fallback_results = []
                for fb_result in fallback_response["results"]:
                    # Create a SearchResult-compatible object
                    fallback_results.append(
                        SearchResult(
                            id=f"fallback_{fb_result.file_path}_{fb_result.line_number}",
                            data={
                                "file_path": fb_result.file_path,
                                "content": fb_result.content,
                                "line_start": fb_result.line_number,
                                "line_end": fb_result.line_number,
                                "language": fb_result.language,
                                "metadata": fb_result.metadata,
                            },
                            score=fb_result.score,
                            distance=None,
                        )
                    )
                results = fallback_results

                logger.debug(
                    "Fallback search returned %d results from %s",
                    len(results),
                    search_source,
                )

        # Enhanced empty result handling
        if not results:
            # Generate debug info
            debug_info = {
                "query": query,
                "project_id": project_id,
                "indexed_chunks": project_state["chunk_count"],
                "search_type": search_type,
            }

            if project_state["is_empty"]:
                # No indexed content in project
                empty_response: dict = {
                    "results": [],
                    "total": 0,
                    "query": query,
                    "search_type": search_type,
                    "source": search_source,
                    "source_note": search_source_note,
                    "debug_info": debug_info,
                    "warnings": project_state["warnings"],
                    "message": f"No indexed content found for project '{project_id}'",
                    "suggestions": [
                        "Use add_knowledge() to index files or directories",
                        "Use get_server_info() to see available projects",
                        "Verify you're using the correct project_id",
                    ],
                    "usage_hints": {
                        "next_steps": [
                            "Index content with add_knowledge(source='.')",
                            "Check available projects with get_server_info()",
                            "Get project overview with get_project_info()",
                        ],
                        "related_tools": [
                            "add_knowledge",
                            "get_server_info",
                            "get_project_info",
                        ],
                    },
                }
                # Add index state when not ready
                if index_state_info.status != IndexState.READY:
                    empty_response["index_state"] = index_state_info.to_dict()
                return empty_response
            else:
                # Content exists but no matches - provide keyword suggestions
                suggestions = [
                    "Try broader search terms",
                    "Try different keywords or synonyms",
                    "Use search_type='fts' for exact keyword matching",
                    "Check if the content you're looking for is indexed",
                ]

                # Try to get top keywords from the project to suggest alternatives
                try:
                    from agentic_inquiry.mcp.utils.keyword_extractor import (
                        KeywordExtractor,
                    )

                    keyword_extractor = KeywordExtractor()
                    top_keywords = await keyword_extractor.extract_top_keywords(
                        db_manager=db_manager, project_id=project_id, limit=10
                    )

                    if top_keywords:
                        keyword_list = ", ".join(
                            [kw["keyword"] for kw in top_keywords[:5]]
                        )
                        suggestions.insert(
                            0, f"Try keywords from indexed content: {keyword_list}"
                        )

                        logger.debug(
                            "Suggested %d keywords for no-results query: %s",
                            len(top_keywords),
                            query,
                        )
                except Exception as e:
                    logger.debug(
                        "Failed to extract keywords for no-results suggestions: %s", e
                    )

                no_match_response: dict = {
                    "results": [],
                    "total": 0,
                    "query": query,
                    "search_type": search_type,
                    "source": search_source,
                    "source_note": search_source_note,
                    "debug_info": debug_info,
                    "message": f"No results found for query '{query}' in {project_state['chunk_count']} indexed chunks",
                    "suggestions": suggestions,
                    "usage_hints": {
                        "next_steps": [
                            "Try broader query terms or suggested keywords",
                            "Use build_context() for comprehensive exploration",
                            "Check project overview with get_project_info()",
                        ],
                        "related_tools": [
                            "build_context",
                            "get_project_info",
                            "find_patterns",
                        ],
                    },
                }

                # Add warnings if project is incomplete
                if project_state["warnings"]:
                    no_match_response["warnings"] = project_state["warnings"]

                # Add index state when not ready
                if index_state_info.status != IndexState.READY:
                    no_match_response["index_state"] = index_state_info.to_dict()

                # SDD-001: Mark response as preview mode for agentic workflows
                if preview_only:
                    no_match_response["preview"] = True

                return no_match_response

        # Format results - preview mode returns minimal metadata (SDD-001)
        formatted_results = []
        for result in results:
            if preview_only:
                # Preview mode: minimal metadata, truncated snippet (SDD-001)
                # Token-efficient for large result sets
                content = result.data.get("content", "")
                preview_snippet = (
                    content[:PREVIEW_SNIPPET_LENGTH] + "..."
                    if len(content) > PREVIEW_SNIPPET_LENGTH
                    else content
                )

                # Title: prefer element_name (function/class name), then entity_name
                title = (
                    result.data.get("element_name", "")
                    or result.data.get("entity_name", "")
                    or ""
                )

                formatted_results.append(
                    {
                        "id": result.data.get("id", ""),
                        "file_path": result.data.get("file_path", ""),
                        "content_type": result.data.get("content_type", "OTHER"),
                        "line_start": result.data.get("line_start"),
                        "line_end": result.data.get("line_end"),
                        "score": result.score,
                        "title": title,
                        "preview_snippet": preview_snippet,
                    }
                )
            else:
                # Full mode: complete content and all metadata
                formatted_results.append(
                    {
                        "file_path": result.data.get("file_path", ""),
                        "content": result.data.get("content", ""),
                        "score": result.score,
                        "line_start": result.data.get("line_start"),
                        "line_end": result.data.get("line_end"),
                        "language": result.data.get("language"),
                        "entity_type": result.data.get("entity_type"),
                        "entity_name": result.data.get("entity_name"),
                        "symbols": result.data.get("symbols", []),
                        "element_name": result.data.get("element_name", ""),
                        "metadata": result.data.get("metadata", {}),
                        "content_type": result.data.get("content_type", "OTHER"),
                    }
                )

        # Enrich results with graph context (#81: Search + Graph Fusion)
        # For each result that matches a known entity, add callers/dependencies
        # so the agent gets architectural context in one query instead of needing
        # a separate understand_entity call.
        try:
            entity_resolver = services.get("entity_resolver")
            if entity_resolver and not preview_only:
                for fr in formatted_results[:5]:  # Top 5 only for performance
                    entity_name = (
                        fr.get("element_name")
                        or fr.get("entity_name")
                        # Fallback: extract from symbols list
                        or (fr.get("symbols", [None])[0] if fr.get("symbols") else None)
                    )
                    # Fallback: extract class/function name from content (language-agnostic patterns)
                    if not entity_name:
                        import re

                        content = fr.get("content", "")
                        # Matches: class X, def X, function X, func X, fn X, export class X,
                        # export function X, type X, interface X, struct X, impl X
                        m = re.search(
                            r"(?:export\s+)?(?:class|def|function|func|fn|type|interface|struct|impl|enum)\s+(\w+)",
                            content,
                        )
                        if m:
                            entity_name = m.group(1)
                    if not entity_name:
                        continue
                    try:
                        # Resolve entity name to full ID for graph lookup
                        resolved = await entity_resolver.resolve_entity(
                            entity_name=entity_name,
                            project_id=project_id,
                        )
                        resolved_id = resolved.entity_id if resolved else entity_name
                        deps = await entity_resolver.get_entity_dependencies(
                            entity_id=resolved_id,
                            project_id=project_id,
                            depth=1,
                        )
                        usages = await entity_resolver.get_entity_usages(
                            entity_id=resolved_id,
                            project_id=project_id,
                            limit=5,
                        )
                        if deps or usages:
                            fr["graph_context"] = {
                                "depends_on": [
                                    {"name": d.name, "type": d.relationship_type}
                                    for d in deps[:5]
                                ],
                                "used_by": [
                                    {
                                        "file_path": getattr(u, "file_path", ""),
                                        "line": getattr(u, "line_number", None),
                                        "type": getattr(
                                            u,
                                            "usage_type",
                                            getattr(u, "relationship_type", ""),
                                        ),
                                    }
                                    for u in usages[:5]
                                ],
                                "total_dependencies": len(deps),
                                "total_usages": len(usages),
                            }
                    except Exception:
                        pass  # Non-fatal — search works without graph enrichment
        except Exception as e:
            logger.debug("Graph enrichment skipped: %s", e)

        # Impact analysis enrichment (#82: Impact-aware search)
        if include_impact:
            try:
                impact_analyzer = services.get("impact_analyzer")
                if impact_analyzer:
                    for fr in formatted_results[:3]:  # Top 3 only
                        entity_name = (
                            fr.get("element_name")
                            or fr.get("entity_name")
                            or (
                                fr.get("symbols", [None])[0]
                                if fr.get("symbols")
                                else None
                            )
                        )
                        if not entity_name:
                            import re as _re

                            _m = _re.search(
                                r"(?:export\s+)?(?:class|def|function|func|fn|type|interface|struct|impl|enum)\s+(\w+)",
                                fr.get("content", ""),
                            )
                            entity_name = _m.group(1) if _m else None
                        if not entity_name:
                            continue
                        try:
                            impact = await impact_analyzer.analyze_impact(
                                entity_name=entity_name,
                                project_id=project_id,
                                depth=1,
                            )
                            fr["impact"] = {
                                "affected_files": len(impact.affected_files),
                                "affected_entities": len(impact.affected_entities),
                                "relationship_types": dict(impact.relationship_types)
                                if hasattr(impact, "relationship_types")
                                else {},
                                "blast_radius": "high"
                                if len(impact.affected_files) > 10
                                else "medium"
                                if len(impact.affected_files) > 3
                                else "low",
                            }
                        except Exception:
                            pass  # Non-fatal
            except Exception as e:
                logger.debug("Impact enrichment skipped: %s", e)

        # Extract related keywords from search results
        related_keywords = []
        try:
            from agentic_inquiry.mcp.utils.keyword_extractor import KeywordExtractor

            keyword_extractor = KeywordExtractor()
            related_keywords = await keyword_extractor.extract_related_keywords(
                search_results=results, limit=10
            )

            logger.debug(
                "Extracted %d related keywords from search results",
                len(related_keywords),
            )
        except Exception as e:
            logger.error("Failed to extract related keywords: %s", e, exc_info=True)
            related_keywords = []

        # Generate usage hints based on results
        usage_hints = _generate_usage_hints(formatted_results, query, related_keywords)

        # Calculate content_type_counts for agentic visibility (SDD-001)
        # This shows the model what content types exist in results
        content_type_counts: dict[str, int] = {}
        for result in results:
            ct = result.data.get("content_type", "OTHER")
            content_type_counts[ct] = content_type_counts.get(ct, 0) + 1

        # Track success
        await event_system.emit(
            "mcp.tool.completed",
            source="mcp_tool",
            tool_name="search_knowledge",
            session_id=session_id,
            count=len(formatted_results),
        )

        response: dict = {
            "results": formatted_results,
            "total": len(formatted_results),
            "query": query,
            "search_type": search_type,
            "source": search_source,
            "source_note": search_source_note,
            "content_type_counts": content_type_counts,  # SDD-001: Dynamic type visibility
            "related_keywords": related_keywords,
            "usage_hints": usage_hints,
        }

        if clarification_request:
            response["clarification_needed"] = True
            response["clarification_request"] = clarification_request
            response["ambiguity_info"] = ambiguity_info

        # SDD-001: Mark response as preview mode for agentic workflows
        if preview_only:
            response["preview"] = True

        # Add warnings if project is incomplete (even with results)
        if project_state["warnings"]:
            response["warnings"] = project_state["warnings"]

        # Add index state when not ready (indexing, sparse, or stale)
        if index_state_info.status != IndexState.READY:
            response["index_state"] = index_state_info.to_dict()

        # Build result quality indicator
        from agentic_inquiry.search.strategy import determine_search_strategy

        strategy = determine_search_strategy(
            progress_percent=index_state_info.progress_percent or 0,
            index_status=index_state_info.status.value,
        )

        result_quality = build_result_quality(
            index_status=index_state_info.status.value,
            progress_percent=index_state_info.progress_percent,
            strategy=strategy.value,
            result_count=len(formatted_results),
        )

        # Include result_quality in response when not at full quality
        # This provides clear messaging about result limitations without cluttering
        # responses when the index is fully ready
        if result_quality["level"] != "full":
            response["result_quality"] = result_quality

        # Add performance metadata
        execution_time_ms = (time.perf_counter() - start_time) * 1000
        response["meta"] = {
            "execution_time_ms": round(execution_time_ms, 2),
            "embedding_time_ms": round(embedding_time_ms, 2),
            "query_time_ms": round(query_time_ms, 2),
            "result_count": len(formatted_results),
        }

        return response

    except Exception as e:
        # Track failure
        await event_system.emit(
            "mcp.tool.failed",
            source="mcp_tool",
            tool_name="search_knowledge",
            error=str(e),
        )
        logger.error("Failed to search knowledge: %s", e, exc_info=True)
        return await MCPErrorHandler.handle(
            error=e,
            context={
                "session_id": session_id,
                "query": query,
                "search_type": search_type,
            },
            services=services,
        )


async def find_similar(
    services: dict,
    session_id: str,
    query: str,
    entity_type: Optional[str] = None,
    similarity_threshold: float = 0.3,
    limit: int = 10,
    search_scope: Optional[Literal["entities", "content", "all"]] = None,
    content_type: Optional[ContentType] = None,
    preview_only: bool = False,
    timeout_ms: Optional[int] = None,
) -> dict:
    """Find semantically similar entities or content.

    Supports multiple search scopes to find code entities (classes, functions,
    modules) or document content (chunks) that match the query semantically.

    Search Scopes:
    - "entities": Search graph_entities table for code symbols ONLY.
      Returns structural code elements (classes, functions, modules, variables).
      Uses multi-pass strategy: high confidence → medium confidence → semantic bridge → fuzzy name matching.
      Best for: "find the Config class", "locate authentication functions"
      Note: For conceptual queries like "authentication", uses semantic bridge to find
      entities in files that contain semantically related code.

    - "content": Search document_chunks table for actual code/documentation content ONLY.
      Returns relevant code snippets and documentation passages with their full text.
      Best for: "how to configure database", "examples of error handling"

    - "all" (DEFAULT): Search both entities AND content, returning unified results.
      Returns both structural elements and content chunks.
      Best for: comprehensive searches that need both symbol definitions and usage examples.

    Important Behavioral Notes:
    - search_scope="entities" will NOT return document chunks or code content
    - search_scope="content" will NOT return code symbols (classes, functions, etc.)
    - For cross-content-type searches (find both symbols and their usage), use search_scope="all"
    - For broad semantic exploration, consider using search_knowledge() or build_context() instead
    - For conceptual queries (e.g., "authentication") that don't match entity names directly,
      the semantic bridge strategy finds entities in semantically related code files.

    Args:
        services: Service dependency dict
        session_id: Session identifier
        query: Text query or entity name to find similar items for
        entity_type: Optional filter by entity type ("class", "function", "module", etc.)
            Only applies when search_scope includes entities.
        similarity_threshold: Minimum acceptable similarity (0.0-1.0, default 0.3).
            Lower values (0.2-0.4) are better for conceptual queries.
            Higher values (0.5-0.8) are better for exact entity name matching.
        limit: Maximum number of results to return
        search_scope: What to search - "entities", "content", or "all" (default).
            If not provided, defaults to "all" (both entities and content).
        content_type: Filter content results to specific type (SDD-001).
            Valid values: CODE, PROSE, TABLE, HEADING, LIST_ITEM, IMAGE_CAPTION, TITLE, OTHER.
            Only applies when search_scope includes content ("content" or "all").
            Leave None to search all content types.
        preview_only: If True, returns only metadata (id, path, type, score, snippet)
            without full content (SDD-001). Use fetch_content() to retrieve full text
            for selected results. Recommended for large result sets to save tokens.
            Only applies to content results (entities already return minimal data).
        timeout_ms: Optional timeout in milliseconds for entity search operations.
            If None (default), uses config-based timeouts:
            - limit <= 10: 500ms
            - limit <= 50: 1000ms
            - limit > 50: 2000ms
            Set to 0 to disable timeout. Use higher values for thorough searches.

    Returns:
        Dictionary containing:
        - similar_entities: List of matching entities (when scope includes entities)
        - similar_content: List of matching content chunks (when scope includes content)
        - total: Total count of results
        - match_summary: Breakdown of match quality levels
        - recommendations: Suggestions for refining the search
        - preview: True when preview_only=True (SDD-001)
        - content_type_counts: Distribution of content types in results (SDD-001)

    Example:
        >>> # Search for code entities
        >>> result = await find_similar(
        ...     services, "sess_123",
        ...     query="authentication handler",
        ...     entity_type="class",
        ...     search_scope="entities"
        ... )
        >>> for entity in result["similar_entities"]:
        ...     print(f"{entity['name']}: {entity['similarity']:.2f}")

        >>> # Search for content (code snippets, documentation)
        >>> result = await find_similar(
        ...     services, "sess_123",
        ...     query="how to configure database connections",
        ...     search_scope="content"
        ... )
        >>> for chunk in result["similar_content"]:
        ...     print(f"{chunk['file_path']}: {chunk['similarity']:.2f}")

        >>> # Search both entities and content
        >>> result = await find_similar(
        ...     services, "sess_123",
        ...     query="caching implementation",
        ...     search_scope="all"
        ... )
    """
    from agentic_inquiry.mcp.utils.validation import (
        validate_limit,
        validate_query_length,
        create_validation_error_response,
        QueryValidationError,
    )

    session_manager = services["session_manager"]
    embedding_service = services["embedding_service"]
    event_system = services["event_system"]
    db_manager = services["storage"]
    config = services["config"]
    search_service = services.get("search_service")  # For semantic bridge

    # Initialize pass_timings for entity search timing debug info
    pass_timings: list[tuple[str, float]] = []

    # Validate query length (DoS protection - S5-001)
    try:
        query = validate_query_length(query, field_name="query")
    except QueryValidationError as e:
        return create_validation_error_response(
            field="query",
            error=e,
            context={"session_id": session_id},
            provided_value=query[:100] if query else None,  # Truncate for display
            expected_type="non-empty string (max 10,000 chars)",
            example='query="authentication handler"',
        )

    # Validate parameters
    try:
        limit = validate_limit(limit, min_value=1, max_value=100)
    except ValueError as e:
        return create_validation_error_response(
            field="limit",
            error=e,
            context={"session_id": session_id, "query": query},
            provided_value=limit,
            expected_type="integer (1-100)",
            example="limit=10",
        )

    # Validate similarity threshold
    if not 0.0 <= similarity_threshold <= 1.0:
        return create_validation_error_response(
            field="similarity_threshold",
            error=ValueError("similarity_threshold must be between 0.0 and 1.0"),
            context={"session_id": session_id, "query": query},
            provided_value=similarity_threshold,
            expected_type="float (0.0-1.0)",
            example="similarity_threshold=0.7",
        )

    # Validate search_scope (default to "entities" if not provided)
    valid_scopes = {"entities", "content", "all"}
    effective_scope: str = "all"
    if search_scope is not None:
        effective_scope = search_scope.lower()
    if effective_scope not in valid_scopes:
        return create_validation_error_response(
            field="search_scope",
            error=ValueError(f"search_scope must be one of: {', '.join(valid_scopes)}"),
            context={"session_id": session_id, "query": query},
            provided_value=search_scope,
            expected_type=f"string ({', '.join(valid_scopes)})",
            example='search_scope="content"',
        )

    # Determine what to search
    search_entities = effective_scope in {"entities", "all"}
    search_content = effective_scope in {"content", "all"}

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

    # Detect index state for response enrichment
    index_state_info = await detect_index_state(
        db_manager=db_manager,
        event_store=event_system.store,
        project_id=project_id,
        sparse_threshold=config.search.sparse_index.threshold,
    )

    # Track start
    await event_system.emit(
        "mcp.tool.started",
        source="mcp_tool",
        tool_name="find_similar",
        session_id=session_id,
        query=query,
        entity_type=entity_type,
        search_scope=effective_scope,
    )

    try:
        # Start timing for performance instrumentation
        start_time = time.perf_counter()

        # Generate query embedding
        # For server-side embedding backends, pass raw query text
        embedding_start = time.perf_counter()
        capabilities_fs = services.get("capabilities")
        if capabilities_fs is None:
            from agentic_inquiry.storage.capabilities import (
                get_capabilities_for_backend,
            )

            _backend_fs = (
                db_manager.get_backend_type()
                if hasattr(db_manager, "get_backend_type")
                else "lancedb"
            )
            capabilities_fs = get_capabilities_for_backend(_backend_fs)

        if capabilities_fs.uses_server_side_embedding:
            query_vector = query  # type: ignore[assignment]
            embedding_time_ms = 0.0
        else:
            query_vector = await embedding_service.embed_async(query)
            embedding_time_ms = (time.perf_counter() - embedding_start) * 1000

        # Start query timing (covers all search passes)
        query_start = time.perf_counter()

        # Normalize entity type
        from agentic_inquiry.models.graph_entity import EntityType

        entity_type_lower = EntityType.normalize(entity_type) if entity_type else None

        # Initialize result containers
        similar_entities: list[dict] = []
        similar_content: list[dict] = []
        seen_names: set[str] = set()
        seen_chunk_ids: set[str] = set()
        match_summary = {
            "high": 0,
            "medium": 0,
            "semantic": 0,
            "fuzzy": 0,
            "content": 0,
        }

        # Check if entity search is supported (for PostgreSQL and LanceDB backends)
        has_entity_search = hasattr(db_manager, "entity_vector_search")

        # Helper to format an entity result
        def format_entity(
            result: dict,
            combined_sim: float,
            vector_sim: float,
            name_sim: float,
            match_quality: str,
        ) -> dict:
            entity_type = result.get("type", "")
            return {
                "name": result.get("name", ""),
                "type": entity_type,
                "file_path": result.get("file_path", ""),
                "line_start": result.get("line_start"),
                "line_end": result.get("line_end"),
                "similarity": round(combined_sim, 4),
                "vector_similarity": round(vector_sim, 4),
                "name_similarity": round(name_sim, 4),
                "match_quality": match_quality,
                "confidence": _classify_confidence(combined_sim),  # ISS-W2-017
                "is_code_entity": entity_type in CODE_ENTITY_TYPES,  # ISS-W2-010/015
                "parent": result.get("parent_name", ""),
                "docstring": result.get("docstring", "")[:200]
                if result.get("docstring")
                else None,
            }

        # Helper to run vector search at a given threshold
        async def vector_search_pass(
            min_threshold: float,
            max_threshold: Optional[float] = None,
            search_limit: int = 50,
        ) -> list[dict]:
            """Run vector search and return results within threshold range.

            Uses backend-agnostic entity_vector_search method that works
            with both LanceDB and PostgreSQL backends.
            """
            if not has_entity_search:
                return []

            try:
                # Use the backend-agnostic entity_vector_search method
                # This works for both LanceDB (via StorageFacade) and PostgreSQL
                raw_results = await db_manager.entity_vector_search(
                    query_vector=query_vector
                    if isinstance(query_vector, str)
                    else query_vector.tolist(),
                    limit=search_limit,
                    entity_type=entity_type_lower,
                    project_id=project_id,
                )
            except Exception as e:
                logger.warning("Vector search pass failed: %s", e)
                return []

            pass_results = []
            for result in raw_results:
                result_dict = _to_entity_dict(result)
                entity_name = result_dict.get("name", "")
                if entity_name in seen_names:
                    continue

                # Calculate similarity scores
                distance = result_dict.get("_distance", 1.0)
                vector_sim = max(0.0, 1.0 - (distance / 2.0))
                name_sim = _fuzzy_name_match(query, entity_name)

                # Combined score with adaptive weighting
                if vector_sim >= 0.4:
                    combined_sim = vector_sim * 0.7 + name_sim * 0.3
                else:
                    combined_sim = vector_sim * 0.4 + name_sim * 0.6

                # Check threshold range
                if combined_sim < min_threshold:
                    continue
                if max_threshold is not None and combined_sim >= max_threshold:
                    continue

                match_quality = _determine_match_quality(combined_sim)
                pass_results.append(
                    format_entity(
                        result_dict, combined_sim, vector_sim, name_sim, match_quality
                    )
                )
                seen_names.add(entity_name)

            return pass_results

        # ==========================================
        # ENTITY SEARCH PASSES (only if search_entities is True)
        # ==========================================
        if search_entities:
            # Time budget for entity search (SG-PERF-002)
            # Use timeout_ms parameter if provided, otherwise get from config
            graph_timeouts = config.search.graph_search.timeouts
            if timeout_ms is not None:
                # timeout_ms=0 means no timeout, use a very large value
                time_budget_ms = timeout_ms if timeout_ms > 0 else 999999
            else:
                time_budget_ms = graph_timeouts.get_find_similar_timeout(limit)
            entity_search_start = time.perf_counter()

            def within_time_budget() -> bool:
                elapsed_ms = (time.perf_counter() - entity_search_start) * 1000
                return elapsed_ms < time_budget_ms

            def log_pass_timing(pass_name: str) -> None:
                elapsed_ms = (time.perf_counter() - entity_search_start) * 1000
                pass_timings.append((pass_name, round(elapsed_ms, 1)))
                logger.debug(
                    "Entity search %s completed, elapsed=%.1fms, budget=%.0fms",
                    pass_name,
                    elapsed_ms,
                    time_budget_ms,
                )

            # ==========================================
            # PASS 1: High confidence (uses user-provided similarity_threshold)
            # ==========================================
            high_results = await vector_search_pass(
                min_threshold=similarity_threshold, search_limit=limit * 2
            )
            similar_entities.extend(high_results)
            match_summary["high"] = len(high_results)
            log_pass_timing("PASS1(high)")

            # ==========================================
            # PASS 2: Medium confidence (0.35 <= threshold < similarity_threshold)
            # Only if we need more results, threshold allows it, and within time budget
            # ==========================================
            if (
                len(similar_entities) < limit
                and similarity_threshold > THRESHOLD_MEDIUM
                and within_time_budget()
            ):
                medium_results = await vector_search_pass(
                    min_threshold=THRESHOLD_MEDIUM,
                    max_threshold=similarity_threshold,
                    search_limit=limit * 2,
                )
                # Only take what we need
                slots_remaining = limit - len(similar_entities)
                similar_entities.extend(medium_results[:slots_remaining])
                match_summary["medium"] = min(len(medium_results), slots_remaining)
                log_pass_timing("PASS2(medium)")

            # ==========================================
            # PASS 2.5: Semantic Bridge (search chunks, find entities)
            # Uses semantic search on code chunks to find related entities
            # Only if we still need results, search_service is available, and within time budget
            # ==========================================
            if (
                len(similar_entities) < limit
                and search_service is not None
                and within_time_budget()
            ):
                log_pass_timing("PASS2.5 starting")
                try:
                    # Calculate remaining time budget for semantic bridge (SG-PERF-003)
                    elapsed_ms = (time.perf_counter() - entity_search_start) * 1000
                    remaining_budget_ms = max(100, time_budget_ms - elapsed_ms)
                    timeout_seconds = remaining_budget_ms / 1000.0

                    # Use asyncio.wait_for to enforce timeout on semantic bridge
                    semantic_entities = await asyncio.wait_for(
                        _entities_from_semantic_search(
                            db_manager=db_manager,
                            embedding_service=embedding_service,
                            search_service=search_service,
                            query=query,
                            project_id=project_id,
                            entity_type_lower=entity_type_lower,
                            limit=limit * 2,
                            query_vector=query_vector,  # Reuse pre-computed embedding
                        ),
                        timeout=timeout_seconds,
                    )

                    semantic_results = []
                    for entity in semantic_entities:
                        entity_name = entity.get("name", "")
                        if entity_name in seen_names:
                            continue

                        # Use semantic bridge score as primary similarity
                        semantic_score = entity.get("semantic_bridge_score", 0.3)
                        name_sim = _fuzzy_name_match(query, entity_name)

                        # Combined score weighted toward semantic
                        combined_sim = semantic_score * 0.7 + name_sim * 0.3

                        if combined_sim >= THRESHOLD_LOW:
                            seen_names.add(entity_name)
                            semantic_results.append(
                                format_entity(
                                    entity,
                                    combined_sim,
                                    semantic_score,
                                    name_sim,
                                    "semantic",
                                )
                            )

                            if len(semantic_results) >= limit - len(similar_entities):
                                break

                    similar_entities.extend(semantic_results)
                    match_summary["semantic"] = len(semantic_results)
                    log_pass_timing("PASS2.5(semantic) done")
                    logger.debug(
                        "Semantic bridge added %d entities for query '%s'",
                        len(semantic_results),
                        query,
                    )

                except asyncio.TimeoutError:
                    log_pass_timing("PASS2.5 TIMEOUT")
                    logger.debug(
                        "Semantic bridge timed out after %.1fms for query '%s'",
                        remaining_budget_ms,
                        query,
                    )
                    match_summary["semantic"] = 0
                except Exception as e:
                    log_pass_timing("PASS2.5 FAILED")
                    logger.debug("Semantic bridge pass failed: %s", e)
                    match_summary["semantic"] = 0
            else:
                log_pass_timing("PASS2.5 SKIPPED (over budget or no search_service)")

            # ==========================================
            # PASS 3: Fuzzy name matching fallback
            # Only if still sparse (< half the limit) and within time budget
            # ==========================================
            if len(similar_entities) < limit // 2 and within_time_budget():
                try:
                    # Build Filter AST for optional type filter
                    fuzzy_filter_ast = (
                        by_type(entity_type_lower) if entity_type_lower else None
                    )

                    all_entities = await db_manager.advanced_filter(
                        table_name="graph_entities",
                        filters=fuzzy_filter_ast,
                        limit=500,
                        project_id=project_id,
                    )

                    fuzzy_results = []
                    for entity in all_entities:
                        entity_name = entity.get("name", "")
                        if entity_name in seen_names:
                            continue

                        name_sim = _fuzzy_name_match(query, entity_name)
                        # Use the user's threshold as minimum for fuzzy
                        min_fuzzy_threshold = max(similarity_threshold, THRESHOLD_LOW)
                        if name_sim >= min_fuzzy_threshold:
                            seen_names.add(entity_name)
                            fuzzy_results.append(
                                format_entity(entity, name_sim, 0.0, name_sim, "fuzzy")
                            )

                            if len(fuzzy_results) >= limit - len(similar_entities):
                                break

                    similar_entities.extend(fuzzy_results)
                    match_summary["fuzzy"] = len(fuzzy_results)
                    log_pass_timing("PASS3(fuzzy) done")

                except Exception as e:
                    logger.debug("Fuzzy name fallback failed: %s", e)

            # ==========================================
            # PASS 4: Direct name match fallback (no embeddings needed)
            # When all vector passes return 0, try exact/prefix name matching
            # via list_entities. This handles the case where entity embeddings
            # haven't been generated yet (server-side embedding race condition).
            # ==========================================
            if len(similar_entities) == 0 and within_time_budget():
                try:
                    from agentic_inquiry.mcp.tools.info import list_entities

                    name_results = await list_entities(
                        services=services,
                        session_id=session_id,
                        entity_type=entity_type if entity_type else None,
                        pattern=query,
                        limit=limit,
                    )
                    for entity in name_results.get("entities", []):
                        entity_name = entity.get("name", "")
                        if entity_name in seen_names:
                            continue
                        name_sim = _fuzzy_name_match(query, entity_name)
                        if name_sim >= 0.2:
                            seen_names.add(entity_name)
                            similar_entities.append(
                                format_entity(
                                    entity, name_sim, 0.0, name_sim, "name_fallback"
                                )
                            )
                    match_summary["name_fallback"] = len(similar_entities)
                    log_pass_timing("PASS4(name_fallback)")
                except Exception as e:
                    logger.debug("Name fallback failed: %s", e)

            # Log final entity search timing
            log_pass_timing("ENTITY_SEARCH_COMPLETE")

        # ==========================================
        # CONTENT SEARCH: Search document_chunks
        # Only if search_scope includes content
        # ==========================================
        if search_content and search_service is not None:
            try:
                # Build filters for content search (SDD-001)
                content_filters: Optional[dict] = None
                if content_type:
                    content_filters = {"content_type": content_type.upper()}

                # Use hybrid search to find relevant content chunks
                chunk_results = await search_service.hybrid_search(
                    query_vector=query_vector
                    if isinstance(query_vector, str)
                    else query_vector.tolist(),
                    query_fts=query,
                    project_id=project_id,
                    limit=limit * 2,  # Get more to filter by threshold
                    filters=content_filters,  # SDD-001: Apply content_type filter
                    boost_overview=False,
                )

                content_results = []
                logger.debug(
                    "find_similar content search returned %d chunks (threshold=%.2f)",
                    len(chunk_results),
                    similarity_threshold,
                )
                for chunk in chunk_results:
                    chunk_id = chunk.id
                    if chunk_id in seen_chunk_ids:
                        continue

                    # Use the already-normalized score from SearchResult
                    # SearchResult.score is normalized to 0.0-1.0 at adapter boundaries
                    similarity = chunk.score
                    logger.debug(
                        "Content chunk %s score=%.4f (threshold=%.2f)",
                        chunk.data.get("file_path", "?")[:50],
                        similarity,
                        similarity_threshold,
                    )

                    if similarity < similarity_threshold:
                        continue

                    seen_chunk_ids.add(chunk_id)

                    # Format content result - preview mode returns minimal metadata (SDD-001)
                    if preview_only:
                        # Preview mode: minimal metadata, truncated snippet
                        content = chunk.data.get("content", "")
                        preview_snippet = (
                            content[:PREVIEW_SNIPPET_LENGTH] + "..."
                            if len(content) > PREVIEW_SNIPPET_LENGTH
                            else content
                        )

                        # Title: prefer element_name (function/class name), then entity_name
                        title = (
                            chunk.data.get("element_name", "")
                            or chunk.data.get("entity_name", "")
                            or ""
                        )

                        content_results.append(
                            {
                                "id": chunk_id,
                                "file_path": chunk.data.get("file_path", ""),
                                "content_type": chunk.data.get("content_type", "OTHER"),
                                "line_start": chunk.data.get("line_start"),
                                "line_end": chunk.data.get("line_end"),
                                "similarity": round(similarity, 4),
                                "title": title,
                                "preview_snippet": preview_snippet,
                            }
                        )
                    else:
                        # Full mode: complete content and all metadata
                        content_results.append(
                            {
                                "id": chunk_id,  # Use canonical 'id' field
                                "file_path": chunk.data.get("file_path", ""),
                                "content": chunk.data.get("content", "")[
                                    :500
                                ],  # Truncate for response
                                "content_type": chunk.data.get("content_type", ""),
                                "chunk_type": chunk.data.get("chunk_type", ""),
                                "similarity": round(similarity, 4),
                                "line_start": chunk.data.get("line_start"),
                                "line_end": chunk.data.get("line_end"),
                                "match_quality": _determine_match_quality(similarity),
                                "confidence": _classify_confidence(
                                    similarity
                                ),  # ISS-W2-017
                                "metadata": _extract_metadata_fields(
                                    chunk.data.get("metadata", {}),
                                    {
                                        "language",
                                        "symbols",
                                        "heading_level",
                                        "section_title",
                                    },
                                ),
                            }
                        )

                    if len(content_results) >= limit:
                        break

                similar_content.extend(content_results)
                match_summary["content"] = len(content_results)

                logger.debug(
                    "Content search found %d chunks for query '%s'",
                    len(content_results),
                    query,
                )

            except Exception as e:
                logger.warning("Content search failed: %s", e, exc_info=True)
                match_summary["content"] = 0

        # End query timing
        query_time_ms = (time.perf_counter() - query_start) * 1000

        # ISS-W2-010/015: Prioritize code entities when search_scope="entities"
        # Code entities (classes, functions, methods) are sorted before documentation entities
        # at the same similarity level. This ensures code queries return code results first.
        def entity_sort_key(entity: dict) -> tuple:
            """Sort key: (is_code_entity descending, similarity descending)."""
            # is_code_entity: True (1) should come before False (0), so negate
            is_code = 1 if entity.get("is_code_entity", False) else 0
            similarity = entity.get("similarity", 0.0)
            return (-is_code, -similarity)

        # Apply prioritization only for entity-focused searches
        if effective_scope == "entities":
            similar_entities.sort(key=entity_sort_key)
        else:
            # For "all" scope, just sort by similarity (highest first)
            similar_entities.sort(key=lambda x: x["similarity"], reverse=True)

        # P1-1 Fix: Filter by user's similarity_threshold before limiting
        # Passes 2/2.5/3 may add results below threshold - remove them here
        similar_entities = [
            e for e in similar_entities if e["similarity"] >= similarity_threshold
        ]

        # ISS-002 Fix: Apply diversity filter for entities to prevent
        # all results coming from the same file with identical scores
        if similar_entities and effective_scope == "entities":
            # Get max_per_file from config with default of 2 for entity diversity
            # Note: Default config value is 1 (for search_knowledge), but entity
            # search benefits from 2 to show more variety per file
            max_per_file = getattr(
                getattr(config.search, "deduplication", None), "max_results_per_file", 2
            )
            # Use at least 2 for entity diversity unless explicitly configured lower
            if max_per_file < 2:
                max_per_file = 2
            similar_entities = diversify_entity_results(
                entities=similar_entities, limit=limit, max_per_file=max_per_file
            )

        # Trim to limit
        similar_entities = similar_entities[:limit]

        # Sort content results by similarity
        similar_content.sort(key=lambda x: x["similarity"], reverse=True)

        # Trim content to limit
        similar_content = similar_content[:limit]

        # Calculate total results
        total_results = len(similar_entities) + len(similar_content)

        # Calculate content_type_counts for agentic visibility (SDD-001)
        # This shows the model what content types exist in results
        content_type_counts: dict[str, int] = {}
        for content_item in similar_content:
            ct = content_item.get("content_type", "OTHER")
            content_type_counts[ct] = content_type_counts.get(ct, 0) + 1

        # Track success
        await event_system.emit(
            "mcp.tool.completed",
            source="mcp_tool",
            tool_name="find_similar",
            session_id=session_id,
            count=total_results,
            search_scope=effective_scope,
        )

        # Generate recommendations
        recommendations = _generate_similar_recommendations(
            query=query,
            results=similar_entities,
            match_summary=match_summary,
            entity_type=entity_type,
        )

        # Build response based on search_scope
        response: dict = {
            "query": query,
            "search_scope": effective_scope,
            "similarity_threshold": similarity_threshold,
            "match_summary": match_summary,
            "content_type_counts": content_type_counts,  # SDD-001: Dynamic type visibility
        }

        # SDD-001: Mark response as preview mode for agentic workflows
        if preview_only:
            response["preview"] = True

        # Include entities if searched
        if search_entities:
            response["similar_entities"] = similar_entities
            response["entity_count"] = len(similar_entities)

        # Include content if searched
        if search_content:
            response["similar_content"] = similar_content
            response["content_count"] = len(similar_content)

        response["total"] = total_results

        if entity_type and search_entities:
            response["filtered_by_type"] = entity_type

        if recommendations:
            response["recommendations"] = recommendations

        # Add helpful message if no results
        if total_results == 0:
            if effective_scope == "entities":
                response["message"] = f"No entities found matching '{query}'"
            elif effective_scope == "content":
                response["message"] = f"No content found matching '{query}'"
            else:
                response["message"] = f"No entities or content found matching '{query}'"
            response["recommendations"] = {
                "related_tools": [
                    "add_knowledge(source='.') - Index more content",
                    "get_project_info() - Check what's indexed",
                    "Try broader search terms or lower similarity_threshold",
                ]
            }

        # Add index state when not ready (indexing, sparse, or stale)
        if index_state_info.status != IndexState.READY:
            response["index_state"] = index_state_info.to_dict()

        # Add performance metadata
        execution_time_ms = (time.perf_counter() - start_time) * 1000
        meta_dict: dict = {
            "execution_time_ms": round(execution_time_ms, 2),
            "embedding_time_ms": round(embedding_time_ms, 2),
            "query_time_ms": round(query_time_ms, 2),
            "result_count": total_results,
        }
        # Add pass timing debug info if entity search ran
        if pass_timings:
            meta_dict["pass_timings"] = pass_timings
        response["meta"] = meta_dict

        return response

    except Exception as e:
        # Track failure
        await event_system.emit(
            "mcp.tool.failed", source="mcp_tool", tool_name="find_similar", error=str(e)
        )
        logger.error("Failed to find similar entities: %s", e, exc_info=True)
        return await MCPErrorHandler.handle(
            error=e,
            context={
                "session_id": session_id,
                "query": query,
                "entity_type": entity_type,
            },
            services=services,
        )


async def fetch_content(services: dict, session_id: str, ids: List[str]) -> dict:
    """Fetch full content for specific chunk IDs (SDD-001).

    Use this after search_knowledge(preview_only=True) or find_similar(preview_only=True)
    to retrieve full content for selected results. This enables token-efficient
    agentic workflows where the model first previews results, then selectively
    fetches only the content it needs.

    Args:
        services: Service dependency dict
        session_id: Session identifier
        ids: List of chunk IDs from preview results (max 20)

    Returns:
        Dictionary containing:
        - results: List of full content for requested chunks
        - found: Number of chunks successfully retrieved
        - not_found: List of IDs that weren't found

    Example:
        >>> # Step 1: Preview search
        >>> preview = await search_knowledge(
        ...     services, "sess_123",
        ...     query="authentication",
        ...     preview_only=True
        ... )
        >>> # Step 2: Select relevant IDs from preview
        >>> relevant_ids = [r["id"] for r in preview["results"][:3]]
        >>> # Step 3: Fetch full content
        >>> content = await fetch_content(
        ...     services, "sess_123",
        ...     ids=relevant_ids
        ... )
        >>> for item in content["results"]:
        ...     print(f"{item['file_path']}: {len(item['content'])} chars")
    """
    from lancedb.query import eq

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

    if len(ids) > 20:
        return {
            "status": "failed",
            "error": "Maximum 20 IDs per request. For larger batches, make multiple calls.",
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
        tool_name="fetch_content",
        session_id=session_id,
        id_count=len(ids),
    )

    try:
        results: list[dict] = []
        not_found: list[str] = []

        # Fetch each chunk from document_chunks table
        for chunk_id in ids:
            try:
                chunk_results = await db_manager.advanced_filter(
                    table_name="document_chunks",
                    filters=eq("id", chunk_id),
                    limit=1,
                    project_id=project_id,
                )

                if chunk_results:
                    chunk = chunk_results[0]
                    results.append(
                        {
                            "id": chunk_id,
                            "file_path": chunk.get("file_path", ""),
                            "content": chunk.get("content", ""),
                            "content_type": chunk.get("content_type", "OTHER"),
                            "line_start": chunk.get("line_start"),
                            "line_end": chunk.get("line_end"),
                            "language": chunk.get("language", ""),
                            "symbols": chunk.get("symbols", []),
                            "element_name": chunk.get("element_name", ""),
                            "entity_name": chunk.get("entity_name", ""),
                            "metadata": chunk.get("metadata", {}),
                        }
                    )
                else:
                    not_found.append(chunk_id)

            except Exception as e:
                logger.debug("Failed to fetch chunk %s: %s", chunk_id, e)
                not_found.append(chunk_id)

        # Track success
        await event_system.emit(
            "mcp.tool.completed",
            source="mcp_tool",
            tool_name="fetch_content",
            session_id=session_id,
            found=len(results),
            not_found=len(not_found),
        )

        return {
            "results": results,
            "found": len(results),
            "not_found": not_found,  # Always return list for consistent typing
            "requested": len(ids),
        }

    except Exception as e:
        # Track failure
        await event_system.emit(
            "mcp.tool.failed",
            source="mcp_tool",
            tool_name="fetch_content",
            error=str(e),
        )
        logger.error("Failed to fetch content: %s", e, exc_info=True)
        return await MCPErrorHandler.handle(
            error=e, context={"session_id": session_id, "ids": ids}, services=services
        )


__all__ = [
    "search_knowledge",
    "find_similar",
    "fetch_content",
    "build_result_quality",
    "ContentType",
]
