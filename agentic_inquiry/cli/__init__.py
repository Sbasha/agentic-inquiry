"""CLI commands for Agentic Inquiry.

This package provides command-line interface tools for:
- Database maintenance operations
- Schema migration and backup management
- Index migration utilities
- Lineage tracing and impact analysis
- Environment resolution and auto-start services
- Dynamic command discovery
"""

from agentic_inquiry.cli.env_resolver import (
    ResolvedEnvironment,
    resolve_environment,
    is_test_environment,
    should_auto_start_proxy,
)

from agentic_inquiry.cli.discover import (
    CommandInfo,
    discover_agv_commands,
    get_command_info,
)

__all__ = [
    # Environment resolution
    "ResolvedEnvironment",
    "resolve_environment",
    "is_test_environment",
    "should_auto_start_proxy",
    # Command discovery
    "CommandInfo",
    "discover_agv_commands",
    "get_command_info",
]
