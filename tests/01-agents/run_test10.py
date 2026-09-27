"""Runner for TEST_10 Performance Investigation."""

import asyncio
import json
import logging
import sys
import time
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
# Suppress noisy loggers
for noisy in ["httpx", "httpcore", "asyncio", "urllib3", "hpack", "h2"]:
    logging.getLogger(noisy).setLevel(logging.WARNING)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PROTOCOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROTOCOLS_DIR))  # allows "from protocols import ..."

RUN_ID = "20260320_092711"
OUTPUT_DIR = PROJECT_ROOT / "test_results" / "ai" / RUN_ID / "performance_investigation"
ENV_PATH = str(PROJECT_ROOT / ".agentic-inquiry" / "envs" / "ai-prod" / "config.yaml")


async def main():
    from agentic_inquiry.config import Config
    from agentic_inquiry.mcp.factories import create_mcp_services

    # Import via package to support relative imports in protocol module
    from protocols import test_10_perf as mod

    print(f"Loading config from: {ENV_PATH}")
    config = Config.load(ENV_PATH)

    print("Creating MCP services...")
    services = await create_mcp_services(config, f"ai_test10_perf_{RUN_ID}")

    print(f"Running TEST_10 performance investigation, output: {OUTPUT_DIR}")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    summary = await mod.run(
        services=services,
        test_id="10",
        slug="perf",
        run_id=RUN_ID,
        output_dir=OUTPUT_DIR,
    )
    elapsed = time.time() - t0

    print("\n" + "=" * 60)
    print("TEST_10 SUMMARY")
    print("=" * 60)
    print(json.dumps(summary, indent=2, default=str))
    print(f"\nTotal elapsed: {elapsed:.1f}s")

    return summary


if __name__ == "__main__":
    result = asyncio.run(main())
    status = result.get("status", "unknown")
    sys.exit(0 if status in ("pass", "partial") else 1)
