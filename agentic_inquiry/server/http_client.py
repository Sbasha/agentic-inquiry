"""HTTP client for ai server REST API.

Used by CLI commands and hook scripts to communicate with the server.
Handles server discovery, auto-start, and request/response serialization.

Supports environment-aware routing:
  - agvClient(env="default") → production server (port 8765)
  - agvClient(env="test")    → test server (port 8766)
"""

import json
import logging
import urllib.error
import urllib.request

from agentic_inquiry.server.lifecycle import ENV_DEFAULT, ensure_server, get_server_url

logger = logging.getLogger("ai.server.client")


class agvClient:
    """HTTP client for the ai REST API.

    Discovers the running server from PID file, auto-starts if needed.
    Uses urllib (stdlib) to avoid adding httpx dependency for hook scripts.
    """

    def __init__(
        self,
        base_url: str | None = None,
        project_id: str = "default",
        workspace: str | None = None,
        auto_start: bool = True,
        timeout: float = 30.0,
        env: str = ENV_DEFAULT,
    ):
        self.timeout = timeout
        self.env = env
        self._base_url = base_url

        if not self._base_url:
            if auto_start:
                self._base_url = ensure_server(
                    project_id=project_id, workspace=workspace, env=env,
                )
            else:
                self._base_url = get_server_url(env)

    @property
    def available(self) -> bool:
        """Whether the server is reachable."""
        return self._base_url is not None

    def get(self, path: str, timeout: float | None = None) -> dict | None:
        """Send a GET request.

        Returns:
            Response dict or None on failure.
        """
        if not self._base_url:
            return None
        return self._request("GET", path, timeout=timeout)

    def post(self, path: str, data: dict | None = None, timeout: float | None = None) -> dict | None:
        """Send a POST request.

        Returns:
            Response dict or None on failure.
        """
        if not self._base_url:
            return None
        return self._request("POST", path, data=data, timeout=timeout)

    def fire_and_forget(self, path: str, data: dict) -> bool:
        """Send a POST request without waiting for full response.

        Returns:
            True if request was sent successfully.
        """
        if not self._base_url:
            return False
        try:
            self._request("POST", path, data=data, timeout=1.0)
            return True
        except Exception:
            return False

    def _request(
        self,
        method: str,
        path: str,
        data: dict | None = None,
        timeout: float | None = None,
    ) -> dict | None:
        """Send an HTTP request to the server."""
        url = f"{self._base_url}{path}"
        timeout = timeout or self.timeout

        body = None
        if data is not None:
            body = json.dumps(data).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=body,
            method=method,
            headers={"Content-Type": "application/json"} if body else {},
        )

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            try:
                error_body = json.loads(e.read())
                logger.debug("Server error %d: %s", e.code, error_body)
                return error_body
            except Exception:
                logger.debug("Server error %d", e.code)
                return {"error": f"HTTP {e.code}", "code": "HTTP_ERROR"}
        except urllib.error.URLError as e:
            logger.debug("Connection failed: %s", e.reason)
            return None
        except Exception:
            logger.debug("Request failed", exc_info=True)
            return None


class HookClient:
    """Lightweight client for hook scripts.

    Does NOT auto-start the server - hooks should not block on server startup.
    Uses short timeouts appropriate for hook execution.

    Always targets the production ("default") server unless explicitly overridden.
    """

    def __init__(self, timeout: float = 2.0, env: str = ENV_DEFAULT):
        self._client = agvClient(auto_start=False, timeout=timeout, env=env)

    @property
    def available(self) -> bool:
        return self._client.available

    def post(self, path: str, data: dict | None = None, timeout: float | None = None) -> dict | None:
        return self._client.post(path, data, timeout=timeout)

    def fire_and_forget(self, path: str, data: dict) -> bool:
        return self._client.fire_and_forget(path, data)
