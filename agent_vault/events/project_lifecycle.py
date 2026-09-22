"""Project lifecycle event tracking helpers.

This module provides utilities for tracking project lifecycle events
(initialized, loaded, closed) in application code.

Since Config.load() and Config.for_project() are synchronous but EventSystem
is async, these helpers should be called from async application code after
project initialization.
"""

import logging
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from agent_vault.events.models import EventStatus
from agent_vault.events.types import EventTypes

if TYPE_CHECKING:
    from agent_vault.events.system import EventSystem

logger = logging.getLogger(__name__)


async def emit_project_initialized(
    event_system: "EventSystem",
    project_id: str,
    project_path: Optional[Path] = None,
    **metadata
) -> None:
    """Emit project.initialized event.
    
    Call this after creating a new project or first-time initialization.
    
    Args:
        event_system: EventSystem instance
        project_id: Project identifier
        project_path: Optional project root path
        **metadata: Additional metadata
        
    Example:
        >>> config = Config.load()
        >>> ctx = config.for_project("my_project")
        >>> async with EventSystem.from_config(ctx) as events:
        ...     await emit_project_initialized(
        ...         events,
        ...         ctx.project_id,
        ...         project_path=Path.cwd()
        ...     )
    """
    event_metadata = {
        "project_id": project_id,
        **metadata
    }
    
    if project_path:
        event_metadata["project_path"] = str(project_path)
    
    await event_system.emit(
        EventTypes.Project.INITIALIZED,
        source="project_lifecycle",
        status=EventStatus.COMPLETED,
        **event_metadata
    )
    
    logger.info("Project initialized: %s", project_id)


async def emit_project_loaded(
    event_system: "EventSystem",
    project_id: str,
    project_path: Optional[Path] = None,
    **metadata
) -> None:
    """Emit project.loaded event.
    
    Call this when loading an existing project.
    
    Args:
        event_system: EventSystem instance
        project_id: Project identifier
        project_path: Optional project root path
        **metadata: Additional metadata
        
    Example:
        >>> config = Config.load()
        >>> ctx = config.for_project("my_project")
        >>> async with EventSystem.from_config(ctx) as events:
        ...     await emit_project_loaded(
        ...         events,
        ...         ctx.project_id,
        ...         project_path=Path.cwd()
        ...     )
    """
    event_metadata = {
        "project_id": project_id,
        **metadata
    }
    
    if project_path:
        event_metadata["project_path"] = str(project_path)
    
    await event_system.emit(
        EventTypes.Project.LOADED,
        source="project_lifecycle",
        status=EventStatus.COMPLETED,
        **event_metadata
    )
    
    logger.debug("Project loaded: %s", project_id)


async def emit_project_closed(
    event_system: "EventSystem",
    project_id: str,
    **metadata
) -> None:
    """Emit project.closed event.
    
    Call this when closing/shutting down a project.
    
    Args:
        event_system: EventSystem instance
        project_id: Project identifier
        **metadata: Additional metadata
        
    Example:
        >>> async with EventSystem.from_config(ctx) as events:
        ...     # ... do work ...
        ...     await emit_project_closed(events, ctx.project_id)
    """
    event_metadata = {
        "project_id": project_id,
        **metadata
    }
    
    await event_system.emit(
        EventTypes.Project.CLOSED,
        source="project_lifecycle",
        status=EventStatus.COMPLETED,
        **event_metadata
    )
    
    logger.info("Project closed: %s", project_id)
