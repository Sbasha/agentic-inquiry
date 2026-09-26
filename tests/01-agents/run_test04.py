"""Runner for TEST_04 Bug Investigation."""

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
for noisy in ["httpx", "httpcore", "asyncio", "urllib3"]:
    logging.getLogger(noisy).setLevel(logging.WARNING)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

RUN_ID = "20260320_092711"
OUTPUT_DIR = PROJECT_ROOT / "test_results" / "ai" / RUN_ID / "bug_investigation"
ENV_PATH = str(PROJECT_ROOT / ".agentic-inquiry" / "envs" / "ai-prod" / "config.yaml")


async def main():
    from agentic_inquiry.config import Config
    from agentic_inquiry.mcp.factories import create_mcp_services
    from tests.agents.protocols.test_04_bug import run  # noqa

    # Import correctly
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "test_04_bug",
        PROJECT_ROOT / "tests" / "01-agents" / "protocols" / "test_04_bug.py",
    )
    mod = importlib.util.load_from_spec(spec)
    spec.loader.exec_module(mod)

    print(f"Loading config from: {ENV_PATH}")
    config = Config.load(ENV_PATH)

    print("Creating MCP services...")
    services = await create_mcp_services(config, f"ai_test04_bug_{RUN_ID}")

    print(f"Running TEST_04 bug investigation, output: {OUTPUT_DIR}")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    summary = await mod.run(
        services=services,
        test_id="04",
        slug="bug",
        run_id=RUN_ID,
        output_dir=OUTPUT_DIR,
    )

    print("\n" + "=" * 60)
    print("TEST_04 SUMMARY")
    print("=" * 60)
    print(json.dumps(summary, indent=2, default=str))
    return summary


if __name__ == "__main__":
    asyncio.run(main())
