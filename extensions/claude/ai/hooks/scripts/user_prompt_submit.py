#!/usr/bin/env python3
"""UserPromptSubmit hook - Signal analysis and dynamic context injection.

Responsibilities:
1. Increment turn counter and check for checkpoints
2. Analyze prompt for signals (entities, intent, file paths)
3. Assemble context (memories, search, graph) based on injection tier
4. Inject assembled context as systemMessage
5. Trigger lazy prefetch for predicted follow-ups

Budget: 200ms total
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
    workspace = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
    session_id = os.environ.get("CLAUDE_SESSION_ID", "unknown")

    # Get the user's prompt
    prompt = input_data.get("userPrompt", input_data.get("prompt", ""))
    if not prompt:
        hook_output(continue_=True)
        return

    parts = []

    try:
        from agentic_inquiry.server.http_client import HookClient
        client = HookClient(timeout=2.0)

        if client.available:
            # 1. Increment turn counter
            turn_result = client.post(
                "/api/v1/session/increment", timeout=0.5,
            )

            # Check for checkpoint
            if turn_result and turn_result.get("checkpoint"):
                turn = turn_result.get("turn", 0)
                parts.append(
                    f"[ai Checkpoint] Turn {turn}. REQUIRED: Store at least one "
                    "insight, decision, or pattern via /ai:memory save. "
                    "If nothing learned, explicitly state why."
                )

            # 2. Assemble context
            context_result = client.post(
                "/api/v1/context/assemble",
                data={"prompt": prompt, "session_id": session_id},
                timeout=2.0,
            )

            if context_result:
                context = context_result.get("context", "")
                if context:
                    parts.append(context)

                # 3. Queue prefetch (fire-and-forget)
                if context_result.get("tier") != "NONE":
                    client.fire_and_forget(
                        "/api/v1/cache/prefetch",
                        data={"queries": _predict_followups(prompt), "session_id": session_id},
                    )
    except ImportError:
        pass  # Server not available

    # Dev mode banner (preserve existing behavior)
    if os.path.exists(os.path.join(workspace, ".agentic-inquiry", ".dev-mode")):
        parts.insert(0, "[ai DEV MODE] Using test environment. /ai-dev off to exit.")

    if parts:
        hook_output(continue_=True, system_message="\n\n".join(parts))
    else:
        hook_output(continue_=True)


def _predict_followups(prompt: str) -> list[str]:
    """Predict likely follow-up queries for prefetch."""
    predictions = []
    words = prompt.lower().split()

    if "how" in words:
        idx = words.index("how")
        remaining = " ".join(words[idx + 1 : idx + 5])
        if remaining:
            predictions.append(f"{remaining} implementation")

    arch_words = {"architecture", "design", "pattern", "service", "component"}
    if arch_words & set(words):
        predictions.append(f"{prompt[:50]} tests")

    code_words = {"function", "class", "method", "implement", "code"}
    if code_words & set(words):
        predictions.append(f"{prompt[:50]} documentation")

    return predictions[:3]


if __name__ == "__main__":
    main()
