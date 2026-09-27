#!/usr/bin/env python3
"""Stop hook - HARD GATE: Force reflection, block until stored.

This hook ensures session learnings are captured before exit.
Responsibilities:
1. Auto-save session file changes
2. Generate reflection prompt
3. Force memory storage before session ends
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
    session_id = os.environ.get("CLAUDE_SESSION_ID", "unknown")

    prompt = None
    try:
        from agentic_inquiry.server.http_client import HookClient

        client = HookClient(timeout=5.0)

        if client.available:
            result = client.post(
                "/api/v1/hooks/stop",
                data={"session_id": session_id},
                timeout=5.0,
            )

            if result:
                prompt = result.get("prompt", "")
    except ImportError:
        pass  # Server not available

    if not prompt:
        prompt = (
            "[ai Stop] Session ending (server unavailable). "
            "REQUIRED: Review your work this session. "
            "Store all decisions, gotchas, and reusable patterns via /ai:memory save. "
            "Do NOT end session without storing learnings."
        )

    # HARD GATE: prompt is mandatory
    hook_output(continue_=True, system_message=prompt)


if __name__ == "__main__":
    main()
