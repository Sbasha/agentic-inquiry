"""Agent-Vault Cloud Run entrypoint."""

import asyncio
import logging
import os

import uvicorn

logging.basicConfig(level=logging.INFO)


async def main() -> None:
    from agent_vault.server.app import create_app

    app = await create_app(
        project_id=os.environ.get("agv_PROJECT_ID", "default"),
    )
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8080")),
        log_level="info",
    )
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
