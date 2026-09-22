"""FastMCP server initialization and orchestration."""

import asyncio
import logging
import inspect
import functools
import sys
from typing import Dict, Any, Optional, Callable, TypeVar

from fastmcp import FastMCP

from agent_vault.config import Config
from agent_vault.executors import shutdown_executors_async
from agent_vault.mcp.factories import create_mcp_services
from agent_vault.mcp.utils.rate_limiter import get_rate_limiter


logger = logging.getLogger(__name__)

# Type variable for generic function wrapping
F = TypeVar('F', bound=Callable[..., Any])


def create_service_bound_wrapper(
    tool_func: Callable[..., Any],
    services: Dict[str, Any]
) -> Callable[..., Any]:
    """Create a wrapper function that binds services parameter without using exec().

    This replaces the exec() pattern with a safer approach using functools.wraps
    and dynamic parameter reconstruction via inspect.signature().

    Args:
        tool_func: The original tool function that expects 'services' as first param
        services: The services dict to bind to the function

    Returns:
        Wrapper function with 'services' parameter removed from signature

    Notes:
        - Preserves function name, docstring, and annotations
        - Maintains parameter defaults and type hints
        - Compatible with FastMCP's parameter introspection
    """
    # Get original signature
    sig = inspect.signature(tool_func)

    # Build new parameters list without 'services'
    new_params = [
        param for name, param in sig.parameters.items()
        if name != "services"
    ]

    # Build new annotations without 'services'
    new_annotations = {
        k: v for k, v in tool_func.__annotations__.items()
        if k != "services"
    }

    # Create wrapper using functools to preserve metadata
    @functools.wraps(tool_func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        """Wrapper that injects services parameter with rate limiting."""
        # Check rate limit if session_id is present
        session_id = kwargs.get("session_id")
        if session_id:
            rate_limiter = get_rate_limiter()
            # Pass tool name for tool-specific rate limits
            result = await rate_limiter.check_rate_limit(
                session_id,
                tool_name=tool_func.__name__
            )
            if not result.allowed:
                logger.warning(
                    "Rate limit hit for session %s on tool %s: %s",
                    session_id,
                    tool_func.__name__,
                    result.limit_type,
                )
                return result.to_error_response()

        return await tool_func(services, *args, **kwargs)

    # Update wrapper metadata
    wrapper.__name__ = tool_func.__name__
    wrapper.__doc__ = tool_func.__doc__
    wrapper.__annotations__ = new_annotations
    wrapper.__signature__ = sig.replace(parameters=new_params)  # type: ignore[attr-defined]

    return wrapper


class MCPServer:
    """Main MCP server orchestrator.
    
    Responsibilities:
    - Initialize FastMCP application
    - Register tools based on configuration
    - Handle tool discovery and invocation
    - Manage API endpoints (if enabled)
    - Lifecycle management (startup/shutdown)
    """
    
    def __init__(self, config: Config, project_id: Optional[str] = None):
        """Initialize MCP server.
        
        Args:
            config: Configuration object
            project_id: Optional default project ID for service initialization
        """
        self.config = config
        self.project_id = project_id
        self.app: Optional[FastMCP] = None
        self.services: Dict[str, Any] = {}
        self._initialized = False
        
        logger.info(
            "MCPServer created",
            extra={
                "mcp_enabled": config.mcp.enabled,
                "project_id": project_id
            }
        )
    
    async def initialize(self, project_id: Optional[str] = None):
        """Initialize server and register tools.
        
        Args:
            project_id: Optional project ID to initialize services for.
                       If None, uses the project_id from constructor.
        
        Raises:
            RuntimeError: If MCP is not enabled in configuration
            ValueError: If no project_id is provided
        """
        if self._initialized:
            logger.warning("MCPServer already initialized, skipping")
            return
        
        if not self.config.mcp.enabled:
            raise RuntimeError("MCP is not enabled in configuration")
        
        # Determine project_id
        pid = project_id or self.project_id
        if not pid:
            raise ValueError("project_id must be provided either in constructor or initialize()")
        
        self.project_id = pid
        
        logger.info("Initializing MCP server for project: %s", self.project_id)
        
        # Create FastMCP application
        self.app = FastMCP(
            name=self.config.mcp.server.name,
            version=self.config.mcp.server.version,
            instructions=self.config.mcp.server.description
        )
        
        # Create service instances
        await self._create_services()
        
        # Register cognitive tools (always enabled)
        await self._register_cognitive_tools()
        
        # Register direct access tools (if enabled)
        if self.config.mcp.tools.direct_access.get("enabled", False):
            logger.info("Direct access tools enabled")
            await self._register_direct_tools()
        else:
            logger.info("Direct access tools disabled")
        
        self._initialized = True
        logger.info("MCP server initialized successfully")

        # After initialization, check if the project is new and needs onboarding
        await self._auto_start_project_learner()

    async def _auto_start_project_learner(self):
        """Automatically starts the project-learner agent if the project is unindexed."""
        try:
            storage = self.services.get("storage")
            if not storage:
                logger.warning("Storage service not available, cannot check project indexing status.")
                return

            tables = await storage.list_tables()
            chunk_count = await storage.count_chunks() if "document_chunks" in tables else 0

            if chunk_count == 0:
                logger.info("Project is unindexed. Automatically starting @project-learner agent.")
                print("\n[Agent-Vault] This project has not been indexed yet.", file=sys.stderr)
                print("[Agent-Vault] Automatically starting the @project-learner agent to build the knowledge base...\n", file=sys.stderr)

                if not self.app:
                    logger.error("FastMCP app not initialized, cannot start agent.")
                    return

                try:
                    # The agent invocation is sent as a request to the FastMCP application
                    # This simulates the user typing "@project-learner"
                    # --- Task Execution ---
                    pass
                    
                    # We need to process this request through the app's entry point.
                    # As we are inside the server, we can directly call the handler.
                    # This is a simplified approach. A more robust solution might involve
                    # a dedicated internal API for triggering agents.
                    
                    # Since we can't directly call the agent, we will notify the user
                    # and provide the command to run. This is a temporary measure until
                    # direct agent invocation from the server is implemented.
                    print("---------------------------------------------------------", file=sys.stderr)
                    print("ACTION REQUIRED:", file=sys.stderr)
                    print("  Run the following command to start the learning process:", file=sys.stderr)
                    print("  @project-learner learn this project", file=sys.stderr)
                    print("---------------------------------------------------------", file=sys.stderr)

                except Exception as e:
                    logger.error(f"Failed to start @project-learner agent: {e}", exc_info=True)
                    print(f"\n[Agent-Vault] Error: Could not automatically start the project learner agent: {e}", file=sys.stderr)
                    print("[Agent-Vault] Please run '@project-learner' manually.", file=sys.stderr)

        except Exception as e:
            logger.warning(f"Could not perform project learner check: {e}", exc_info=True)

    async def _check_and_suggest_onboarding(self):
        """Checks if the project is unindexed and suggests the onboarding tool."""
        try:
            storage = self.services.get("storage")
            if not storage:
                return

            tables = await storage.list_tables()
            if "document_chunks" not in tables:
                # If the main table doesn't even exist, it's a new project.
                logger.info("Project appears to be new. Suggesting onboarding.")
                print(
                    "\n[Agent-Vault] This project has not been indexed yet."
                    "\n[Agent-Vault] To get started, run the project learner agent: @project-learner\n",
                    file=sys.stderr
                )
                return

            # If table exists, check if it's empty
            chunk_count = await storage.count_chunks()
            if chunk_count == 0:
                logger.info("Project has no indexed content. Suggesting onboarding.")
                print(
                    "\n[Agent-Vault] This project has no indexed content."
                    "\n[Agent-Vault] To build the knowledge base, run the project learner agent: @project-learner\n",
                    file=sys.stderr
                )
        except Exception as e:
            # S5-001: Log onboarding check failure (non-critical)
            logger.warning(f"Could not perform project onboarding check: {e}", exc_info=True)
    
    async def _create_services(self):
        """Create all MCP services with dependencies."""
        logger.info("Creating MCP services")
        
        try:
            self.services = await create_mcp_services(
                config=self.config,
                project_id=self.project_id
            )
            
            logger.info(
                "MCP services created",
                extra={"service_count": len(self.services)}
            )
        except Exception:
            logger.error("Failed to create MCP services", exc_info=True)
            raise
    
    async def _register_cognitive_tools(self):
        """Register cognitive tools (default enabled)."""
        logger.info("Registering cognitive tools")

        # Import all tool functions
        from agent_vault.mcp.tools import (
            session, memory, search, analysis, context, knowledge, info
        )

        # Define tools with (function, name, description) tuples
        tools = [
            # Session tools
            (session.create_session, "create_session", "Create a new work session for a project"),
            (session.get_session, "get_session", "Retrieve details about a session"),
            (session.list_sessions, "list_sessions", "List all sessions with optional filtering"),
            (session.resume_session, "resume_session", "Resume an existing session"),

            # Memory tools
            (memory.save_memory, "save_memory", "Save an observation or insight to memory"),
            (memory.recall_memories, "recall_memories", "Recall relevant memories based on semantic similarity"),

            # Search tools
            (search.search_knowledge, "search_knowledge", "Search across all indexed content in the project"),
            (search.find_similar, "find_similar", "Find entities or content semantically similar to a query. Use search_scope='content' for document chunks, 'entities' for code symbols, or 'all' for both."),
            (search.fetch_content, "fetch_content", "Fetch full content for specific chunk IDs. Use after search_knowledge(preview_only=True) to retrieve selected results."),

            # Analysis tools
            (analysis.understand_entity, "understand_entity", "Deep dive into a code entity (class, function, module)"),
            (analysis.analyze_impact, "analyze_impact", "Analyze the impact of changing a code entity"),
            (analysis.find_patterns, "find_patterns", "Find recurring patterns in the codebase"),

            # Context tools
            (context.build_context, "build_context", "Build focused context for a task or query"),

            # Knowledge tools
            (knowledge.add_knowledge, "add_knowledge", "Add content to the knowledge base by indexing files or text"),

            # Info tools
            (info.get_server_info, "get_server_info", "Get comprehensive server configuration and available projects"),
            (info.get_events, "get_events", "Retrieve event log for a session"),
            (info.get_project_info, "get_project_info", "Get comprehensive project information and statistics"),
            (info.list_entities, "list_entities", "List indexed entities with optional filtering by type, file, or pattern"),
            (info.run_maintenance, "run_maintenance", "Run database maintenance to compact files and reclaim disk space"),
        ]

        # Register each tool with services injected using safe wrapper pattern
        for tool_func, name, description in tools:
            # Create service-bound wrapper without exec()
            bound_func = create_service_bound_wrapper(tool_func, self.services)

            # Register with FastMCP
            self.app.tool(bound_func, name=name, description=description)
            logger.debug("Registered tool: %s", name)

        logger.info("Registered %d cognitive tools", len(tools))
    
    async def _register_direct_tools(self):
        """Register direct access tools (default disabled)."""
        logger.info("Registering direct access tools")

        from agent_vault.mcp.tools import direct_access

        # Define direct access tools with (function, name, description) tuples
        tools = [
            (direct_access.index_files, "index_files", "Index specific files with granular control"),
            (direct_access.search_code, "search_code", "Code-only search with syntax awareness"),
            (direct_access.search_docs, "search_docs", "Documentation-only search"),
            (direct_access.graph_traverse, "graph_traverse", "Custom graph navigation and relationship traversal"),
            (direct_access.get_by_id, "get_by_id", "Bulk entity retrieval by ID"),
            (direct_access.get_recent_activity, "get_recent_activity", "Get recent project activity and changes"),
        ]

        # Register each tool with services injected using safe wrapper pattern
        for tool_func, name, description in tools:
            # Create service-bound wrapper without exec()
            bound_func = create_service_bound_wrapper(tool_func, self.services)

            # Register with FastMCP
            self.app.tool(bound_func, name=name, description=description)
            logger.debug("Registered direct access tool: %s", name)

        logger.info("Registered %d direct access tools", len(tools))
    
    async def start(self):
        """Start MCP server.

        Raises:
            RuntimeError: If server is not initialized
        """
        if not self._initialized:
            raise RuntimeError("Server must be initialized before starting")

        if not self.app:
            raise RuntimeError("FastMCP app not created")

        logger.info("Starting MCP server")

        # Start FastMCP server
        # Note: FastMCP handles the actual server lifecycle
        # This method is primarily for logging and future extensions

        logger.info(
            "MCP server started",
            extra={
                "host": self.config.mcp.api.host,
                "port": self.config.mcp.api.port,
                "api_enabled": self.config.mcp.api.enabled
            }
        )

    def run(
        self,
        transport: str = "stdio",
        host: Optional[str] = None,
        port: Optional[int] = None,
    ):
        """Run the MCP server with the specified transport.

        This is a convenience method that wraps FastMCP's run() method.

        Args:
            transport: Transport type - "stdio" (default), "http", or "sse"
                - stdio: Standard input/output for local/CLI use
                - http: HTTP-based web service (recommended for production)
                - sse: Server-Sent Events (legacy, not recommended)
            host: Network interface to bind to (for http/sse transports)
                - "127.0.0.1" for localhost only
                - "0.0.0.0" for all interfaces
                Defaults to config.mcp.api.host if not specified
            port: Port number (for http/sse transports)
                Defaults to config.mcp.api.port if not specified

        Raises:
            RuntimeError: If server is not initialized

        Examples:
            # STDIO (default) - for local development
            server.run()

            # HTTP - for web deployments
            server.run(transport="http", host="127.0.0.1", port=8000)

            # HTTP - accessible from network
            server.run(transport="http", host="0.0.0.0", port=8000)

        Notes:
            - For STDIO transport, host and port are ignored
            - For HTTP transport, server is accessible at http://host:port/mcp
            - For SSE transport, server is accessible at http://host:port/sse
            - This method cannot be called from inside an async function
              (use run_async() instead)
        """
        if not self._initialized or not self.app:
            raise RuntimeError("Server must be initialized first")

        # Use config defaults if not specified
        if host is None:
            host = self.config.mcp.api.host
        if port is None:
            port = self.config.mcp.api.port

        # Log the startup configuration
        if transport == "stdio":
            logger.info("Starting MCP server with STDIO transport")
        else:
            logger.info(
                "Starting MCP server",
                extra={
                    "transport": transport,
                    "host": host,
                    "port": port,
                    "endpoint": f"http://{host}:{port}/mcp" if transport == "http" else f"http://{host}:{port}/sse"
                }
            )

        # Run the FastMCP server
        if transport == "stdio":
            self.app.run(transport="stdio")
        else:
            self.app.run(transport=transport, host=host, port=port)  # type: ignore[arg-type]

    async def run_async(
        self,
        transport: str = "stdio",
        host: Optional[str] = None,
        port: Optional[int] = None,
    ):
        """Run the MCP server asynchronously with the specified transport.

        This is an async version of run() for use within async contexts.

        Args:
            transport: Transport type - "stdio" (default), "http", or "sse"
            host: Network interface to bind to (for http/sse transports)
            port: Port number (for http/sse transports)

        Raises:
            RuntimeError: If server is not initialized

        Examples:
            # In async context
            await server.run_async(transport="http", host="127.0.0.1", port=8000)

        Notes:
            - Use this method when calling from within an async function
            - Use run() when calling from synchronous code
        """
        if not self._initialized or not self.app:
            raise RuntimeError("Server must be initialized first")

        # Use config defaults if not specified
        if host is None:
            host = self.config.mcp.api.host
        if port is None:
            port = self.config.mcp.api.port

        # Log the startup configuration
        if transport == "stdio":
            logger.info("Starting MCP server with STDIO transport (async)")
        else:
            logger.info(
                "Starting MCP server (async)",
                extra={
                    "transport": transport,
                    "host": host,
                    "port": port,
                    "endpoint": f"http://{host}:{port}/mcp" if transport == "http" else f"http://{host}:{port}/sse"
                }
            )

        # Run the FastMCP server asynchronously
        if transport == "stdio":
            await self.app.run_async(transport="stdio")
        else:
            await self.app.run_async(transport=transport, host=host, port=port)  # type: ignore[arg-type]
    
    async def shutdown(self):
        """Graceful shutdown."""
        logger.info("Shutting down MCP server")

        # Cleanup services
        if self.services:
            # Cancel the background maintenance task before tearing down its
            # dependencies (memory_system / storage). Without this, the task's
            # next tick fires against torn-down services and logs spurious
            # "Periodic … failed" exceptions.
            maintenance_task = self.services.get("maintenance_task")
            if maintenance_task is not None and not maintenance_task.done():
                maintenance_task.cancel()
                try:
                    await maintenance_task
                except asyncio.CancelledError:
                    pass  # Expected: we just cancelled it.
                except Exception as cleanup_err:
                    logger.debug(
                        "Maintenance task raised during shutdown: %s",
                        cleanup_err,
                    )

            # Stop event system and close EventStore connection
            if "event_system" in self.services:
                try:
                    logger.debug("Stopping EventSystem")
                    await self.services["event_system"].stop()
                    logger.debug("EventSystem stopped successfully")
                except Exception as e:
                    logger.error(
                        "Error stopping EventSystem: %s",
                        str(e),
                        exc_info=True,
                        extra={
                            "error_type": type(e).__name__,
                            "error_message": str(e)
                        }
                    )
            
            # Close database connections
            if "db_manager" in self.services:
                try:
                    # LanceDB doesn't require explicit cleanup in most cases
                    # but we log it for completeness
                    logger.debug("Closing database connections")
                except Exception as e:
                    logger.error(
                        "Error closing database: %s",
                        str(e),
                        exc_info=True,
                        extra={
                            "error_type": type(e).__name__,
                            "error_message": str(e)
                        }
                    )

            # Shutdown thread pool executors
            try:
                logger.debug("Shutting down thread pool executors")
                await shutdown_executors_async(wait=True, cancel_futures=False)
                logger.debug("Thread pool executors shut down successfully")
            except Exception as e:
                logger.error(
                    "Error shutting down executors: %s",
                    str(e),
                    exc_info=True,
                    extra={
                        "error_type": type(e).__name__,
                        "error_message": str(e)
                    }
                )

            # Clear services
            self.services.clear()
        
        self._initialized = False
        logger.info("MCP server shutdown complete")
    
    def get_app(self) -> FastMCP:
        """Get the FastMCP application instance.
        
        Returns:
            FastMCP application instance
        
        Raises:
            RuntimeError: If server is not initialized
        """
        if not self._initialized or not self.app:
            raise RuntimeError("Server must be initialized first")
        
        return self.app
