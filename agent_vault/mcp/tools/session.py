"""Session management tools for MCP server.

These tools provide session lifecycle management for AI agent workflows:
- Creating new work sessions
- Retrieving session details
- Listing sessions with filters
- Resuming previous sessions
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


async def create_session(
    services: dict,
    project_id: str,
    description: Optional[str] = None
) -> dict:
    """Create a new work session for a project.

    Returns session ID, project statistics (indexed files, entities, memories),
    and guidance on next steps based on whether the project is indexed.

    Args:
        services: Service dependency dict
        project_id: Project identifier
        description: Optional session description

    Returns:
        Session metadata with statistics and guidance

    Example:
        >>> result = await create_session(services, "my_project", "Feature work")
        >>> session_id = result["session_id"]
        >>> print(result["guidance"]["next_steps"])
    """
    from agent_vault.mcp.utils.validation import validate_project_id, ProjectIDValidationError
    
    session_manager = services["session_manager"]
    event_system = services["event_system"]
    server_config = services.get("server_config", {})

    # Validate project_id format
    try:
        validated_project_id = validate_project_id(project_id, normalize=True)
        
        # Warn if normalized (changed)
        if validated_project_id != project_id:
            logger.warning(
                "Project ID normalized from '%s' to '%s'",
                project_id,
                validated_project_id
            )
        
        project_id = validated_project_id
        
    except ProjectIDValidationError as e:
        # Return validation error with helpful message
        logger.error("Project ID validation failed: %s", e)
        return {
            "error": str(e),
            "error_code": "INVALID_PROJECT_ID",
            "suggestion": "Use get_server_info() to see project_id format requirements and available projects",
            "examples": ["my-project", "project_123", "my_project"]
        }

    # Track start
    await event_system.emit(
        "mcp.tool.started",
        source="mcp_tool",
        tool_name="create_session",
        project_id=project_id
    )

    # Check for mismatch with server default
    default_project = server_config.get("default_project_id")
    if default_project and project_id != default_project:
        logger.info(
            "Creating session for project '%s' (server default is '%s')",
            project_id,
            default_project
        )

    try:
        result = await session_manager.create_session(
            project_id=project_id,
            description=description
        )

        # Add warning if project differs from default
        if default_project and project_id != default_project:
            result["warning"] = {
                "message": f"Using project '{project_id}' (server default is '{default_project}')",
                "suggestion": "Use get_server_info() to see all available projects"
            }

        # Track success
        await event_system.emit(
        "mcp.tool.completed",
        source="mcp_tool",
            tool_name="create_session",
            session_id=result["session_id"]
        )

        return result

    except Exception as e:
        # Track failure
        await event_system.emit(
        "mcp.tool.failed",
        source="mcp_tool",
            tool_name="create_session",
            error=str(e)
        )
        logger.error("Failed to create session: %s", e, exc_info=True)
        return {
            "error": str(e),
            "suggestion": "Ensure project_id is valid and database is accessible. Use get_server_info() to discover available projects."
        }


async def get_session(
    services: dict,
    session_id: str,
    include_history: bool = True
) -> dict:
    """Retrieve details about a session.

    Returns session metadata, status, activity log, and optionally full
    tool call history.

    Args:
        services: Service dependency dict
        session_id: Session identifier
        include_history: Whether to include full tool call history

    Returns:
        Session details with optional history

    Example:
        >>> result = await get_session(services, "sess_123")
        >>> print(result["status"])  # active, inactive, expired
        >>> print(result["activity_log"])  # Recent operations
    """
    session_manager = services["session_manager"]

    # Validate session
    if not await session_manager.validate_session(session_id):
        return {
            "error": f"Session '{session_id}' not found or expired",
            "suggestion": "Use list_sessions to find valid sessions or create a new one"
        }

    # Track tool call in session history
    await session_manager.track_tool_call(
        session_id, "get_session", {"include_history": include_history}
    )

    try:
        session = await session_manager.get_session(
            session_id=session_id,
            include_history=include_history
        )

        return {
            "session_id": session.session_id,
            "project_id": session.project_id,
            "status": session.status,
            "description": session.description,
            "created_at": session.created_at.isoformat(),
            "last_active": session.last_active.isoformat(),
            "activity_log": session.activity_log,
            "history": session.history if include_history else None
        }

    except Exception as e:
        logger.error("Failed to get session: %s", e, exc_info=True)
        return {
            "error": str(e),
            "suggestion": "Check session_id is valid"
        }


async def list_sessions(
    services: dict,
    project_id: Optional[str] = None,
    include_expired: bool = False,
    limit: int = 50
) -> dict:
    """List all sessions with optional filtering.

    Returns list of sessions sorted by last activity (most recent first).
    Can filter by project and exclude expired sessions.

    Args:
        services: Service dependency dict
        project_id: Optional filter by project ID
        include_expired: Include expired sessions in results
        limit: Maximum number of sessions to return

    Returns:
        List of session summaries

    Example:
        >>> result = await list_sessions(services, project_id="my_project")
        >>> for session in result["sessions"]:
        ...     print(f"{session['session_id']}: {session['status']}")
    """
    session_manager = services["session_manager"]

    try:
        sessions = await session_manager.list_sessions(
            project_id=project_id,
            include_expired=include_expired,
            limit=limit
        )

        return {
            "sessions": [
                {
                    "session_id": s["session_id"],
                    "project_id": s["project_id"],
                    "status": s.get("status", "unknown"),
                    "description": s.get("description"),
                    "created_at": s["created_at"],
                    "last_active": s["last_active"]
                }
                for s in sessions
            ],
            "total": len(sessions)
        }

    except Exception as e:
        logger.error("Failed to list sessions: %s", e, exc_info=True)
        return {
            "error": str(e),
            "suggestion": "Check database is accessible"
        }


async def resume_session(
    services: dict,
    session_id: str
) -> dict:
    """Resume an existing session.

    Validates the session is still valid (not expired), updates last_active
    timestamp, and returns session context including recent activity and
    project statistics.

    Args:
        services: Service dependency dict
        session_id: Session identifier to resume

    Returns:
        Resumed session details with context

    Example:
        >>> result = await resume_session(services, "sess_123")
        >>> print(result["guidance"]["recent_activity"])
    """
    session_manager = services["session_manager"]
    event_system = services["event_system"]

    # Track start
    await event_system.emit(
        "mcp.tool.started",
        source="mcp_tool",
        tool_name="resume_session",
        session_id=session_id
    )

    # Validate session
    if not await session_manager.validate_session(session_id):
        return {
            "error": f"Session '{session_id}' not found or expired",
            "suggestion": "Session may have expired. Use list_sessions to find valid sessions."
        }

    # Track tool call in session history
    await session_manager.track_tool_call(session_id, "resume_session", {})

    try:
        result = await session_manager.resume_session(session_id)

        # Track success
        await event_system.emit(
        "mcp.tool.completed",
        source="mcp_tool",
            tool_name="resume_session",
            session_id=session_id
        )

        return result

    except Exception as e:
        # Track failure
        await event_system.emit(
        "mcp.tool.failed",
        source="mcp_tool",
            tool_name="resume_session",
            error=str(e)
        )
        logger.error("Failed to resume session: %s", e, exc_info=True)
        return {
            "error": str(e),
            "suggestion": "Ensure session_id is valid"
        }


__all__ = [
    "create_session",
    "get_session",
    "list_sessions",
    "resume_session"
]
