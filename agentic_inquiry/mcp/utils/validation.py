"""Parameter validation utilities for MCP tools.

This module provides security-focused validation functions for tool parameters,
particularly for file path validation to prevent directory traversal attacks.
"""

import functools
import logging
import re
from pathlib import Path
from typing import Any, Optional, Union, Callable


class PathValidationError(ValueError):
    """Raised when path validation fails.

    This exception is raised when a file path fails security validation,
    such as attempting to access files outside allowed directories or
    using directory traversal sequences.
    """
    pass


class ProjectIDValidationError(ValueError):
    """Raised when project_id validation fails."""
    pass


class QueryValidationError(ValueError):
    """Raised when query validation fails.

    This exception is raised when a search query fails validation,
    such as being empty or exceeding maximum length limits.
    """
    pass


class EntityNameValidationError(ValueError):
    """Raised when entity name validation fails.

    This exception is raised when an entity name fails validation,
    such as containing path separators or exceeding length limits.
    """
    pass


class SessionIDValidationError(ValueError):
    """Raised when session_id validation fails.

    This exception is raised when a session ID fails validation,
    such as not being a valid UUID format.
    """
    pass


class ColumnNameValidationError(ValueError):
    """Raised when column name validation fails.

    This exception is raised when a column or field name fails validation,
    such as containing SQL injection characters or invalid patterns.
    """
    pass


# Query length limits for DoS prevention
MAX_QUERY_LENGTH = 10_000  # 10,000 characters
MIN_QUERY_LENGTH = 1  # Minimum 1 character (non-empty)

# Entity name limits
MAX_ENTITY_NAME_LENGTH = 500  # 500 characters for entity names
MIN_ENTITY_NAME_LENGTH = 1  # Minimum 1 character (non-empty)

# Path separator characters that are not allowed in entity names
FORBIDDEN_ENTITY_CHARS = frozenset({'/', '\\', '\x00'})  # Forward slash, backslash, null byte

# Logger for query validation warnings
_logger = logging.getLogger(__name__)

# Entity ID format: type::project_hash::file_path::entity_name
ENTITY_ID_SEPARATOR = "::"


def extract_entity_name_from_id(entity_input: str) -> tuple[str, bool]:
    """Extract entity name from a full entity ID or return as-is if simple name.

    Entity IDs have the format: type::project_hash::file_path::entity_name
    This function extracts just the entity name (last component) for validation,
    while preserving the original input for resolution.

    Args:
        entity_input: Either a simple entity name ("MyClass") or full entity ID
            ("class::project::/path/to/file.py::MyClass")

    Returns:
        Tuple of (entity_name, is_full_id):
        - entity_name: The extracted entity name for validation
        - is_full_id: True if input was a full entity ID, False if simple name

    Examples:
        >>> extract_entity_name_from_id("MyClass")
        ('MyClass', False)
        >>> extract_entity_name_from_id("class::proj::/path/file.py::MyClass")
        ('MyClass', True)
        >>> extract_entity_name_from_id("function::proj::/path.py::process_data")
        ('process_data', True)
    """
    if entity_input is None:
        return "", False

    entity_input = entity_input.strip()
    if not entity_input:
        return "", False

    # Check if this looks like a full entity ID (contains ::)
    if ENTITY_ID_SEPARATOR in entity_input:
        # Split by :: and take the last component as entity name
        parts = entity_input.split(ENTITY_ID_SEPARATOR)
        if len(parts) >= 4:
            # Format: type::project::path::name
            # Last part is the entity name
            entity_name = parts[-1].strip()
            return entity_name, True

    # Not a full entity ID, return as-is
    return entity_input, False


