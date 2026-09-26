#!/usr/bin/env python3
"""SessionStart hook - Start server, load memories, inject behavioral contract.

Responsibilities:
1. Auto-start ai server if not running
2. Run staleness check on memories
3. Inject behavioral contract (MUST-level requirements)
4. Report ai readiness
"""

import os
import sys
from pathlib import Path

# Add plugin root to path for shared helpers
_plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT") or str(
    Path(__file__).parent.parent.parent
)
if _plugin_root not in sys.path:
    sys.path.insert(0, _plugin_root)

from scripts.socket_client import hook_output, read_hook_input


def main() -> None:
    input_data = read_hook_input()
    workspace = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())

    # Auto-start server(s)
    parts = []
    dev_mode = os.path.exists(os.path.join(workspace, ".agentic-inquiry", ".dev-mode"))
    try:
        from agentic_inquiry.server.lifecycle import ensure_server, server_status

        # Always start production server
        url = ensure_server(workspace=workspace)
        if url:
            status = server_status()
            parts.append(
                f"[ai] Server active (port={status.get('port', '?')}, "
                f"project={status.get('project_id', 'unknown')[:8]})"
            )
        else:
            parts.append("[ai] Server not available - memory/context features limited")

        # If dev mode, also start test server
        if dev_mode:
            test_url = ensure_server(workspace=workspace, env="test")
            if test_url:
                test_status = server_status(env="test")
                parts.append(
                    f"[ai-DEV] Test server active (port={test_status.get('port', '?')})"
                )
    except ImportError:
        parts.append("[ai] Server not available - memory/context features limited")

    # Behavioral contract - MUST-level requirements
    contract = (
        "[ai Memory Contract] IMPORTANT behavioral requirements:\n"
        "- You MUST respond to ALL [ai Memory] and [ai Pre-Compact] prompts from hooks.\n"
        "- You MUST store memories at every decision point, discovery, and checkpoint.\n"
        "- You MUST call /ai:memory save after discovering architectural patterns.\n"
        "- You MUST store decisions before context compaction (PreCompact hook).\n"
        "- You CANNOT silently ignore [ai Memory] prompts.\n"
        "- You CANNOT end a session without storing learnings (Stop hook).\n\n"
        "Memory categories — use as things happen, not just at session end:\n"
        "- **decision**: Choices made with rationale and trade-offs\n"
        "- **pattern**: Reusable approaches, workflows, how-to knowledge\n"
        "- **gotcha**: Bugs found, surprises, non-obvious behaviors\n"
        "- **architecture**: How components connect, service boundaries\n"
        "- **observation**: Notable events, performance data, behaviors\n\n"
        "Checkpoints occur every 5 turns. You will be prompted to store memories.\n"
        "PreCompact and Stop hooks are HARD GATES — you must store before proceeding."
    )
    parts.append(contract)

    hook_output(continue_=True, system_message="\n\n".join(parts))


if __name__ == "__main__":
    main()
