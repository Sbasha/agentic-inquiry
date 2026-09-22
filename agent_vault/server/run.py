"""agv Server runner - entry point for background server process.

Usage:
    python -m agent_vault.server.run --port 8765 --project-id default
    python -m agent_vault.server.run --port 8766 --project-id default --env test
"""

import argparse
import asyncio
import logging
import signal
import sys

import uvicorn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("agv.server.run")


def parse_args():
    parser = argparse.ArgumentParser(description="agv Server")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--project-id", default="default")
    parser.add_argument("--workspace", default=None)
    parser.add_argument("--env", default="default")
    return parser.parse_args()


async def _start_server():
    args = parse_args()
    
    # Create app via async factory
    from agent_vault.server.app import create_app
    app = await create_app(
        project_id=args.project_id,
        workspace=args.workspace,
    )

    # Write PID file
    from agent_vault.server.lifecycle import write_pid_file, remove_pid_file
    import os
    write_pid_file(os.getpid(), args.port, args.project_id, env=args.env)

    logger.info("Starting agv server on 0.0.0.0:%d (env=%s)", args.port, args.env)

    # We use uvicorn directly but make sure we don't block the loop incorrectly
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=args.port,
        log_level="info",
        ws_ping_interval=30,
        ws_ping_timeout=30,
    )
    server = uvicorn.Server(config)
    await server.serve()
    remove_pid_file(env=args.env)


def main():
    asyncio.run(_start_server())


if __name__ == "__main__":
    main()
