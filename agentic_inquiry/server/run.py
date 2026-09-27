"""ai Server runner - entry point for background server process.

Usage:
    python -m agentic_inquiry.server.run --port 8765 --project-id default
    python -m agentic_inquiry.server.run --port 8766 --project-id default --env test
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
logger = logging.getLogger("ai.server.run")


def parse_args():
    parser = argparse.ArgumentParser(description="ai Server")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--project-id", default="default")
    parser.add_argument("--workspace", default=None)
    parser.add_argument("--env", default="default")
    return parser.parse_args()


async def _start_server():
    args = parse_args()

    import os

    from agentic_inquiry.config import Config
    from agentic_inquiry.server.app import create_app
    from agentic_inquiry.server.bind import bind_host, rest_auth_enabled
    from agentic_inquiry.server.lifecycle import remove_pid_file, write_pid_file

    # Refuse a bad bind before create_app opens any store.
    config = Config.load()
    try:
        host = bind_host(
            os.environ.get("INQUIRY_SERVER_HOST"), rest_auth_enabled(config)
        )
    except ValueError as exc:
        logger.error("Cannot start the ai server: %s", exc)
        raise SystemExit(1) from None

    app = await create_app(
        config=config,
        project_id=args.project_id,
        workspace=args.workspace,
    )

    try:
        write_pid_file(os.getpid(), args.port, args.project_id, env=args.env)
        logger.info("Starting ai server on %s:%d (env=%s)", host, args.port, args.env)
        uvicorn_config = uvicorn.Config(
            app,
            host=host,
            port=args.port,
            log_level="info",
            ws_ping_interval=30,
            ws_ping_timeout=30,
        )
        await uvicorn.Server(uvicorn_config).serve()
    finally:
        # uvicorn re-raises the signal that stopped it once serve() returns,
        # and a signal before its lifespan starts skips the lifespan's
        # shutdown; the second shutdown() after a normal stop does nothing.
        remove_pid_file(env=args.env)
        await app.state.mcp_server.shutdown()


def main():
    # uvicorn restores the handlers it found and re-raises the stopping signal
    # after serve() returns. Under the default SIGTERM action that kills the
    # process before _start_server's finally removes the PID file.
    signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(128 + signum))
    try:
        asyncio.run(_start_server())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
