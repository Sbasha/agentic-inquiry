"""Runner for TEST_11 API Design."""
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
for noisy in ["httpx", "httpcore", "asyncio", "urllib3", "hpack", "h2"]:
    logging.getLogger(noisy).setLevel(logging.WARNING)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PROTOCOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROTOCOLS_DIR))

RUN_ID = "20260320_213916"
OUTPUT_DIR = PROJECT_ROOT / "test_results" / "agv" / RUN_ID / "api_design"
ENV_PATH = str(PROJECT_ROOT / ".agv" / "envs" / "agv-prod" / "config.yaml")


async def main():
    from agent_vault.config import Config
    from agent_vault.mcp.factories import create_mcp_services
    from protocols import test_11_api_design as mod

    print(f"Loading config from: {ENV_PATH}")
    config = Config.load(ENV_PATH)

    print("Creating MCP services...")
    services = await create_mcp_services(config, f"agv_test11_api_{RUN_ID}")

    print(f"Running TEST_11 API design, output: {OUTPUT_DIR}")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    summary = await mod.run(
        services=services,
        test_id="11",
        slug="api",
        run_id=RUN_ID,
        output_dir=OUTPUT_DIR,
    )
    elapsed = time.time() - t0

    print("\n" + "=" * 60)
    print("TEST_11 SUMMARY")
    print("=" * 60)
    print(json.dumps(summary, indent=2, default=str))
    print(f"\nTotal elapsed: {elapsed:.1f}s")

    return summary


if __name__ == "__main__":
    result = asyncio.run(main())
    status = result.get("status", "unknown")
    sys.exit(0 if status in ("pass", "partial") else 1)
