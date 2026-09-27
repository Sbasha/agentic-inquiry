"""Project state checking utilities for MCP tools.

This module provides utilities for checking project state and generating
helpful warnings when projects have no or minimal indexed data.
"""

import logging

logger = logging.getLogger(__name__)


async def check_project_state(
    db_manager, project_id: str, chunk_threshold: int = 10
) -> dict:
    """Check project state and return warnings if needed.

    Checks the project's chunk and entity counts and generates warnings
    for empty (0 chunks) or incomplete (< threshold chunks) projects.

    Args:
        db_manager: LanceDB manager instance
        project_id: Project identifier
        chunk_threshold: Minimum chunks for complete project (default: 10)

    Returns:
        Dictionary with:
            - project_id: Project identifier
            - chunk_count: Number of indexed chunks
            - entity_count: Number of extracted entities
            - warnings: List of warning messages (empty if no warnings)
            - is_empty: True if project has no indexed content
            - is_incomplete: True if project has minimal content

    Example:
        >>> state = await check_project_state(db_manager, "my_project")
        >>> if state["warnings"]:
        ...     for warning in state["warnings"]:
        ...         print(f"Warning: {warning}")
    """
    try:
        # Get chunk and entity counts
        chunk_count = await db_manager.count_records(
            table_name="document_chunks", project_id=project_id
        )

        entity_count = await db_manager.count_records(
            table_name="graph_entities", project_id=project_id
        )

        logger.debug(
            "Project state for %s: chunks=%d, entities=%d",
            project_id,
            chunk_count,
            entity_count,
        )

    except Exception as e:
        logger.warning(
            "Failed to get project state for %s: %s — skipping state check",
            project_id,
            e,
        )
        # On connection error, assume data may exist rather than blocking tools
        # Returning -1 signals "unknown" so callers don't treat it as empty
        chunk_count = -1
        entity_count = -1

    # Generate warnings based on state
    warnings = []
    is_empty = chunk_count == 0
    is_incomplete = 0 < chunk_count < chunk_threshold

    if is_empty:
        warnings.append(
            "Project has no indexed content. "
            "Use add_knowledge() to index files before searching."
        )
    elif is_incomplete:
        warnings.append(
            f"Project has only {chunk_count} chunks. "
            "Consider indexing more content for better results."
        )

    return {
        "project_id": project_id,
        "chunk_count": chunk_count,
        "entity_count": entity_count,
        "warnings": warnings,
        "is_empty": is_empty,
        "is_incomplete": is_incomplete,
    }


__all__ = ["check_project_state"]
