"""Agentic Inquiry Command Line Interface.

This is the main entry point for the Agentic Inquiry system.

Commands:
    ai                     Interactive client (connect to running server)
    ai setup               Setup wizard
    ai serve               Start MCP server
    ai index [PATH]        Index a codebase
    ai search <query>      Semantic search
    ai entity <name>       Understand a code entity
    ai memory save|recall  Manage memories
    ai patterns            Discover code patterns
    ai lineage             Trace data lineage
    ai services            Detect service architecture
    ai validate            Validate index accuracy
    ai agent-test          Execute agent test scenarios
"""

import os
import sys
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def _should_skip_auto_start() -> bool:
    """Check if auto-start services should be skipped.

    Returns:
        True if auto-start should be skipped
    """
    # Check CLI flag
    if "--no-auto-start" in sys.argv:
        sys.argv.remove("--no-auto-start")
        return True

    # Check env vars
    if os.environ.get("INQUIRY_NO_AUTO_START", "").lower() in ("1", "true", "yes"):
        return True

    if os.environ.get("INQUIRY_TEST_MODE", "").lower() in ("1", "true", "yes"):
        return True

    return False


def _ensure_services_running() -> None:
    """Local providers need no service startup; kept for the command entry sequence."""
    return None


def print_help() -> None:
    """Print main help message."""
    print("""
Agentic Inquiry - AI-Powered Code Understanding

Usage: ai <command> [options]

Commands:
  Setup & Server:
    setup               Run setup wizard (local LanceDB environment)
    serve               Start MCP server
    server start        Start ai REST+MCP server
    server stop         Stop running server
    server status       Show server status
    server restart      Restart server

  Indexing:
    index [PATH]        Index a codebase for search
    index status        Show index statistics
    onboard start       Record the start of an onboard run
    onboard complete    Mark an onboard run completed

  Search & Discovery:
    search <query>      Semantic search across code and docs
    search similar <n>  Find similar code entities
    entity <name>       Understand a code entity
    entity deps <name>  Show entity dependencies
    entity refs <name>  Show entity references
    patterns            List discovered patterns
    patterns discover   Analyze codebase for patterns

  Analysis:
    lineage trace <e>   Trace data lineage
    lineage impact <e>  Analyze change impact
    lineage gaps <e>    Find lineage gaps
    services detect     Detect service architecture
    services show       Show service map
    validate            Validate index accuracy

  Memory:
    memory save <text>  Save a memory
    memory recall <q>   Recall memories by query
    memory list         List all memories

  Testing:
    agent-test list     List available agent tests
    agent-test <ID>     Run a specific agent test (01-15)
    agent-test --all    Run all agent tests
    agent-test status   Show test run status

  Interactive:
    (no command)        Connect to running server
    shell               Interactive shell

Examples:
  ai index .                          # Index current directory
  ai search "authentication flow"     # Search for auth code
  ai entity authenticate_user         # Understand a function
  ai lineage impact User              # Analyze change impact
  ai memory save "Auth uses JWT"      # Save insight

Environment:
  INQUIRY_PROJECT_ID      Default project ID
  INQUIRY_CONFIG          Path to config file
  OPENAI_API_KEY      Required ONLY for OpenAI-based embeddings
""")


def _parse_server_flags(args: list[str]) -> dict:
    """Parse --port, --project-id, --env flags from server command args."""
    result = {
        "port": None,
        "project_id": os.environ.get("INQUIRY_PROJECT_ID", "default"),
        "env": os.environ.get("INQUIRY_SERVER_ENV", "default"),
    }
    i = 0
    while i < len(args):
        if args[i] == "--port" and i + 1 < len(args):
            result["port"] = int(args[i + 1])
            i += 2
        elif args[i] == "--project-id" and i + 1 < len(args):
            result["project_id"] = args[i + 1]
            i += 2
        elif args[i] == "--env" and i + 1 < len(args):
            result["env"] = args[i + 1]
            i += 2
        else:
            i += 1
    return result


def _print_server_status(status: dict) -> None:
    """Print a single server's status."""
    env = status.get("env", "default")
    if status.get("running"):
        print(
            f"  [{env}] running  pid={status['pid']}  port={status['port']}  "
            f"project={status.get('project_id', '?')[:12]}  "
            f"healthy={status.get('healthy', '?')}"
        )
    else:
        msg = f"  [{env}] not running"
        if status.get("stale_pid_cleaned"):
            msg += " (cleaned stale PID)"
        print(msg)


