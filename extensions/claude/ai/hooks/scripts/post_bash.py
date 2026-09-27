#!/usr/bin/env python3
"""PostToolUse Bash hook - Classify command, extract results.

Responsibilities:
1. Classify command type (test, build, git, deploy, general)
2. Prompt for memory capture on significant events
3. Auto-capture test failures
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

    tool_input = input_data.get("toolInput", {})
    command = tool_input.get("command", "")
    tool_output = input_data.get("toolOutput", {})
    exit_code = tool_output.get("exitCode", tool_output.get("exit_code", 0))
    stdout = tool_output.get("stdout", tool_output.get("output", ""))

    if not command:
        hook_output(continue_=True)
        return

    prompt = None
    try:
        from agentic_inquiry.server.http_client import HookClient

        client = HookClient(timeout=2.0)

        if client.available:
            result = client.post(
                "/api/v1/hooks/post_bash",
                data={
                    "command": command,
                    "exit_code": exit_code,
                    "output": stdout[:2000] if stdout else "",
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
