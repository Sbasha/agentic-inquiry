"""Agentic Inquiry Cloud Run entrypoint.

The platform sets ``INQUIRY_SERVER_HOST=0.0.0.0``. A non-loopback value is
refused unless ``INQUIRY_MCP_API_AUTH_API_KEY`` is set. An unset host binds
loopback.
"""

import asyncio
import logging
import os
import sys

import uvicorn

logging.basicConfig(level=logging.INFO)


def _host() -> str:
    from agentic_inquiry.server.bind import bind_host

    requested = os.environ.get("INQUIRY_SERVER_HOST")
    key = os.environ.get("INQUIRY_MCP_API_AUTH_API_KEY", "")
    try:
        return bind_host(requested, auth_enabled=bool(key.strip()))
    except ValueError:
        sys.stderr.write(
            "INQUIRY_SERVER_HOST is not a loopback address. "
            "Configure the API-key setting INQUIRY_MCP_API_AUTH_API_KEY "
            "before binding any other address.\n"
        )
        raise SystemExit(1) from None


async def main() -> None:
    from agentic_inquiry.server.app import create_app

    host = _host()
    app = await create_app(
        project_id=os.environ.get("INQUIRY_PROJECT_ID", "default"),
    )
    config = uvicorn.Config(
        app,
        host=host,
        port=int(os.environ.get("PORT", "8080")),
        log_level="info",
    )
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
