#!/usr/bin/env python3
"""PreCompact hook - HARD GATE: Auto-save snapshot, block until stored.

This hook BLOCKS compaction until working memory is stored.
Responsibilities:
1. Auto-save accumulated file changes
2. Prompt for mandatory memory capture
3. Return continue=false to enforce the gate
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
    session_id = os.environ.get("CLAUDE_SESSION_ID", "unknown")

    prompt = None
    try:
        from agent_vault.server.http_client import HookClient
        client = HookClient(timeout=5.0)

        if client.available:
            result = client.post(
                "/api/v1/hooks/pre_compact",
                data={"session_id": session_id},
                timeout=5.0,
            )

            if result:
                prompt = result.get("prompt", "")
    except ImportError:
        pass  # Server not available

    if not prompt:
        # Fallback when server unavailable
        prompt = (
            "[agv Pre-Compact] Context is about to compress (server unavailable). "
            "REQUIRED: Store any decisions, discoveries, or reusable patterns "
            "from this work NOW via /agv:memory save. "
            "This is your last chance before context compresses."
        )

    # HARD GATE: always prompt, always continue (let compaction proceed after prompting)
    hook_output(continue_=True, system_message=prompt)


if __name__ == "__main__":
    main()
