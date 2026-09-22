#!/usr/bin/env python3
"""PostToolUse TaskUpdate hook - Status transition memory prompts.

Responsibilities:
1. Detect task status transitions (in_progress, completed, pending)
2. Prompt for appropriate memory capture
"""

import os
import sys
from pathlib import Path

# Add plugin root to path for shared helpers
_plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT") or str(Path(__file__).parent.parent.parent)
if _plugin_root not in sys.path:
    sys.path.insert(0, _plugin_root)

from scripts.socket_client import hook_output, read_hook_input


def main() -> None:
    input_data = read_hook_input()

    tool_input = input_data.get("toolInput", {})
    task_id = tool_input.get("taskId", "")
    status = tool_input.get("status", "")
    subject = tool_input.get("subject", "")

    # Only prompt on status transitions
    if not status:
        hook_output(continue_=True)
        return

    prompt = None
    try:
        from agent_vault.server.http_client import HookClient
        client = HookClient(timeout=2.0)

        if client.available:
            result = client.post(
                "/api/v1/hooks/post_task_update",
                data={
                    "task_id": task_id,
                    "status": status,
                    "subject": subject,
                },
                timeout=0.5,
            )

            if result and result.get("prompt"):
                prompt = result["prompt"]
    except ImportError:
        pass  # Server not available

    if prompt:
        hook_output(continue_=True, system_message=prompt)
    else:
        hook_output(continue_=True)


if __name__ == "__main__":
    main()
