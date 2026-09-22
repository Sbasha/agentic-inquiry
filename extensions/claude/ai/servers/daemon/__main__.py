"""ai Daemon Service entry point.

Usage:
    python -m extensions.claude.ai.servers.daemon --workspace /path/to/project
"""

import argparse
import asyncio
import logging
import os
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description="ai Daemon Service")
    parser.add_argument(
        "--workspace",
        default=os.getcwd(),
        help="Workspace directory (default: cwd)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stderr),
        ],
    )

    from .daemon import InquiryDaemon

    daemon = InquiryDaemon(workspace=args.workspace)

    async def run() -> None:
        await daemon.start()
        await daemon.run_forever()

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
