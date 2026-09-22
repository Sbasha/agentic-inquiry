"""MCP tool implementations.

Simple function-based tools for FastMCP integration.
Each tool module exports async functions that take services dict as first parameter.
"""

# Import all tool modules for use in server registration
from agent_vault.mcp.tools import (
    session,
    memory,
    search,
    analysis,
    context,
    knowledge,
    info,
    direct_access,
)

__all__ = [
    "session",
    "memory",
    "search",
    "analysis",
    "context",
    "knowledge",
    "info",
    "direct_access",
]
