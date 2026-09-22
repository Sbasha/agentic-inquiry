#!/usr/bin/env python3
"""PostToolUse Write/Edit hook - Store change event, require memory capture.

Responsibilities:
1. Record file change in server
2. Invalidate relevant caches
3. Prompt for memory capture on significant files
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

    # Extract file path from tool input
    tool_input = input_data.get("toolInput", {})
    file_path = tool_input.get("file_path", "")
    tool_name = input_data.get("toolName", "Write")

    if not file_path:
        hook_output(continue_=True)
        return

    change_type = "write" if tool_name == "Write" else "edit"

    prompt = None
    try:
        from agentic_inquiry.server.http_client import HookClient
        client = HookClient(timeout=2.0)

        if client.available:
            # Fire-and-forget: record change + invalidate cache
            client.fire_and_forget(
                "/api/v1/hooks/post_write",
                data={"file_path": file_path, "change_type": change_type},
            )

            # Check if file is significant
            result = client.post(
                "/api/v1/hooks/post_read",
                data={"file_path": file_path},
                timeout=0.5,
            )

            if result:
                importance = result.get("importance", "")
                if importance == "config":
                    prompt = (
                        f"[ai Memory] Configuration file modified: {os.path.basename(file_path)}. "
                        "If this changes system behavior, store the rationale via /ai:memory save."
                    )
                elif importance == "entry_point":
                    prompt = (
                        f"[ai Memory] Entry point modified: {os.path.basename(file_path)}. "
                        "Store what changed and why via /ai:memory save."
                    )
    except ImportError:
        pass  # Server not available

    if prompt:
        hook_output(continue_=True, system_message=prompt)
    else:
        hook_output(continue_=True)


if __name__ == "__main__":
    main()