def validate_query_length(
    query: str,
    max_length: int = MAX_QUERY_LENGTH,
    truncate: bool = True,
    field_name: str = "query"
) -> str:
    """Validate and optionally truncate query string length.

    This function provides DoS protection by limiting query string length.
    Queries exceeding the maximum length can be truncated or rejected.

    Args:
        query: The query string to validate
        max_length: Maximum allowed query length (default: MAX_QUERY_LENGTH)
        truncate: If True, truncate long queries with warning; if False, raise error
        field_name: Name of the field for error messages (default: "query")

    Returns:
        Validated (and possibly truncated) query string

    Raises:
        QueryValidationError: If query is empty or exceeds max_length when truncate=False

    Examples:
        >>> validate_query_length("short query")
        'short query'
        >>> validate_query_length("", field_name="search_query")
        QueryValidationError: search_query cannot be empty
        >>> validate_query_length("x" * 20000, truncate=True)  # Returns truncated
        'xxx...xxx'  # 10,000 chars with warning logged
        >>> validate_query_length("x" * 20000, truncate=False)
        QueryValidationError: query exceeds maximum length

    Security Notes:
        - Empty queries are always rejected to prevent accidental full-table scans
        - Length limit prevents memory exhaustion and query processing DoS
        - Truncation preserves usability while enforcing limits
    """
    # Check for None or empty
    if query is None:
        raise QueryValidationError(
            f"{field_name} cannot be None. "
            f"Please provide a valid search query. "
            f"Example: {field_name}='how to authenticate users'"
        )

    # Strip whitespace and check for empty
    query = query.strip()
    if len(query) < MIN_QUERY_LENGTH:
        raise QueryValidationError(
            f"{field_name} cannot be empty. "
            f"Please provide a search query with at least {MIN_QUERY_LENGTH} character(s). "
            f"Example: {field_name}='authentication error handling'"
        )

    # Check length limit
    if len(query) > max_length:
        if truncate:
            original_length = len(query)
            query = query[:max_length]
            _logger.warning(
                "Query truncated from %d to %d characters for DoS protection. "
                "Consider using a more specific query.",
                original_length,
                max_length
            )
        else:
            raise QueryValidationError(
                f"{field_name} exceeds maximum length of {max_length} characters "
                f"(provided: {len(query)}). "
                f"Please use a shorter, more specific query. "
                f"Maximum allowed: {max_length} characters."
            )

    return query


def validate_entity_name(
    entity_name: str,
    max_length: int = MAX_ENTITY_NAME_LENGTH,
    field_name: str = "entity"
) -> str:
    """Validate entity name for security and consistency.

    This function validates entity names (class names, function names, etc.)
    to prevent path traversal attacks and ensure they are within reasonable
    length limits. Entity names should not contain path separators or other
    potentially dangerous characters.

    Args:
        entity_name: The entity name to validate
        max_length: Maximum allowed length (default: MAX_ENTITY_NAME_LENGTH)
        field_name: Name of the field for error messages (default: "entity")

    Returns:
        Validated entity name (stripped of leading/trailing whitespace)

    Raises:
        EntityNameValidationError: If entity name is empty, too long, or contains
            forbidden characters (path separators, null bytes)

    Examples:
        >>> validate_entity_name("MyClass")
        'MyClass'
        >>> validate_entity_name("my_function")
        'my_function'
        >>> validate_entity_name("path/to/class")
        EntityNameValidationError: entity contains forbidden characters
        >>> validate_entity_name("")
        EntityNameValidationError: entity cannot be empty

    Security Notes:
        - Path separators (/, \\) are rejected to prevent path traversal
        - Null bytes are rejected to prevent string truncation attacks
        - Length limit prevents memory exhaustion and DoS
        - Entity names are intended for code symbols, not file paths
    """
    # Check for None
    if entity_name is None:
        raise EntityNameValidationError(
            f"{field_name} cannot be None. "
            f"Please provide a valid entity name. "
            f"Example: {field_name}='MyClass' or {field_name}='authenticate'"
        )

    # Strip whitespace and check for empty
    entity_name = entity_name.strip()
    if len(entity_name) < MIN_ENTITY_NAME_LENGTH:
        raise EntityNameValidationError(
            f"{field_name} cannot be empty. "
            f"Please provide an entity name with at least {MIN_ENTITY_NAME_LENGTH} character(s). "
            f"Example: {field_name}='Config' or {field_name}='process_data'"
        )

    # Check length limit
    if len(entity_name) > max_length:
        raise EntityNameValidationError(
            f"{field_name} exceeds maximum length of {max_length} characters "
            f"(provided: {len(entity_name)}). "
            f"Please use a shorter, more specific entity name. "
            f"Maximum allowed: {max_length} characters."
        )

    # Check for forbidden characters (path separators, null bytes)
    forbidden_found = set(entity_name) & FORBIDDEN_ENTITY_CHARS
    if forbidden_found:
        # Format forbidden characters for display
        char_display = []
        for char in sorted(forbidden_found):
            if char == '/':
                char_display.append("'/' (forward slash)")
            elif char == '\\':
                char_display.append("'\\\\' (backslash)")
            elif char == '\x00':
                char_display.append("null byte")
            else:
                char_display.append(repr(char))

        raise EntityNameValidationError(
            f"{field_name} '{entity_name}' contains forbidden characters: {', '.join(char_display)}. "
            f"Entity names cannot contain path separators or control characters. "
            f"If you're looking for a file path, use search_knowledge with a file path query instead. "
            f"Example valid entity names: 'MyClass', 'process_data', 'Config'"
        )

    return entity_name


