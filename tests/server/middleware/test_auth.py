"""Tests for APIKeyAuthMiddleware (T40).

Covers:
- Auth disabled (pass-through for all requests)
- Valid bearer token grants access
- Missing token returns 401
- Invalid token returns 401
- Exempt paths bypass auth (/health, /docs, /openapi.json, /api/v1/health)
- Exempt prefixes bypass auth (/mcp, /ui)
- request_id set on state
- X-ai-User header logged on success
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from agentic_inquiry.server.middleware.auth import APIKeyAuthMiddleware, EXEMPT_PATHS, EXEMPT_PREFIXES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_app(auth_config: dict) -> FastAPI:
    """Create a minimal FastAPI app with the auth middleware attached."""
    app = FastAPI()
    app.add_middleware(APIKeyAuthMiddleware, auth_config=auth_config)

    @app.get("/api/v1/search")
    async def protected():
        return {"ok": True}

    @app.get("/api/v1/health")
    async def health():
        return {"status": "ok"}

    @app.get("/health")
    async def health_root():
        return {"status": "ok"}

    @app.get("/docs")
    async def docs():
        return {"docs": True}

    @app.get("/openapi.json")
    async def openapi():
        return {}

    @app.get("/mcp/tools")
    async def mcp_tools():
        return {"tools": []}

    @app.get("/ui/index.html")
    async def ui():
        return {"ui": True}

    return app


_AUTH_CONFIG_DISABLED = {"enabled": False}
_AUTH_CONFIG_ENABLED = {"enabled": True, "api_key": "secret-key-123"}


# ---------------------------------------------------------------------------
# T40-1: Auth disabled — all requests pass through
# ---------------------------------------------------------------------------

class TestAuthDisabled:
    """When auth is disabled the middleware must never reject a request."""

    def test_passes_without_any_auth_header(self):
        client = TestClient(_build_app(_AUTH_CONFIG_DISABLED))
        resp = client.get("/api/v1/search")
        assert resp.status_code == 200

    def test_passes_with_bogus_token(self):
        client = TestClient(_build_app(_AUTH_CONFIG_DISABLED))
        resp = client.get("/api/v1/search", headers={"Authorization": "Bearer garbage"})
        assert resp.status_code == 200

    def test_passes_with_no_headers_at_all(self):
        client = TestClient(_build_app(_AUTH_CONFIG_DISABLED))
        resp = client.get("/api/v1/search", headers={})
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# T40-2: Auth enabled — valid bearer token
# ---------------------------------------------------------------------------

class TestValidBearer:
    """Requests carrying the correct API key must be allowed through."""

    def test_valid_key_passes(self):
        client = TestClient(_build_app(_AUTH_CONFIG_ENABLED))
        resp = client.get(
            "/api/v1/search",
            headers={"Authorization": "Bearer secret-key-123"},
        )
        assert resp.status_code == 200

    def test_valid_key_with_x_agv_user_header(self):
        """X-ai-User header must not break auth flow."""
        client = TestClient(_build_app(_AUTH_CONFIG_ENABLED))
        resp = client.get(
            "/api/v1/search",
            headers={
                "Authorization": "Bearer secret-key-123",
                "X-ai-User": "alice",
            },
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# T40-3: Missing token → 401
# ---------------------------------------------------------------------------

class TestMissingToken:
    """Requests without an Authorization header must be rejected with 401."""

    def test_no_auth_header_returns_401(self):
        client = TestClient(_build_app(_AUTH_CONFIG_ENABLED))
        resp = client.get("/api/v1/search")
        assert resp.status_code == 401

    def test_401_response_has_auth_required_code(self):
        client = TestClient(_build_app(_AUTH_CONFIG_ENABLED))
        resp = client.get("/api/v1/search")
        body = resp.json()
        assert body.get("code") == "AUTH_REQUIRED"

    def test_non_bearer_scheme_returns_401(self):
        """Basic auth scheme must not be treated as a bearer token."""
        client = TestClient(_build_app(_AUTH_CONFIG_ENABLED))
        resp = client.get(
            "/api/v1/search",
            headers={"Authorization": "Basic dXNlcjpwYXNz"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# T40-4: Invalid token → 401
# ---------------------------------------------------------------------------

class TestInvalidToken:
    """Requests with a wrong API key must be rejected with 401."""

    def test_wrong_key_returns_401(self):
        client = TestClient(_build_app(_AUTH_CONFIG_ENABLED))
        resp = client.get(
            "/api/v1/search",
            headers={"Authorization": "Bearer wrong-key"},
        )
        assert resp.status_code == 401

    def test_wrong_key_has_invalid_token_code(self):
        client = TestClient(_build_app(_AUTH_CONFIG_ENABLED))
        resp = client.get(
            "/api/v1/search",
            headers={"Authorization": "Bearer wrong-key"},
        )
        body = resp.json()
        assert body.get("code") == "INVALID_TOKEN"

    def test_empty_bearer_value_returns_401(self):
        """'Bearer ' with no value must be rejected."""
        client = TestClient(_build_app(_AUTH_CONFIG_ENABLED))
        resp = client.get(
            "/api/v1/search",
            headers={"Authorization": "Bearer "},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# T40-5: Exempt paths bypass auth
# ---------------------------------------------------------------------------

class TestExemptPaths:
    """Exact-match exempt paths must bypass auth even when enabled."""

    @pytest.mark.parametrize("path", sorted(EXEMPT_PATHS))
    def test_exempt_path_bypasses_auth(self, path: str):
        client = TestClient(_build_app(_AUTH_CONFIG_ENABLED))
        resp = client.get(path)
        # 404 is fine — it means the middleware let the request through
        # (the test app may not have registered a handler for every exempt path).
        assert resp.status_code != 401

    def test_health_endpoint_no_auth(self):
        client = TestClient(_build_app(_AUTH_CONFIG_ENABLED))
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_api_v1_health_no_auth(self):
        client = TestClient(_build_app(_AUTH_CONFIG_ENABLED))
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200

    def test_docs_no_auth(self):
        client = TestClient(_build_app(_AUTH_CONFIG_ENABLED))
        resp = client.get("/docs")
        assert resp.status_code == 200

    def test_openapi_json_no_auth(self):
        client = TestClient(_build_app(_AUTH_CONFIG_ENABLED))
        resp = client.get("/openapi.json")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# T40-6: Exempt prefixes bypass auth
# ---------------------------------------------------------------------------

class TestExemptPrefixes:
    """Paths starting with exempt prefixes must bypass auth."""

    def test_mcp_prefix_bypasses_auth(self):
        client = TestClient(_build_app(_AUTH_CONFIG_ENABLED))
        resp = client.get("/mcp/tools")
        assert resp.status_code != 401

    def test_ui_prefix_bypasses_auth(self):
        client = TestClient(_build_app(_AUTH_CONFIG_ENABLED))
        resp = client.get("/ui/index.html")
        assert resp.status_code != 401

    @pytest.mark.parametrize("prefix", EXEMPT_PREFIXES)
    def test_sub_path_of_prefix_bypasses_auth(self, prefix: str):
        """Any path that starts with an exempt prefix must be allowed."""
        client = TestClient(_build_app(_AUTH_CONFIG_ENABLED))
        resp = client.get(f"{prefix}/some/deep/path")
        assert resp.status_code != 401


# ---------------------------------------------------------------------------
# T40-7: request_id is always set on request.state
# ---------------------------------------------------------------------------

class TestRequestIdState:
    """The middleware must set request.state.request_id on every request."""

    def test_request_id_set_when_auth_disabled(self):
        """Even when auth is off, the request_id must be set."""
        app = FastAPI()
        app.add_middleware(APIKeyAuthMiddleware, auth_config=_AUTH_CONFIG_DISABLED)

        @app.get("/check-state")
        async def check_state(req: Request):
            # request_id should be accessible
            rid = req.state.request_id
            return {"request_id": rid}

        client = TestClient(app)
        resp = client.get("/check-state")
        assert resp.status_code == 200
        data = resp.json()
        rid = data.get("request_id", "")
        # The request_id is an 8-char hex string (first 8 chars of uuid4)
        assert isinstance(rid, str) and len(rid) == 8

    def test_request_id_set_when_auth_enabled_and_valid(self):
        app = FastAPI()
        app.add_middleware(APIKeyAuthMiddleware, auth_config=_AUTH_CONFIG_ENABLED)

        @app.get("/check-state")
        async def check_state(req: Request):
            return {"request_id": req.state.request_id}

        client = TestClient(app)
        resp = client.get(
            "/check-state",
            headers={"Authorization": "Bearer secret-key-123"},
        )
        assert resp.status_code == 200
        rid = resp.json().get("request_id", "")
        assert isinstance(rid, str) and len(rid) == 8


# ---------------------------------------------------------------------------
# T40-8: Middleware constants sanity checks
# ---------------------------------------------------------------------------

class TestMiddlewareConstants:
    """EXEMPT_PATHS and EXEMPT_PREFIXES must cover expected values."""

    def test_exempt_paths_includes_health(self):
        assert "/health" in EXEMPT_PATHS

    def test_exempt_paths_includes_docs(self):
        assert "/docs" in EXEMPT_PATHS

    def test_exempt_prefixes_includes_mcp(self):
        assert any(p.startswith("/mcp") for p in EXEMPT_PREFIXES)

    def test_exempt_prefixes_includes_ui(self):
        assert any(p.startswith("/ui") for p in EXEMPT_PREFIXES)
