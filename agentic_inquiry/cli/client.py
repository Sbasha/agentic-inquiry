"""Interactive client for Agentic Inquiry MCP Server."""

import sys
import json
import logging
import urllib.request
import urllib.error
import urllib.parse
from typing import Dict, Any, Optional, List
from pathlib import Path

from agentic_inquiry.cli.env_resolver import load_config_for_environment

logger = logging.getLogger(__name__)

class agvClient:
    """Client for interacting with a running ai MCP server."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8000):
        self.base_url = f"http://{host}:{port}"
        self.tools_url = f"{self.base_url}/mcp/tools"
        # FastMCP usually exposes tools via JSON-RPC or REST-like endpoints depending on configuration.
        # For simplicity, we'll assume standard MCP-over-HTTP if available, 
        # or just check health first.
        # FastMCP default HTTP transport exposes SSE at /sse and messages at /message?
        # Let's check if we can hit the server root or health.
        
    def is_server_running(self) -> bool:
        """Check if the server is responsive."""
        try:
            # FastMCP doesn't strictly define a /health endpoint by default, 
            # but we can try to connect.
            # We'll try hitting the docs endpoint or root.
            with urllib.request.urlopen(self.base_url, timeout=1) as response:
                return response.status in (200, 404)
        except urllib.error.URLError:
            return False
        except Exception:
            return False

    def list_tools(self) -> List[Dict[str, Any]]:
        """List available tools (simulated for now as RPC is complex over raw HTTP)."""
        # In a real implementation, this would query the MCP discovery endpoint.
        # For now, we'll return a static list or try to implement JSON-RPC over HTTP if supported.
        return []

    def call_tool(self, tool_name: str, args: Dict[str, Any]) -> Any:
        """Call a tool via JSON-RPC over HTTP (simulated)."""
        # This requires the server to support JSON-RPC over HTTP POST.
        # FastMCP supports this via the /messages endpoint typically?
        # For now, we will just print what would happen.
        print(f"Calling {tool_name} with {args} on {self.base_url}...")
        print("Note: interactive tool execution via HTTP is pending full MCP client implementation.")
        return None

def run_shell(host: str, port: int):
    """Run an interactive shell."""
    client = agvClient(host, port)
    
    if not client.is_server_running():
        print(f"❌ No server detected at http://{host}:{port}")
        print("Run 'ai setup' to configure or 'ai serve' to start the server.")
        return

    print(f"✅ Connected to Agentic Inquiry Server at http://{host}:{port}")
    print("Interactive shell (type 'exit' to quit, 'help' for info)")
    
    while True:
        try:
            command = input("ai> ").strip()
            if not command:
                continue
            
            if command in ("exit", "quit"):
                break
            
            if command == "help":
                print("Available commands:")
                print("  <tool> <key>=<value> ... : Call a tool")
                print("  exit                     : Quit shell")
                continue
                
            parts = command.split()
            tool = parts[0]
            args = {}
            for part in parts[1:]:
                if "=" in part:
                    k, v = part.split("=", 1)
                    args[k] = v
            
            client.call_tool(tool, args)
            
        except KeyboardInterrupt:
            print()
            break
        except Exception as e:
            print(f"Error: {e}")

def connect_or_setup():
    """Entry point for client connection."""
    # Load config to find port
    try:
        config = load_config_for_environment()
        host = config.mcp.api.host
        port = config.mcp.api.port
    except Exception:
        # Defaults
        host = "127.0.0.1"
        port = 8000

    client = agvClient(host, port)
    
    if client.is_server_running():
        run_shell(host, port)
    else:
        print("Agentic Inquiry Server is not running.")
        print("To start the server: ai serve")
        print("To configure setup:  ai setup")
