"""CLI entry point for MCP server.

This module provides the command-line interface for starting and managing
the Agentic Inquiry MCP server.

Usage:
    # Start with default configuration
    python -m agentic_inquiry.mcp.cli --project-id my_project
    
    # With custom configuration
    python -m agentic_inquiry.mcp.cli --config custom.yaml --project-id my_project
    
    # Enable direct access tools
    python -m agentic_inquiry.mcp.cli --project-id my_project --enable-direct-tools
    
    # Specify host and port
    python -m agentic_inquiry.mcp.cli --project-id my_project --host 0.0.0.0 --port 9000
"""

import asyncio
import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

from agentic_inquiry.config import Config
from agentic_inquiry.mcp.server import MCPServer
from agentic_inquiry.mcp.utils.validation import validate_file_path, PathValidationError


# Configure initial logging to stderr (will be reconfigured in configure_logging)
# Using stderr by default since stdio transport uses stdout for JSON-RPC
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments.
    
    Returns:
        Parsed arguments namespace
    """
    parser = argparse.ArgumentParser(
        description="Agentic Inquiry MCP Server - AI-powered code and knowledge search",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Start with STDIO transport (default, for local CLI)
  %(prog)s --project-id my_project

  # Start with HTTP transport (for web service)
  %(prog)s --project-id my_project --transport http --host 127.0.0.1 --port 8000

  # HTTP transport accessible from network
  %(prog)s --project-id my_project --transport http --host 0.0.0.0 --port 8000

  # SSE transport (legacy, not recommended)
  %(prog)s --project-id my_project --transport sse --port 8000

  # With custom configuration file
  %(prog)s --config custom.yaml --project-id my_project --transport http

  # Enable direct access tools
  %(prog)s --project-id my_project --enable-direct-tools

  # Enable debug logging
  %(prog)s --project-id my_project --log-level DEBUG
        """
    )
    
    # Configuration
    parser.add_argument(
        "--config",
        type=str,
        help="Path to configuration file (default: uses Config.load() defaults)"
    )
    
    # Project
    parser.add_argument(
        "--project-id",
        type=str,
        required=True,
        help="Project identifier (required)"
    )
    
    # Tool configuration
    parser.add_argument(
        "--enable-direct-tools",
        action="store_true",
        help="Enable direct access tools (default: disabled)"
    )
    
    # Server configuration
    parser.add_argument(
        "--transport",
        type=str,
        choices=["stdio", "http", "sse"],
        default="stdio",
        help="Transport type (default: stdio). Options: stdio (local CLI), http (web service), sse (legacy)"
    )

    parser.add_argument(
        "--host",
        type=str,
        help="Server host for http/sse transports (overrides config, default: 127.0.0.1)"
    )

    parser.add_argument(
        "--port",
        type=int,
        help="Server port for http/sse transports (overrides config, default: 8765)"
    )
    
    # Logging
    parser.add_argument(
        "--log-level",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default="INFO",
        help="Logging level (default: INFO)"
    )
    
    parser.add_argument(
        "--log-file",
        type=str,
        help="Log file path (default: logs to console only)"
    )
    
    return parser.parse_args()


def configure_logging(log_level: str, log_file: Optional[str] = None, transport: str = "stdio"):
    """Configure logging based on CLI arguments.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Optional log file path
        transport: Transport type - when "stdio", logs go to stderr to avoid
            corrupting JSON-RPC protocol on stdout
    """
    # Set root logger level
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level))

    # Clear existing handlers
    root_logger.handlers.clear()

    # Console handler - use stderr for stdio transport to avoid corrupting JSON-RPC
    stream = sys.stderr if transport == "stdio" else sys.stdout
    console_handler = logging.StreamHandler(stream)
    console_handler.setLevel(getattr(logging, log_level))
    console_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)
    
    # File handler (if specified)
    if log_file:
        # Validate log file path for security
        import os
        project_root = Path(os.getcwd())
        try:
            log_path = validate_file_path(log_file, project_root, must_exist=False)
        except PathValidationError as e:
            logger.error("Invalid log file path: %s", e)
            sys.stderr.write(f"Error: Invalid log file path - {e}\n")
            sys.stderr.write("Please use a path within the project directory.\n")
            sys.exit(1)
        
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        file_handler = logging.FileHandler(log_path)
        file_handler.setLevel(getattr(logging, log_level))
        file_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)
        
        logger.info("Logging to file: %s", log_file)


