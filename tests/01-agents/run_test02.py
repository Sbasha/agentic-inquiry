"""Runner for TEST_02 Onboarding."""
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
for noisy in ["httpx", "httpcore", "asyncio", "urllib3", "sentence_transformers",
              "filelock", "transformers"]:
    logging.getLogger(noisy).setLevel(logging.WARNING)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PROTOCOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROTOCOLS_DIR))  # allows "from protocols import ..."

RUN_ID = "20260320_213916"
OUTPUT_DIR = PROJECT_ROOT / "test_results" / "ai" / RUN_ID / "onboarding"
ENV_PATH = str(PROJECT_ROOT / ".agentic-inquiry" / "envs" / "ai-prod" / "config.yaml")
PROJECT_ID = f"ai_test02_onboard_{RUN_ID}"


async def main():
    from agentic_inquiry.config import Config
    from agentic_inquiry.mcp.factories import create_mcp_services
    # Import via package to support relative imports in protocol module
    from protocols import test_02_onboarding as mod

    print(f"Loading config from: {ENV_PATH}")
    config = Config.load(ENV_PATH)

    print(f"Creating MCP services for project: {PROJECT_ID}")
    services = await create_mcp_services(config, PROJECT_ID)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Running TEST_02 onboarding, output: {OUTPUT_DIR}")

    t0 = time.time()
    summary = await mod.run(
        services=services,
        test_id="02",
        slug="onboarding",
        run_id=RUN_ID,
        output_dir=OUTPUT_DIR,
    )

    print("\n" + "=" * 60)
    print("TEST_02 SUMMARY")
    print("=" * 60)
    print(json.dumps(summary, indent=2, default=str))
    print(f"\nTotal wall time: {time.time() - t0:.1f}s")

    return summary


if __name__ == "__main__":
    asyncio.run(main())
