#!/usr/bin/env python3
"""Minimal stdio MCP server that records its working directory.

Usage: mcp-cwd-probe.py <harness-label>

On start it appends one JSON line to cwd-probe.log beside this file with the
label, os.getcwd(), argv, pid and the parent process name. It then serves a
one-tool MCP surface so the harness treats it as healthy: the `cwd` tool
returns os.getcwd(). Stdlib only.
"""
import json
import os
import subprocess
import sys
import time

LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cwd-probe.log")
LABEL = sys.argv[1] if len(sys.argv) > 1 else "unlabelled"


def parent_name(pid: int) -> str:
    try:
        out = subprocess.run(["ps", "-o", "comm=", "-p", str(pid)], capture_output=True, text=True)
        return out.stdout.strip()
    except Exception as exc:  # noqa: BLE001
        return f"? ({exc})"


with open(LOG, "a", encoding="utf-8") as fh:
    fh.write(json.dumps({
        "label": LABEL,
        "cwd": os.getcwd(),
        "argv": sys.argv,
        "pid": os.getpid(),
        "ppid": os.getppid(),
        "parent": parent_name(os.getppid()),
        "pwd_env": os.environ.get("PWD"),
        "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }) + "\n")


def send(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


TOOLS = [{
    "name": "cwd",
    "description": "Return the server process working directory.",
    "inputSchema": {"type": "object", "properties": {}},
}]

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        msg = json.loads(line)
    except json.JSONDecodeError:
        continue
    mid = msg.get("id")
    method = msg.get("method")
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": msg.get("params", {}).get("protocolVersion", "2025-06-18"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "cwdprobe", "version": "0.1"},
        }})
    elif method == "tools/list":
        send({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        send({"jsonrpc": "2.0", "id": mid, "result": {
            "content": [{"type": "text", "text": json.dumps({"label": LABEL, "cwd": os.getcwd()})}],
            "isError": False,
        }})
    elif method == "ping":
        send({"jsonrpc": "2.0", "id": mid, "result": {}})
    elif mid is not None:
        send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"unknown method {method}"}})