def load_configuration(config_path: Optional[str] = None) -> Config:
    """Load configuration from file or defaults.
    
    Args:
        config_path: Optional path to configuration file
        
    Returns:
        Configuration object
        
    Raises:
        FileNotFoundError: If config file doesn't exist
        PathValidationError: If config path is outside project directory
        Exception: If config loading fails
    """
    try:
        if config_path:
            # Validate config file path for security
            import os
            project_root = Path(os.getcwd())
            try:
                config_file = validate_file_path(config_path, project_root, must_exist=False)
            except PathValidationError as e:
                logger.error("Invalid config file path: %s", e)
                sys.stderr.write(f"Error: Invalid config file path - {e}\n")
                sys.stderr.write("Please use a path within the project directory.\n")
                sys.exit(1)
            
            if not config_file.exists():
                raise FileNotFoundError(f"Configuration file not found: {config_path}")
            
            logger.info("Loading configuration from: %s", config_path)
            config = Config.load(str(config_file))
        else:
            logger.info("Loading default configuration")
            config = Config.load()
        
        return config
        
    except Exception as e:
        logger.error("Failed to load configuration: %s", e)
        raise


def apply_cli_overrides(config: Config, args: argparse.Namespace) -> Config:
    """Apply CLI argument overrides to configuration.

    Args:
        config: Base configuration
        args: Parsed CLI arguments

    Returns:
        Modified configuration
    """
    # Enable direct access tools if requested
    if args.enable_direct_tools:
        logger.info("Enabling direct access tools (CLI override)")
        config.mcp.tools.direct_access["enabled"] = True

    # Override host if specified
    if args.host:
        logger.info("Setting host to %s (CLI override)", args.host)
        config.mcp.api.host = args.host

    # Override port if specified
    if args.port:
        logger.info("Setting port to %s (CLI override)", args.port)
        config.mcp.api.port = args.port

    return config


async def run_server(config: Config, project_id: str, transport: str, host: Optional[str], port: Optional[int]):
    """Run the MCP server.

    Args:
        config: Configuration object
        project_id: Project identifier
        transport: Transport type (stdio, http, or sse)
        host: Optional host override
        port: Optional port override
    """
    server = None

    try:
        # Create server
        logger.info("Creating MCP server")
        server = MCPServer(config=config, project_id=project_id)

        # Initialize server
        logger.info("Initializing MCP server")
        await server.initialize()

        # Start server with specified transport
        # Note: For stdio transport, we need to use run() not run_async()
        # because FastMCP.run() handles its own event loop for stdio
        if transport == "stdio":
            logger.info("MCP server ready with STDIO transport")
            logger.info("Press Ctrl+C to stop")

            # For stdio, we need to exit the async context and call run()
            # This is a bit awkward but required by FastMCP's design
            # We'll handle this by returning the server and letting the caller run it
            return server, transport, host, port
        else:
            # For http/sse, we can use run_async
            logger.info(
                "Starting MCP server",
                extra={
                    "transport": transport,
                    "host": host or config.mcp.api.host,
                    "port": port or config.mcp.api.port
                }
            )
            await server.run_async(transport=transport, host=host, port=port)

    except KeyboardInterrupt:
        logger.info("Received shutdown signal")
    except Exception as e:
        logger.error("Server error: %s", e, exc_info=True)
        raise
    finally:
        # Shutdown server
        if server and transport != "stdio":
            logger.info("Shutting down MCP server")
            await server.shutdown()


async def async_main():
    """Async main entry point."""
    # Parse arguments
    args = parse_arguments()

    # Configure logging - pass transport so stdio mode logs to stderr
    configure_logging(args.log_level, args.log_file, args.transport)

    logger.info("Starting Agentic Inquiry MCP Server")
    logger.info("Project ID: %s", args.project_id)
    logger.info("Transport: %s", args.transport)

    try:
        # Load configuration
        config = load_configuration(args.config)

        # Apply CLI overrides
        config = apply_cli_overrides(config, args)

        # Check if MCP is enabled
        if not config.mcp.enabled:
            logger.error("MCP is not enabled in configuration")
            logger.error("Set 'mcp.enabled: true' in your configuration file")
            sys.exit(1)

        # Run server
        result = await run_server(config, args.project_id, args.transport, args.host, args.port)

        # If stdio transport, we need to handle it specially
        if result and args.transport == "stdio":
            server, transport, host, port = result
            # Exit async context and run stdio server synchronously
            return server, transport, host, port

    except KeyboardInterrupt:
        logger.info("Shutdown complete")
    except Exception as e:
        logger.error("Fatal error: %s", e, exc_info=True)
        sys.exit(1)


def main():
    """Main entry point."""
    try:
        # Run async initialization
        result = asyncio.run(async_main())

        # If stdio transport, run the server synchronously
        if result:
            server, transport, host, port = result
            try:
                server.run(transport=transport, host=host, port=port)
            except KeyboardInterrupt:
                logger.info("Received shutdown signal")
            finally:
                # Cleanup
                asyncio.run(server.shutdown())

    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
