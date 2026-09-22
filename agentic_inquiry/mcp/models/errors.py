"""Error models for MCP server."""

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class MCPError(BaseModel):
    """Base error model for MCP operations."""
    
    code: str = Field(..., description="Error code")
    message: str = Field(..., description="Error message")
    details: Optional[Dict[str, Any]] = Field(None, description="Additional error details")
    help: Optional[str] = Field(None, description="Help text for resolving the error")


class SessionNotFoundError(MCPError):
    """Error raised when a session is not found."""
    
    code: str = Field(default="SESSION_NOT_FOUND", description="Error code")
    session_id: str = Field(..., description="Session ID that was not found")
    
    def __init__(self, session_id: str, **kwargs):
        """Initialize SessionNotFoundError.
        
        Args:
            session_id: The session ID that was not found
            **kwargs: Additional fields
        """
        super().__init__(  # type: ignore[call-arg]
            code="SESSION_NOT_FOUND",
            message=f"Session '{session_id}' not found",
            help="Create a new session with 'create_session' tool",
            session_id=session_id,
            **kwargs
        )


class EntityNotFoundError(MCPError):
    """Error raised when an entity is not found."""
    
    code: str = Field(default="ENTITY_NOT_FOUND", description="Error code")
    entity_name: str = Field(..., description="Entity name that was not found")
    
    def __init__(self, entity_name: str, **kwargs):
        """Initialize EntityNotFoundError.
        
        Args:
            entity_name: The entity name that was not found
            **kwargs: Additional fields
        """
        super().__init__(  # type: ignore[call-arg]
            code="ENTITY_NOT_FOUND",
            message=f"Entity '{entity_name}' not found",
            help="Check entity name spelling or search for similar entities",
            entity_name=entity_name,
            **kwargs
        )


class ValidationError(MCPError):
    """Error raised when validation fails."""
    
    code: str = Field(default="VALIDATION_ERROR", description="Error code")
    field: Optional[str] = Field(None, description="Field that failed validation")
    
    def __init__(self, message: str, field: Optional[str] = None, **kwargs):
        """Initialize ValidationError.
        
        Args:
            message: Validation error message
            field: Optional field name that failed validation
            **kwargs: Additional fields
        """
        super().__init__(  # type: ignore[call-arg]
            code="VALIDATION_ERROR",
            message=message,
            field=field,
            **kwargs
        )


__all__ = [
    "MCPError",
    "SessionNotFoundError",
    "EntityNotFoundError",
    "ValidationError",
]