def _handle_server_command() -> None:
    """Handle `ai server <subcommand>` commands.

    Supports --env flag for environment-aware server management:
        ai server start --env test    # Start test server on port 8766
        ai server stop --env test     # Stop test server
        ai server status              # Show all servers
    """
    from agentic_inquiry.server.lifecycle import (
        all_servers_status,
        server_status,
        start_server,
        stop_server,
    )

    subcommand = sys.argv[2] if len(sys.argv) > 2 else "status"
    flags = _parse_server_flags(sys.argv[3:])

    if subcommand == "start":
        info = start_server(
            project_id=flags["project_id"],
            port=flags["port"],
            wait=True,
            env=flags["env"],
        )
        if info:
            print(
                f"ai server started: env={flags['env']} pid={info['pid']} port={info['port']}"
            )
        else:
            print("Failed to start ai server", file=sys.stderr)
            sys.exit(1)

    elif subcommand == "stop":
        if stop_server(env=flags["env"]):
            print(f"ai server stopped (env={flags['env']})")
        else:
            print(f"ai server is not running (env={flags['env']})")

    elif subcommand == "restart":
        stop_server(env=flags["env"])
        import time

        time.sleep(0.5)
        info = start_server(wait=True, env=flags["env"])
        if info:
            print(
                f"ai server restarted: env={flags['env']} pid={info['pid']} port={info['port']}"
            )
        else:
            print("Failed to restart ai server", file=sys.stderr)
            sys.exit(1)

    elif subcommand == "status":
        # Show all servers by default, or specific env with --env
        if "--env" in sys.argv[3:]:
            statuses = [server_status(env=flags["env"])]
        else:
            statuses = all_servers_status()
            if not statuses:
                statuses = [server_status()]  # Check default even if no PID files

        print("ai servers:")
        any_running = False
        for status in statuses:
            _print_server_status(status)
            if status.get("running"):
                any_running = True
        if not any_running:
            print("  (no servers running)")

    else:
        print(f"Unknown server command: {subcommand}")
        print("Usage: ai server [start|stop|status|restart] [--env ENV]")
        sys.exit(1)


def main():
    """Main CLI entry point."""
    from agentic_inquiry.cli.client import connect_or_setup

    # No args -> help or client
    if len(sys.argv) == 1:
        connect_or_setup()
        return

    command = sys.argv[1]

    # Help - no services needed
    if command in ("-h", "--help", "help"):
        print_help()
        return

    # Setup wizard - no services needed
    if command == "setup":
        from agentic_inquiry.cli.setup_wizard import run_setup

        success = run_setup(sys.argv[2:])
        sys.exit(0 if success else 1)

    # For all other commands, ensure required services are running
    # (e.g., Cloud SQL Proxy for PostgreSQL backends)
    _ensure_services_running()

    # ai Server (REST + MCP dual-surface)
    if command == "server":
        _handle_server_command()
        return

    # MCP Server (legacy)
    if command == "serve":
        sys.argv.pop(1)
        from agentic_inquiry.mcp.cli import main as mcp_main

        mcp_main()
        return

    # Index
    if command == "index":
        sys.argv.pop(1)
        from agentic_inquiry.cli.index import main as index_main

        sys.exit(index_main())

    # Onboard metadata
    if command == "onboard":
        sys.argv.pop(1)
        from agentic_inquiry.cli.onboard import main as onboard_main

        sys.exit(onboard_main())

    # Search
    if command == "search":
        sys.argv.pop(1)
        from agentic_inquiry.cli.search import main as search_main

        sys.exit(search_main())

    # Entity
    if command == "entity":
        sys.argv.pop(1)
        from agentic_inquiry.cli.entity import main as entity_main

        sys.exit(entity_main())

    # Memory
    if command == "memory":
        sys.argv.pop(1)
        from agentic_inquiry.cli.memory import main as memory_main

        sys.exit(memory_main())

    # Patterns
    if command == "patterns":
        sys.argv.pop(1)
        from agentic_inquiry.cli.patterns import main as patterns_main

        sys.exit(patterns_main())

    # Lineage
    if command == "lineage":
        sys.argv.pop(1)
        from agentic_inquiry.cli.lineage import main as lineage_main

        sys.exit(lineage_main())

    # Services
    if command == "services":
        sys.argv.pop(1)
        from agentic_inquiry.cli.services import main as services_main

        sys.exit(services_main())

    # Validate
    if command == "validate":
        sys.argv.pop(1)
        from agentic_inquiry.cli.validate import main as validate_main

        sys.exit(validate_main())

    # Agent Test
    if command == "agent-test":
        sys.argv.pop(1)
        from agentic_inquiry.cli.agent_test import main as agent_test_main

        sys.exit(agent_test_main())

    # Shell
    if command == "shell":
        connect_or_setup()
        return

    # Unknown command - check if it looks like a project ID (legacy)
    if command.startswith("--") or command.startswith("-"):
        # Flags - pass to MCP server (legacy behavior)
        from agentic_inquiry.mcp.cli import main as mcp_main

        mcp_main()
        return

    # Unknown command
    print(f"Unknown command: {command}")
    print("Run 'ai --help' for usage information.")
    sys.exit(1)


if __name__ == "__main__":
    main()
