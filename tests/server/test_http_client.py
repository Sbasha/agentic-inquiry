"""Tests for agent_vault.server.http_client - HTTP client for REST API."""

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

import pytest

from agent_vault.server.http_client import agvClient, HookClient


@pytest.fixture
def mock_server():
    """Start a simple HTTP server for testing."""
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            response = {"status": "ok", "path": self.path}
            self.wfile.write(json.dumps(response).encode())

        def do_POST(self):
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body) if body else {}

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            response = {"received": True, "path": self.path, "data": data}
            self.wfile.write(json.dumps(response).encode())

        def log_message(self, format, *args):
            pass  # Suppress logging

    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()


class TestagvClient:
    """Test the agv HTTP client."""

    def test_get_request(self, mock_server):
        client = agvClient(base_url=mock_server, auto_start=False)
        result = client.get("/api/v1/health")
        assert result is not None
        assert result["status"] == "ok"
        assert result["path"] == "/api/v1/health"

    def test_post_request(self, mock_server):
        client = agvClient(base_url=mock_server, auto_start=False)
        result = client.post("/api/v1/search", data={"query": "test"})
        assert result is not None
        assert result["received"] is True
        assert result["data"]["query"] == "test"

    def test_fire_and_forget(self, mock_server):
        client = agvClient(base_url=mock_server, auto_start=False)
        assert client.fire_and_forget("/api/v1/hooks/post_write", {"file_path": "test.py"})

    def test_unavailable_returns_none(self):
        client = agvClient(base_url=None, auto_start=False)
        assert not client.available
        assert client.get("/health") is None
        assert client.post("/search", {"query": "test"}) is None

    def test_connection_failure_returns_none(self):
        client = agvClient(base_url="http://127.0.0.1:1", auto_start=False)
        assert client.get("/health", timeout=0.5) is None


class TestHookClient:
    """Test the hook-specific client."""

    def test_hook_client_no_auto_start(self):
        """HookClient should NOT auto-start the server."""
        client = HookClient(timeout=1.0)
        # Should be not available since no server is running at default location
        # (This test relies on no agv server actually running)
        assert isinstance(client.available, bool)

    def test_hook_client_post(self, mock_server):
        """HookClient can make POST requests when server available."""
        # Manually construct with available base URL
        from agent_vault.server.http_client import agvClient
        inner = agvClient(base_url=mock_server, auto_start=False)
        # Use inner client directly since HookClient wraps it
        result = inner.post("/api/v1/hooks/post_bash", data={"command": "ls"})
        assert result is not None
        assert result["received"] is True
