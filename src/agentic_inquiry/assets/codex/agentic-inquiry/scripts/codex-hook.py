"""Translate native Codex hooks without reading transcripts or executing source text."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

MAX_BYTES = 1_048_576
EVENTS = {"SessionStart", "UserPromptSubmit", "PostToolUse", "PreCompact", "Stop", "SessionEnd"}


def translate(event: str, native: dict) -> tuple[dict, list[str]]:
    if event not in EVENTS or native.get("hook_event_name", event) != event:
        raise ValueError("Unsupported or mismatched native hook event")
    root, session = native.get("cwd"), native.get("session_id")
    if not isinstance(root, str) or not Path(root).is_absolute():
        raise ValueError("Native hook cwd must be an absolute path")
    if not isinstance(session, str) or not session or len(session) > 300:
        raise ValueError("Native hook session_id is missing or oversized")
    payload = {
        "schema_version": 1,
        "project_root": str(Path(root).resolve()),
        "session_id": session,
        "owner": "standalone",
    }
    warnings = []
    if event == "UserPromptSubmit" and isinstance(native.get("prompt"), str):
        query = native["prompt"]
        if len(query.encode()) <= 16_384:
            payload["query"] = query
        else:
            warnings.append("Prompt exceeds the recall query bound; no prompt text was forwarded.")
    if event == "PostToolUse":
        arguments = native.get("tool_input", {})
        artifacts = []
        if isinstance(arguments, dict):
            tool = native.get("tool_name")
            if tool in {"Write", "Edit"}:
                path = arguments.get("file_path", arguments.get("path"))
                if isinstance(path, str):
                    artifacts.append(path)
            elif tool == "apply_patch" and isinstance(arguments.get("command"), str):
                artifacts = re.findall(
                    r"^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+)$",
                    arguments["command"],
                    re.MULTILINE,
                )
        if artifacts:
            identity = native.get("tool_use_id")
            if isinstance(identity, str) and identity and len(identity) <= 300:
                payload["event_id"] = identity
                payload["artifacts"] = sorted(set(artifacts))[:100]
                if len(set(artifacts)) > 100:
                    warnings.append(
                        "More than 100 changed paths; run ai index for complete refresh."
                    )
            else:
                warnings.append(
                    "No stable native tool event ID; run ai index explicitly to refresh changed sources."
                )
    return payload, warnings


def output(event: str, response: dict, warnings: list[str]) -> dict:
    result = {}
    context = response.get("context", {}).get("text", "")
    if context and event in {"SessionStart", "UserPromptSubmit", "PostToolUse"}:
        result["hookSpecificOutput"] = {"hookEventName": event, "additionalContext": context}
    if response.get("status") in {"partial", "error", "unsupported"}:
        warnings.append(
            "Agentic Inquiry needs attention: "
            + json.dumps(
                {
                    "status": response.get("status"),
                    "pending": response.get("pending", []),
                    "errors": response.get("errors", []),
                }
            )
        )
    if event == "PreCompact" and response.get("status") != "inert":
        warnings.append(
            "Save selected observations explicitly with ai capture before compaction; transcript capture is disabled."
        )
    if warnings:
        result["systemMessage"] = "\n".join(warnings)[:8192]
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", required=True, choices=sorted(EVENTS))
    parser.add_argument("--db")
    args = parser.parse_args()
    try:
        raw = sys.stdin.buffer.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("Native hook exceeds the 1 MiB limit")
        native = json.loads(raw)
        if not isinstance(native, dict):
            raise TypeError("Native hook must be a JSON object")
        payload, warnings = translate(args.event, native)
        argv = [
            "ai",
            "integration",
            "hook",
            "--client",
            "codex",
            "--event",
            args.event,
            "--input",
            "-",
        ]
        completed = subprocess.run(
            argv,
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            timeout=2 if args.event == "SessionEnd" else 12,
            check=False,
        )
        if completed.returncode not in {0, 1} or len(completed.stdout.encode()) > MAX_BYTES:
            raise RuntimeError(
                "Agentic Inquiry hook failed; inspect ai integration status and capture status"
            )
        response = json.loads(completed.stdout)
        if response.get("schema_version") != 1:
            raise ValueError("Unsupported Agentic Inquiry response schema")
        print(json.dumps(output(args.event, response, warnings)))
        return 0
    except (OSError, ValueError, TypeError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(
            json.dumps(
                {
                    "systemMessage": f"Agentic Inquiry hook unavailable ({type(error).__name__}); use the explicit ai commands."
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
