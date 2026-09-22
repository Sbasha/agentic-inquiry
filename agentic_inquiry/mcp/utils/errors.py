"""Error handling utilities for MCP tools.

This module provides centralized error handling, converting exceptions
to helpful MCP error responses with suggestions and related tools.
"""

from typing import Dict, Any, List, Optional


class MCPErrorHandler:
    """Central error handling for MCP tools.
    
    This class converts exceptions into helpful MCP error responses that include:
    - Error codes and messages
    - Help text explaining the error
    - Actionable suggestions for resolution
    - Related tools that might help
    
    Example:
        try:
            result = await tool.execute(**params)
        except Exception as e:
            return MCPErrorHandler.handle(e, params, services)
    """
    
    # Error message templates
    ERROR_MESSAGES: Dict[str, Dict[str, Any]] = {
        "SESSION_NOT_FOUND": {
            "message": "Session '{session_id}' not found or expired",
            "help": "Create a new session with 'create_session' tool",
            "related": ["create_session", "list_sessions"],
            "suggestions": [
                "Try: Create a new session with create_session(project_id='your_project')",
                "Try: List active sessions with list_sessions() to find valid session IDs",
                "Try: Check if the session has expired (default TTL is 48 hours)"
            ]
        },
        "PROJECT_NOT_INDEXED": {
            "message": "Project '{project_id}' has no indexed content",
            "help": "Index your content with 'add_knowledge' tool before searching",
            "related": ["add_knowledge"],
            "suggestions": [
                "Try: Index a file with add_knowledge(session_id='...', content_type='file', source='path/to/file.py')",
                "Try: Index a directory with add_knowledge(session_id='...', content_type='directory', source='src/')",
                "Try: Check session status to see indexing progress"
            ]
        },
        "NO_RESULTS": {
            "message": "No results found for query '{query}'",
            "help": "Try broader search terms or check if content is indexed",
            "related": ["add_knowledge", "search_knowledge"],
            "suggestions": [
                "Try: Using different keywords or synonyms",
                "Try: Broader search terms (e.g., 'authentication' instead of 'OAuth2TokenValidator')",
                "Try: Checking if relevant files are indexed with add_knowledge",
                "Try: Searching for related concepts or parent classes"
            ]
        },
        "ENTITY_NOT_FOUND": {
            "message": "Entity '{entity}' not found in index",
            "help": "The entity may not exist or may not be indexed yet",
            "related": ["search_knowledge", "add_knowledge"],
            "suggestions": [
                "Try: Using a qualified name like 'Module.Class.method'",
                "Try: Searching first with search_knowledge to find the correct entity name",
                "Try: Checking if the entity's file has been indexed",
                "Try: Using understand_entity with a broader entity name"
            ]
        },
        "TOKEN_BUDGET_EXCEEDED": {
            "message": "Context exceeds token budget of {max_tokens}",
            "help": "Increase max_tokens parameter or use more focused query",
            "related": ["search_knowledge", "build_context"],
            "suggestions": [
                "Try: Increasing max_tokens parameter (e.g., max_tokens=8000)",
                "Try: Using a more specific query to reduce result count",
                "Try: Using focus='code' or focus='docs' to limit context scope",
                "Try: Using depth='focused' instead of 'comprehensive'"
            ]
        },
        "INVALID_PROJECT_ID": {
            "message": "Invalid project ID '{project_id}'",
            "help": "Project IDs must be alphanumeric with hyphens/underscores",
            "related": ["create_session"],
            "suggestions": [
                "Try: Using only letters, numbers, hyphens, and underscores",
                "Try: Avoiding spaces and special characters",
                "Try: Example valid IDs: 'my-project', 'project_123', 'MyProject2024'"
            ]
        },
        "INDEXING_FAILED": {
            "message": "Failed to index content from '{source}'",
            "help": "Check that the path exists and is accessible",
            "related": ["add_knowledge"],
            "suggestions": [
                "Try: Verifying the file or directory exists at the specified path",
                "Try: Using a relative path from the project root (e.g., 'src/main.py')",
                "Try: Checking file permissions and accessibility",
                "Try: Ensuring the file format is supported (Python, JavaScript, Markdown, etc.)"
            ],
            "troubleshooting": {
                "possible_causes": [
                    "File or directory does not exist at the specified path",
                    "File format is not supported by available parsers",
                    "Insufficient permissions to read the file",
                    "File is corrupted or contains invalid encoding",
                    "Parser failed to process file structure"
                ],
                "next_steps": [
                    "Verify the file path is correct and the file exists",
                    "Check file extension is supported (.py, .js, .ts, .md, .txt, etc.)",
                    "Ensure you have read permissions for the file",
                    "Try indexing a different file to isolate the issue",
                    "Check logs for detailed parser error messages"
                ],
                "supported_formats": [
                    "Code: .py, .js, .ts, .jsx, .tsx, .java, .cpp, .c, .h, .cs, .go, .rs, .rb, .php",
                    "Documentation: .md, .rst, .txt",
                    "Documents: .pdf, .docx, .html"
                ]
            }
        },
        "STORAGE_ERROR": {
            "message": "Storage operation failed",
            "help": "Check database connectivity and disk space",
            "related": [],
            "suggestions": [
                "Try: Checking available disk space in the vector_db directory",
                "Try: Verifying database file permissions",
                "Try: Restarting the service if database is locked",
                "Try: Checking logs for detailed error information"
            ],
            "troubleshooting": {
                "possible_causes": [
                    "Insufficient disk space for database operations",
                    "Database file is locked by another process",
                    "Database corruption or schema mismatch",
                    "File system permissions issue",
                    "Network storage connectivity issue"
                ],
                "next_steps": [
                    "Check available disk space with 'df -h' or similar",
                    "Verify no other processes are accessing the database",
                    "Check database file permissions in vector_db/ directory",
                    "Review logs for specific storage error details",
                    "Consider backing up and reinitializing the database if corrupted"
                ]
            }
        },
        "CONFIGURATION_ERROR": {
            "message": "Configuration error: {details}",
            "help": "Check your configuration file and environment variables",
            "related": [],
            "suggestions": [
                "Try: Reviewing agentic-inquiry.yaml for syntax errors",
                "Try: Checking environment variables (AI_*)",
                "Try: Comparing with config/default.yaml for correct structure",
                "Try: Validating configuration against config/config.schema.json"
            ],
            "troubleshooting": {
                "possible_causes": [
                    "YAML syntax error in configuration file",
                    "Missing required configuration fields",
                    "Invalid configuration values or types",
                    "Environment variable override conflicts",
                    "Configuration file not found or not readable"
                ],
                "next_steps": [
                    "Validate YAML syntax using a YAML validator",
                    "Compare your config with config/default.yaml",
                    "Check environment variables with 'env | grep INQUIRY_'",
                    "Review config/config.schema.json for required fields",
                    "Try running with default configuration to isolate the issue"
                ]
            }
        },
    }
    
    @staticmethod
    async def handle(
        error: Exception,
        context: Dict[str, Any],
        services: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Convert exception to helpful MCP error response.
        
        Args:
            error: Exception that occurred
            context: Original parameters for context
            services: Service instances for generating suggestions
            
        Returns:
            MCP error response dictionary with error details and suggestions
        """
        # Import here to avoid circular dependency
        from agentic_inquiry.mcp.models.errors import (
            SessionNotFoundError,
            EntityNotFoundError,
        )
        from agentic_inquiry.exceptions import (
            ConfigurationError,
            StorageError,
            ParsingError,
        )
        
        # Map exception types to error codes
        if isinstance(error, SessionNotFoundError):
            return await MCPErrorHandler._format_error(
                "SESSION_NOT_FOUND",
                context,
                services
            )
        
        elif isinstance(error, EntityNotFoundError):
            # Generate suggestions for entity not found
            suggestions = await MCPErrorHandler._suggest_similar_entities(
                context.get("entity", ""),
                services
            )
            return await MCPErrorHandler._format_error(
                "ENTITY_NOT_FOUND",
                context,
                services,
                additional_suggestions=suggestions
            )
        
        elif isinstance(error, StorageError):
            return await MCPErrorHandler._format_error(
                "STORAGE_ERROR",
                {"details": str(error)},
                services
            )
        
        elif isinstance(error, ConfigurationError):
            return await MCPErrorHandler._format_error(
                "CONFIGURATION_ERROR",
                {"details": str(error)},
                services
            )
        
        elif isinstance(error, ParsingError):
            return await MCPErrorHandler._format_error(
                "INDEXING_FAILED",
                {"source": context.get("source", "unknown"), "details": str(error)},
                services
            )
        
        # Check error message for common patterns
        error_msg = str(error).lower()
        
        if "session" in error_msg and ("not found" in error_msg or "expired" in error_msg):
            return await MCPErrorHandler._format_error(
                "SESSION_NOT_FOUND",
                context,
                services
            )
        
        elif "entity" in error_msg and "not found" in error_msg:
            suggestions = await MCPErrorHandler._suggest_similar_entities(
                context.get("entity", ""),
                services
            )
            return await MCPErrorHandler._format_error(
                "ENTITY_NOT_FOUND",
                context,
                services,
                additional_suggestions=suggestions
            )
        
        elif "no results" in error_msg or "empty" in error_msg:
            suggestions = await MCPErrorHandler._suggest_search_alternatives(
                context.get("query", ""),
                services
            )
            return await MCPErrorHandler._format_error(
                "NO_RESULTS",
                context,
                services,
                additional_suggestions=suggestions
            )
        
        elif "token" in error_msg and "budget" in error_msg:
            return await MCPErrorHandler._format_error(
                "TOKEN_BUDGET_EXCEEDED",
                context,
                services
            )
        
        # Generic error for unexpected exceptions
        return {
            "error": {
                "code": "INTERNAL_ERROR",
                "message": str(error),
                "help": "An unexpected error occurred. Check logs for details.",
                "details": {
                    "error_type": type(error).__name__,
                    "error_message": str(error)
                }
            },
            "suggestions": [
                "Check session log for detailed error information",
                "Verify all parameters are correct",
                "If this persists, please report the issue"
            ],
            "related_tools": [],
            "context": context
        }
    
    @staticmethod
    async def _format_error(
        error_code: str,
        context: Dict[str, Any],
        services: Dict[str, Any],
        additional_suggestions: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Format error response from template.
        
        Args:
            error_code: Error code from ERROR_MESSAGES
            context: Context for message formatting
            services: Service instances
            additional_suggestions: Additional suggestions to include
            
        Returns:
            Formatted error response dictionary
        """
        template = MCPErrorHandler.ERROR_MESSAGES.get(error_code)
        if not template:
            # Fallback for unknown error codes
            return {
                "error": {
                    "code": error_code,
                    "message": "An error occurred",
                    "help": "Check the error details for more information",
                    "details": context
                },
                "suggestions": [],
                "related_tools": [],
                "context": context
            }
        
        # Format message with context
        try:
            message = template["message"].format(**context)
        except KeyError:
            # If formatting fails, use template as-is
            message = template["message"]
        
        help_text = template["help"]
        
        # Combine suggestions
        suggestions = []
        
        # Add template suggestions first
        if "suggestions" in template:
            suggestions.extend(template["suggestions"])
        
        # Add additional context-specific suggestions
        if additional_suggestions:
            suggestions.extend(additional_suggestions)
        
        # Build response
        response = {
            "error": {
                "code": error_code,
                "message": message,
                "help": help_text,
                "details": context
            },
            "suggestions": suggestions,
            "related_tools": template["related"],
            "context": context
        }
        
        # Add troubleshooting section if available
        if "troubleshooting" in template:
            response["troubleshooting"] = template["troubleshooting"]
        
        return response
    
    @staticmethod
    async def _suggest_search_alternatives(
        query: str,
        services: Dict[str, Any]
    ) -> List[str]:
        """Generate suggestions for empty search results.
        
        Args:
            query: Original search query
            services: Service instances
            
        Returns:
            List of suggestion strings
        """
        suggestions = []
        
        # Check if query is very short
        if len(query) < 3:
            suggestions.append(
                "Try: Using a longer, more specific search query (at least 3 characters)"
            )
        
        # Check if query is very long
        if len(query) > 100:
            suggestions.append(
                "Try: Using a shorter, more focused search query"
            )
        
        # Try to get top keywords from the project to suggest alternatives
        try:
            from agentic_inquiry.mcp.utils.keyword_extractor import KeywordExtractor
            
            db_manager = services.get("storage")
            session_manager = services.get("session_manager")
            
            if db_manager and session_manager:
                # Get project_id from context if available
                project_id = services.get("project_id")
                
                if project_id:
                    keyword_extractor = KeywordExtractor()
                    top_keywords = await keyword_extractor.extract_top_keywords(
                        db_manager=db_manager,
                        project_id=project_id,
                        limit=10
                    )
                    
                    if top_keywords:
                        keyword_list = ", ".join([kw["keyword"] for kw in top_keywords[:5]])
                        suggestions.append(
                            f"Try: Using keywords from indexed content: {keyword_list}"
                        )
        except Exception as e:
            # Don't fail if keyword extraction fails
            import logging
            logger = logging.getLogger(__name__)
            logger.debug("Failed to extract keywords for suggestions: %s", e)
        
        return suggestions
    
    @staticmethod
    async def _suggest_similar_entities(
        entity: str,
        services: Dict[str, Any]
    ) -> List[str]:
        """Generate suggestions for entity not found.
        
        Args:
            entity: Entity name that wasn't found
            services: Service instances
            
        Returns:
            List of suggestion strings
        """
        suggestions = []
        
        # Suggest using qualified names
        if "." not in entity and "/" not in entity:
            suggestions.append(
                f"Try: Using a qualified name like 'module.{entity}' or 'class.{entity}'"
            )
        
        return suggestions
    
    @staticmethod
    def create_validation_error(
        field: str,
        message: str,
        context: Dict[str, Any],
        provided_value: Any = None,
        expected_type: Optional[str] = None,
        expected_values: Optional[List[str]] = None,
        example: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a validation error response with detailed information.
        
        Args:
            field: Field that failed validation
            message: Validation error message
            context: Original request context
            provided_value: The value that was provided (optional)
            expected_type: Expected type or format (optional)
            expected_values: List of valid values (optional)
            example: Example of valid usage (optional)
            
        Returns:
            MCP error response dictionary with validation details
        """
        from agentic_inquiry.correlation import get_correlation_id
        
        correlation_id = get_correlation_id()
        
        # Build detailed error information
        details: Dict[str, Any] = {
            "field": field,
            "validation_error": message,
            "correlation_id": correlation_id
        }
        
        if provided_value is not None:
            details["provided"] = str(provided_value)
        
        if expected_type:
            details["expected_type"] = expected_type
        
        if expected_values:
            details["expected_values"] = expected_values
        
        # Build suggestions
        suggestions = [
            "Review the tool documentation for parameter requirements",
            "Ensure the parameter type matches the expected type",
            "Check for typos in parameter names"
        ]
        
        # Add specific suggestions based on validation type
        if expected_values:
            suggestions.insert(0, f"Try: Using one of these valid values: {', '.join(expected_values)}")
        
        if expected_type:
            suggestions.insert(0, f"Try: Providing a value of type {expected_type}")
        
        if example:
            suggestions.insert(0, f"Try: Example usage: {example}")
        
        return {
            "error": {
                "code": "VALIDATION_ERROR",
                "message": f"Invalid value for '{field}': {message}",
                "help": "Check the parameter documentation for valid values",
                "details": details
            },
            "suggestions": suggestions,
            "related_tools": [],
            "context": context,
            "troubleshooting": {
                "possible_causes": [
                    "Parameter value is outside the allowed range",
                    "Parameter type doesn't match expected type",
                    "Required parameter is missing",
                    "Parameter name is misspelled",
                    "Parameter format is incorrect"
                ],
                "next_steps": [
                    "Check the tool documentation for parameter specifications",
                    "Verify parameter names are spelled correctly",
                    "Ensure parameter values match expected types",
                    "Review example usage in documentation",
                    f"Use correlation_id {correlation_id} when reporting issues"
                ]
            }
        }


__all__ = ["MCPErrorHandler"]