def validate_path(project_root_attr: str = "project_root") -> Callable:
    """Decorator to validate file paths before method execution.
    
    This decorator automatically validates file_path parameters against the
    project root to prevent directory traversal attacks. It extracts the
    project root from the instance using the specified attribute name.
    
    Args:
        project_root_attr: Name of the instance attribute containing project root path
                          (default: "project_root")
        
    Returns:
        Decorated function that validates file_path parameter before execution
        
    Raises:
        PathValidationError: If file_path is outside project root
        AttributeError: If instance doesn't have the specified project_root attribute
        
    Example:
        >>> class IndexingPipeline:
        ...     def __init__(self, project_root: str):
        ...         self.project_root = project_root
        ...     
        ...     @validate_path()
        ...     async def remove_file_data(self, file_path: str) -> None:
        ...         # file_path is now validated
        ...         pass
        
    Security Notes:
        - Validates file_path parameter before method execution
        - Uses validate_file_path() for actual validation logic
        - Preserves original exception messages for debugging
        - Works with both sync and async methods
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(self, *args, **kwargs):
            # Extract file_path from args or kwargs
            # Assume file_path is the first positional argument after self
            if args:
                file_path = args[0]
                remaining_args = args[1:]
            elif 'file_path' in kwargs:
                file_path = kwargs.pop('file_path')
                remaining_args = args
            else:
                raise ValueError(
                    f"Method {func.__name__} requires 'file_path' parameter for validation"
                )
            
            # Get project root from instance
            if not hasattr(self, project_root_attr):
                raise AttributeError(
                    f"Instance of {type(self).__name__} does not have attribute '{project_root_attr}'. "
                    f"Ensure the class has a '{project_root_attr}' attribute for path validation."
                )
            
            project_root = getattr(self, project_root_attr)
            
            # Validate the path
            validated_path = validate_file_path(file_path, project_root)
            
            # Call original function with validated path
            return await func(self, str(validated_path), *remaining_args, **kwargs)
        
        @functools.wraps(func)
        def sync_wrapper(self, *args, **kwargs):
            # Extract file_path from args or kwargs
            if args:
                file_path = args[0]
                remaining_args = args[1:]
            elif 'file_path' in kwargs:
                file_path = kwargs.pop('file_path')
                remaining_args = args
            else:
                raise ValueError(
                    f"Method {func.__name__} requires 'file_path' parameter for validation"
                )
            
            # Get project root from instance
            if not hasattr(self, project_root_attr):
                raise AttributeError(
                    f"Instance of {type(self).__name__} does not have attribute '{project_root_attr}'. "
                    f"Ensure the class has a '{project_root_attr}' attribute for path validation."
                )
            
            project_root = getattr(self, project_root_attr)
            
            # Validate the path
            validated_path = validate_file_path(file_path, project_root)
            
            # Call original function with validated path
            return func(self, str(validated_path), *remaining_args, **kwargs)
        
        # Return appropriate wrapper based on whether function is async
        import inspect
        if inspect.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


def validate_file_path(
    path: Union[str, Path],
    allowed_base: Path,
    must_exist: bool = False
) -> Path:
    """Validate file path is within allowed directory.
    
    This function provides security validation to prevent directory traversal
    attacks by ensuring that resolved paths stay within the allowed base directory.
    
    Args:
        path: Path to validate (can be relative or absolute)
        allowed_base: Base directory that path must be within
        must_exist: If True, path must exist on filesystem
        
    Returns:
        Validated absolute Path object
        
    Raises:
        PathValidationError: If path is outside allowed_base or doesn't exist
        
    Warning:
        Always use this function to validate user-provided file paths before
        performing file operations. Direct use of user-provided paths without
        validation can lead to unauthorized file access.
        
    Example:
        >>> base = Path("/project")
        >>> validate_file_path("src/main.py", base)
        Path("/project/src/main.py")
        >>> validate_file_path("../etc/passwd", base)
        PathValidationError: Path outside allowed directory
        
    Note:
        Security implementation details:
        - Uses Path.resolve() to normalize paths and resolve symlinks
        - Prevents directory traversal with ".." sequences
        - Validates against the resolved absolute path
        - Checks containment using relative_to() which raises ValueError
          if path is not within allowed_base
    """
    # Convert to Path objects
    path_obj = Path(path)
    allowed_base = Path(allowed_base).resolve()
    
    # If path is relative, resolve it relative to allowed_base
    # If path is absolute, resolve it as-is
    if not path_obj.is_absolute():
        path_obj = (allowed_base / path_obj).resolve()
    else:
        path_obj = path_obj.resolve()
    
    # Check if path is within allowed base
    # relative_to() raises ValueError if path is not a subpath
    try:
        path_obj.relative_to(allowed_base)
    except ValueError:
        raise PathValidationError(
            f"Security constraint violation: Path '{path}' is outside allowed directory '{allowed_base}'. "
            f"For security reasons, file operations are restricted to the project directory. "
            f"Try using a relative path from the project root (e.g., 'src/file.py') or "
            f"an absolute path within the project directory."
        )
    
    # Check existence if required
    if must_exist and not path_obj.exists():
        raise PathValidationError(
            f"Path '{path}' does not exist. "
            f"Ensure the file or directory exists within the project at '{allowed_base}'. "
            f"Try checking the path spelling or use a file listing tool to verify the location."
        )
    
    return path_obj



def validate_project_id(
    project_id: str,
    normalize: bool = True
) -> str:
    """
    Validate and optionally normalize project ID.
    
    This function validates project IDs according to the following rules:
    - Length: 1-64 characters
    - Characters: Only alphanumeric, hyphens (-), and underscores (_)
    - Pattern: ^[a-zA-Z0-9_-]+$
    - Normalization: Converts to lowercase if requested
    
    Args:
        project_id: Project identifier to validate
        normalize: If True, convert to lowercase (default: True)
        
    Returns:
        Validated (and possibly normalized) project_id
        
    Raises:
        ProjectIDValidationError: If validation fails with helpful error message
        
    Examples:
        >>> validate_project_id("my-project")
        'my-project'
        >>> validate_project_id("My_Project_123", normalize=True)
        'my_project_123'
        >>> validate_project_id("invalid project!")
        ProjectIDValidationError: Invalid characters in project_id
        
    Security Notes:
        - Strict format validation prevents SQL injection
        - Length limit prevents DoS attacks
        - Normalization ensures consistent storage
    """
    import re
    
    # Check for empty or None
    if not project_id:
        raise ProjectIDValidationError(
            "Project ID cannot be empty. "
            "Please provide a valid project identifier. "
            "Examples of valid project IDs: 'my-project', 'project_123', 'my_project'"
        )
    
    # Check length constraints
    if len(project_id) > 64:
        raise ProjectIDValidationError(
            f"Project ID '{project_id}' exceeds maximum length of 64 characters (current: {len(project_id)}). "
            f"Please use a shorter identifier. "
            f"Examples: 'my-project', 'proj-123', 'my_app'"
        )
    
    # Check character pattern
    pattern = r'^[a-zA-Z0-9_-]+$'
    if not re.fullmatch(pattern, project_id):
        # Identify invalid characters for better error message
        valid_chars = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-')
        invalid_chars = set(project_id) - valid_chars
        
        raise ProjectIDValidationError(
            f"Project ID '{project_id}' contains invalid characters: {sorted(invalid_chars)}. "
            f"Only alphanumeric characters, hyphens (-), and underscores (_) are allowed. "
            f"Examples of valid project IDs: 'my-project', 'project_123', 'my_project'"
        )
    
    # Normalize to lowercase if requested
    if normalize:
        normalized = project_id.lower()
        return normalized
    
    return project_id



def validate_limit(
    limit: int,
    min_value: int = 1,
    max_value: int = 1000,
    field_name: str = "limit"
) -> int:
    """Validate limit parameter for search and query operations.
    
    Args:
        limit: Limit value to validate
        min_value: Minimum allowed value (default: 1)
        max_value: Maximum allowed value (default: 1000)
        field_name: Name of the field for error messages
        
    Returns:
        Validated limit value
        
    Raises:
        ValueError: If limit is outside allowed range with detailed error
        
    Examples:
        >>> validate_limit(10)
        10
        >>> validate_limit(0)
        ValueError: limit must be between 1 and 1000
        >>> validate_limit(2000)
        ValueError: limit must be between 1 and 1000
    """
    if not isinstance(limit, int):
        raise ValueError(
            f"{field_name} must be an integer. "
            f"Provided: {type(limit).__name__} ({limit}). "
            f"Expected: integer between {min_value} and {max_value}. "
            f"Example: {field_name}=10"
        )
    
    if limit < min_value or limit > max_value:
        raise ValueError(
            f"{field_name} must be between {min_value} and {max_value}. "
            f"Provided: {limit}. "
            f"Try using a value within the allowed range. "
            f"Example: {field_name}=10"
        )
    
    return limit


def validate_search_type(
    search_type: str,
    allowed_types: Optional[list[Any]] = None
) -> str:
    """Validate search_type parameter.
    
    Args:
        search_type: Search type to validate
        allowed_types: List of allowed search types (default: ["hybrid", "vector", "fts"])
        
    Returns:
        Validated search_type
        
    Raises:
        ValueError: If search_type is not in allowed types with detailed error
        
    Examples:
        >>> validate_search_type("hybrid")
        'hybrid'
        >>> validate_search_type("invalid")
        ValueError: search_type must be one of: hybrid, vector, fts
    """
    if allowed_types is None:
        allowed_types = ["hybrid", "vector", "fts"]
    
    if not isinstance(search_type, str):
        raise ValueError(
            f"search_type must be a string. "
            f"Provided: {type(search_type).__name__} ({search_type}). "
            f"Expected: one of {', '.join(allowed_types)}. "
            f"Example: search_type='hybrid'"
        )
    
    if search_type not in allowed_types:
        raise ValueError(
            f"search_type must be one of: {', '.join(allowed_types)}. "
            f"Provided: '{search_type}'. "
            f"Try using one of the supported search types. "
            f"Example: search_type='hybrid'"
        )
    
    return search_type


def validate_content_type(
    content_type: str,
    allowed_types: Optional[list[Any]] = None
) -> str:
    """Validate content_type parameter for indexing operations.

    Supports aliases for more intuitive usage:
    - "code" → "directory" (indexes a codebase directory)

    Args:
        content_type: Content type to validate
        allowed_types: List of allowed content types (default: ["file", "directory", "text"])

    Returns:
        Validated and normalized content_type

    Raises:
        ValidationError: If content_type is not in allowed types with detailed error

    Examples:
        >>> validate_content_type("file")
        'file'
        >>> validate_content_type("code")  # Alias for directory
        'directory'
        >>> validate_content_type("invalid")
        ValidationError: Invalid content_type: 'invalid'. Valid values: file, directory, text, code
    """
    from agentic_inquiry.exceptions import ValidationError

    # Content type aliases for more intuitive usage
    CONTENT_TYPE_ALIASES = {
        "code": "directory",  # "code" is more intuitive than "directory" for codebase indexing
    }

    if allowed_types is None:
        allowed_types = ["file", "directory", "text"]

    if not isinstance(content_type, str):
        raise ValidationError(
            param_name="content_type",
            invalid_value=content_type,
            valid_values=allowed_types + list(CONTENT_TYPE_ALIASES.keys()),
            example="content_type='file'"
        )

    # Normalize alias to canonical value
    normalized = CONTENT_TYPE_ALIASES.get(content_type, content_type)

    if normalized not in allowed_types:
        raise ValidationError(
            param_name="content_type",
            invalid_value=content_type,
            valid_values=allowed_types + list(CONTENT_TYPE_ALIASES.keys()),
            example="content_type='file'"
        )

    return normalized


def create_validation_error_response(
    field: str,
    error: Exception,
    context: dict[str, Any],
    provided_value: Any = None,
    expected_type: Optional[str] = None,
    expected_values: Optional[list[Any]] = None,
    example: Optional[str] = None
) -> dict[str, Any]:
    """Create a standardized validation error response.
    
    This is a convenience function that wraps MCPErrorHandler.create_validation_error
    with additional context from validation exceptions.
    
    Args:
        field: Field that failed validation
        error: The validation exception
        context: Original request context
        provided_value: The value that was provided
        expected_type: Expected type or format
        expected_values: List of valid values
        example: Example of valid usage
        
    Returns:
        Formatted validation error response
    """
    from agentic_inquiry.mcp.utils.errors import MCPErrorHandler
    
    return MCPErrorHandler.create_validation_error(
        field=field,
        message=str(error),
        context=context,
        provided_value=provided_value,
        expected_type=expected_type,
        expected_values=expected_values,
        example=example
    )


def validate_session_id(session_id: str) -> str:
    """Validate session ID format.

    Session IDs must be valid UUID4 format to prevent session fixation
    and ensure sessions are only created by the server.

    Args:
        session_id: Session identifier to validate

    Returns:
        Validated session_id (lowercase, normalized)

    Raises:
        SessionIDValidationError: If session_id is not a valid UUID format

    Examples:
        >>> validate_session_id("550e8400-e29b-41d4-a716-446655440000")
        '550e8400-e29b-41d4-a716-446655440000'
        >>> validate_session_id("not-a-uuid")
        SessionIDValidationError: Invalid session_id format

    Security Notes:
        - Validates UUID4 format to prevent session ID injection
        - Normalizes to lowercase for consistent handling
        - Prevents session fixation by ensuring only server-generated IDs are valid
    """
    import uuid

    # Check for empty or None
    if not session_id:
        raise SessionIDValidationError(
            "Session ID cannot be empty. "
            "Please provide a valid session ID from create_session()."
        )

    # Normalize to lowercase and strip whitespace
    session_id = session_id.strip().lower()

    # Validate UUID format
    try:
        parsed_uuid = uuid.UUID(session_id, version=4)
        # Ensure it's actually a valid UUID4 (check variant and version)
        if parsed_uuid.version != 4:
            raise SessionIDValidationError(
                f"Session ID '{session_id}' is not a valid UUID4 format. "
                "Session IDs must be UUID4 (random UUID) generated by create_session()."
            )
        return str(parsed_uuid)
    except ValueError:
        raise SessionIDValidationError(
            f"Session ID '{session_id}' is not a valid UUID format. "
            "Session IDs must be UUID4 format like '550e8400-e29b-41d4-a716-446655440000'. "
            "Use create_session() to generate a valid session ID."
        )


# Column name validation pattern (SEC-006)
# Matches safe SQL column names: starts with letter/underscore,
# contains only alphanumeric and underscores, dots allowed for nested access
_COLUMN_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def validate_column_name(
    column_name: str,
    field_name: str = "column",
    allow_nested: bool = True
) -> str:
    """Validate that a column name is safe for use in database queries.

    SEC-006: Prevents SQL injection by ensuring column names follow
    a strict pattern (alphanumeric + underscore, starting with letter or underscore).

    Column names must:
    - Start with a letter or underscore
    - Contain only letters, numbers, and underscores
    - Optionally contain dots for nested field access (e.g., metadata.type)
    - Not be empty
    - Not contain SQL injection characters (quotes, semicolons, comments, etc.)

    Args:
        column_name: Column name to validate
        field_name: Name of the field for error messages (default: "column")
        allow_nested: If True, allows dot-separated nested access (default: True)

    Returns:
        Validated column name (stripped of whitespace)

    Raises:
        ColumnNameValidationError: If column name is invalid or contains
            potentially dangerous characters

    Examples:
        >>> validate_column_name("file_path")
        'file_path'
        >>> validate_column_name("metadata.type")
        'metadata.type'
        >>> validate_column_name("DROP TABLE--")
        ColumnNameValidationError: Invalid column name
        >>> validate_column_name("column'; DELETE FROM")
        ColumnNameValidationError: Invalid column name

    Security Notes:
        - Prevents SQL injection via ORDER BY, SELECT, etc.
        - Only allows [A-Za-z_][A-Za-z0-9_]* pattern per segment
        - Dots are only allowed when allow_nested=True
        - Maximum length of 128 characters prevents DoS
    """
    # Check for None or empty
    if column_name is None:
        raise ColumnNameValidationError(
            f"{field_name} cannot be None. "
            f"Please provide a valid column name. "
            f"Examples: 'id', 'file_path', 'created_at'"
        )

    # Strip whitespace and check for empty
    column_name = column_name.strip()
    if not column_name:
        raise ColumnNameValidationError(
            f"{field_name} cannot be empty. "
            f"Please provide a valid column name. "
            f"Examples: 'id', 'file_path', 'created_at'"
        )

    # Length check (prevent DoS via extremely long names)
    max_length = 128
    if len(column_name) > max_length:
        raise ColumnNameValidationError(
            f"{field_name} '{column_name[:50]}...' exceeds maximum length of {max_length} characters. "
            f"Please use a shorter column name."
        )

    # Check for dots and validate nested access
    if "." in column_name:
        if not allow_nested:
            raise ColumnNameValidationError(
                f"{field_name} '{column_name}' contains dots but nested access is not allowed. "
                f"Please use a simple column name without dots."
            )

        # Check for invalid dot patterns
        if column_name.startswith(".") or column_name.endswith(".") or ".." in column_name:
            raise ColumnNameValidationError(
                f"{field_name} '{column_name}' has invalid dot pattern. "
                f"Column names cannot start/end with dots or contain consecutive dots. "
                f"Example valid nested: 'metadata.type'"
            )

        # Validate each segment
        segments = column_name.split(".")
        for segment in segments:
            if not segment:
                raise ColumnNameValidationError(
                    f"{field_name} '{column_name}' has empty segment. "
                    f"Each dot-separated segment must be non-empty."
                )
            if not _COLUMN_NAME_PATTERN.match(segment):
                raise ColumnNameValidationError(
                    f"{field_name} '{column_name}' contains invalid segment '{segment}'. "
                    f"Each segment must start with a letter or underscore and contain "
                    f"only letters, numbers, and underscores. "
                    f"Pattern: [A-Za-z_][A-Za-z0-9_]*"
                )
    else:
        # Simple column name without dots
        if not _COLUMN_NAME_PATTERN.match(column_name):
            raise ColumnNameValidationError(
                f"{field_name} '{column_name}' is invalid. "
                f"Column names must start with a letter or underscore and contain "
                f"only letters, numbers, and underscores. "
                f"Pattern: [A-Za-z_][A-Za-z0-9_]* "
                f"Examples: 'id', 'file_path', 'created_at'"
            )

    return column_name


def validate_column_names(
    column_names: list,
    field_name: str = "columns",
    allow_nested: bool = True
) -> list:
    """Validate a list of column names for safe database use.

    SEC-006: Validates each column name in a list to prevent SQL injection.

    Args:
        column_names: List of column names to validate
        field_name: Name of the field for error messages
        allow_nested: If True, allows dot-separated nested access

    Returns:
        Validated list of column names

    Raises:
        ColumnNameValidationError: If any column name is invalid

    Examples:
        >>> validate_column_names(["id", "name", "file_path"])
        ['id', 'name', 'file_path']
        >>> validate_column_names(["id", "'; DROP TABLE--"])
        ColumnNameValidationError: Invalid column name
    """
    if column_names is None:
        raise ColumnNameValidationError(
            f"{field_name} cannot be None. "
            f"Please provide a list of column names."
        )

    if not isinstance(column_names, list):
        raise ColumnNameValidationError(
            f"{field_name} must be a list. "
            f"Provided: {type(column_names).__name__}"
        )

    validated = []
    for i, col in enumerate(column_names):
        try:
            validated.append(validate_column_name(
                col,
                field_name=f"{field_name}[{i}]",
                allow_nested=allow_nested
            ))
        except ColumnNameValidationError as e:
            # Re-raise with context about the list position
            raise ColumnNameValidationError(str(e))

    return validated


# Known table names for validation (SEC-006)
# This allowlist prevents SQL injection via table name manipulation
KNOWN_TABLE_NAMES = frozenset({
    "document_chunks",
    "graph_entities",
    "graph_relationships",
    "memory_episodic",
    "memory_episodic_medium",
    "memory_semantic",
    "memory_semantic_high",
    "mcp_sessions",
    "mcp_events",
})


def validate_table_name(
    table_name: str,
    allow_unknown: bool = False
) -> str:
    """Validate that a table name is safe for database use.

    SEC-006: Prevents SQL injection via table name by:
    1. Validating against known table allowlist (preferred)
    2. Validating format pattern if allow_unknown=True

    Args:
        table_name: Table name to validate
        allow_unknown: If True, allows tables not in allowlist but validates format

    Returns:
        Validated table name

    Raises:
        ColumnNameValidationError: If table name is invalid or unknown

    Examples:
        >>> validate_table_name("document_chunks")
        'document_chunks'
        >>> validate_table_name("unknown_table")
        ColumnNameValidationError: Unknown table 'unknown_table'
        >>> validate_table_name("DROP TABLE--")
        ColumnNameValidationError: Invalid table name
    """
    # Validate format first
    validated = validate_column_name(
        table_name,
        field_name="table",
        allow_nested=False  # Table names cannot have dots
    )

    # Check against allowlist
    if validated not in KNOWN_TABLE_NAMES:
        if not allow_unknown:
            raise ColumnNameValidationError(
                f"Unknown table '{validated}'. "
                f"Valid tables are: {', '.join(sorted(KNOWN_TABLE_NAMES))}. "
                f"If this is a new table, ensure it's added to the allowlist."
            )
        # allow_unknown=True: format was validated above, allow it
        _logger.warning(
            "Allowing unknown table name '%s' - not in allowlist",
            validated
        )

    return validated
