"""Runner for TEST_04 Bug Investigation - run 20260320_213916."""
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
for noisy in ["httpx", "httpcore", "asyncio", "urllib3"]:
    logging.getLogger(noisy).setLevel(logging.WARNING)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Make protocols importable as a package
PROTOCOLS_DIR = PROJECT_ROOT / "tests" / "01-agents"
sys.path.insert(0, str(PROTOCOLS_DIR))

RUN_ID = "20260320_213916"
OUTPUT_DIR = PROJECT_ROOT / "test_results" / "agv" / RUN_ID / "bug_investigation"
CONFIG_PATH = str(PROJECT_ROOT / ".agv" / "envs" / "agv-prod" / "config.yaml")


async def main():
    from agent_vault.config import Config
    from agent_vault.mcp.factories import create_mcp_services
    from protocols.test_04_bug import run  # noqa

    print(f"Loading config from: {CONFIG_PATH}")
    config = Config.load(config_path=CONFIG_PATH)

    print("Creating MCP services...")
    project_id = f"agv_test04_bug_{RUN_ID}"
    services = await create_mcp_services(config, project_id)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Running TEST_04 bug investigation, output: {OUTPUT_DIR}")

    summary = await run(
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
