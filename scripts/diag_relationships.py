"""Diagnostic: check if pending relationships accumulate during indexing."""
import asyncio
import logging
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Show all ai logs at INFO level
logging.basicConfig(
    level=logging.INFO,
    format="%(name)s: %(message)s",
    stream=sys.stderr,
)
# But only show our diagnostic messages on stdout
for name in ["agentic_inquiry.indexing", "agentic_inquiry.mcp.tools.knowledge"]:
    logging.getLogger(name).setLevel(logging.INFO)


async def main():
    from agentic_inquiry.config import Config
    from agentic_inquiry.mcp.server import MCPServer
    from agentic_inquiry.mcp.tools.session import create_session
    from agentic_inquiry.mcp.tools.knowledge import add_knowledge

    config_path = str(PROJECT_ROOT / ".agentic-inquiry/envs/ai-prod/config.yaml")
    config = Config.load_with_overlay(config_path)

    server = MCPServer(config=config, project_id="diag_rels_server")
    await server.initialize()
    services = server.services

    # Create session
    r = await create_session(services, project_id="diag_rels_test", description="Relationship diagnostic")
    session_id = r["session_id"]
    print(f"Session: {session_id}")

    # Index just 5 Python files from mcp/tools (small, fast)
    source = str(PROJECT_ROOT / "agentic_inquiry/mcp/tools")
    print(f"Indexing: {source}")
    t0 = time.time()
    r = await add_knowledge(services, session_id=session_id, content_type="directory", source=source)
    print(f"add_knowledge returned: status={r.get('status')}")

    # Wait for async indexing
    if r.get("status") == "started":
        print("Waiting for async indexing...")
        await asyncio.sleep(60)  # Wait 60s for small dir

    print(f"Done in {time.time() - t0:.1f}s")
    await server.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
