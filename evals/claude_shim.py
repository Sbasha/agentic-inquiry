"""OpenAI-compatible chat endpoint that answers with ``claude -p`` (RFC-0003 live competitor arms).

Competitors that ingest through an LLM (mem0, OpenKB, Cognee) take an
OpenAI-compatible base URL. This server gives them one pinned Claude model
through the Claude subscription. JSON mode and tool calls are expressed in the
prompt: the model answers with one JSON object, which the server turns back
into an OpenAI message. Responses are cached by request hash so a rerun is
reproducible and free.

Run: ``python -m evals.claude_shim --port 8765`` (``EVALS_SHIM_SLOTS`` concurrent
``claude -p`` calls, default 8); point clients at
``http://127.0.0.1:8765/v1``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from evals.answer import ANSWERER, _claude
from evals.data import CACHE

MODEL = ANSWERER
SHIM_CACHE = CACHE / "llm-shim"
_SLOTS = threading.Semaphore(int(os.environ.get("EVALS_SHIM_SLOTS", "8")))

_TOOL_PROTOCOL = """You can call tools. The available tools, as JSON schemas:
{tools}

Reply with exactly one JSON object and nothing else. To call tools:
{{"tool_calls": [{{"name": "<tool name>", "arguments": {{...}}}}]}}
To answer without a tool:
{{"content": "<your reply>"}}"""

_JSON_PROTOCOL = "Reply with exactly one valid JSON object and nothing else."


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        )
    return "" if content is None else str(content)


def render_prompt(body: dict[str, Any]) -> str:
    """Flatten an OpenAI chat request into one prompt for ``claude -p``."""
    lines: list[str] = []
    for message in body.get("messages", []):
        role = message.get("role", "user")
        if role == "tool":
            lines.append(
                f"[tool result {message.get('tool_call_id', '')}]\n{_text(message.get('content'))}"
            )
            continue
        text = _text(message.get("content"))
        for call in message.get("tool_calls") or []:
            fn = call.get("function", {})
            text += f"\n[called {fn.get('name')} with {fn.get('arguments')}]"
        lines.append(f"[{role}]\n{text}")
    prompt = "\n\n".join(lines)
    if body.get("tools"):
        specs = [tool.get("function", tool) for tool in body["tools"]]
        prompt += "\n\n" + _TOOL_PROTOCOL.format(tools=json.dumps(specs, indent=1))
    elif (body.get("response_format") or {}).get("type") in {
        "json_object",
        "json_schema",
    }:
        schema = (body.get("response_format") or {}).get("json_schema")
        prompt += (
            "\n\n"
            + _JSON_PROTOCOL
            + (f"\nSchema: {json.dumps(schema)}" if schema else "")
        )
    return prompt


def _first_json(text: str) -> Any:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return None
    return None


def to_message(body: dict[str, Any], reply: str) -> tuple[dict[str, Any], str]:
    """Turn the model's reply into an OpenAI assistant message and finish reason."""
    if body.get("tools"):
        parsed = _first_json(reply)
        if isinstance(parsed, dict) and parsed.get("tool_calls"):
            calls = [
                {
                    "id": f"call_{uuid.uuid4().hex[:12]}",
                    "type": "function",
                    "function": {
                        "name": call.get("name", ""),
                        "arguments": json.dumps(call.get("arguments", {})),
                    },
                }
                for call in parsed["tool_calls"]
            ]
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": calls,
            }, "tool_calls"
        if isinstance(parsed, dict) and "content" in parsed:
            return {"role": "assistant", "content": str(parsed["content"])}, "stop"
        return {"role": "assistant", "content": reply}, "stop"
    if (body.get("response_format") or {}).get("type") in {
        "json_object",
        "json_schema",
    }:
        parsed = _first_json(reply)
        return {
            "role": "assistant",
            "content": json.dumps(parsed) if parsed is not None else reply,
        }, "stop"
    return {"role": "assistant", "content": reply}, "stop"


def complete(body: dict[str, Any]) -> dict[str, Any]:
    """One chat completion, served from the cache when the same request was seen."""
    prompt = render_prompt(body)
    key = hashlib.sha256(
        json.dumps([MODEL, prompt, bool(body.get("tools"))]).encode()
    ).hexdigest()
    path = SHIM_CACHE / key[:2] / f"{key}.json"
    if path.exists():
        record = json.loads(path.read_text())
    else:
        with _SLOTS:
            record = _claude(MODEL, prompt)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record))
    message, finish = to_message(body, record["text"])
    return {
        "id": f"chatcmpl-{key[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": body.get("model", MODEL),
        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
        "usage": {
            "prompt_tokens": record.get("input_tokens", 0),
            "completion_tokens": record.get("output_tokens", 0),
            "total_tokens": record.get("input_tokens", 0)
            + record.get("output_tokens", 0),
        },
    }


def _stream_chunks(response: dict[str, Any]) -> list[dict[str, Any]]:
    message = response["choices"][0]["message"]
    delta: dict[str, Any] = {"role": "assistant", "content": message.get("content")}
    if message.get("tool_calls"):
        delta["tool_calls"] = [
            dict(call, index=i) for i, call in enumerate(message["tool_calls"])
        ]
    base = {k: response[k] for k in ("id", "created", "model")} | {
        "object": "chat.completion.chunk"
    }
    return [
        base | {"choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
        base
        | {
            "choices": [
                {
                    "index": 0,
                    "delta": {},
                    "finish_reason": response["choices"][0]["finish_reason"],
                }
            ],
            "usage": response["usage"],
        },
    ]


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        if self.path.rstrip("/").endswith("/models"):
            self._send(
                200, {"object": "list", "data": [{"id": MODEL, "object": "model"}]}
            )
        else:
            self._send(404, {"error": {"message": "not found"}})

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        if not self.path.rstrip("/").endswith("/chat/completions"):
            self._send(404, {"error": {"message": f"unsupported path {self.path}"}})
            return
        body = json.loads(
            self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}"
        )
        try:
            response = complete(body)
        except Exception as exc:  # noqa: BLE001 - reported to the client as an API error
            self._send(
                502, {"error": {"message": str(exc)[:500], "type": "upstream_error"}}
            )
            return
        if not body.get("stream"):
            self._send(200, response)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for chunk in _stream_chunks(response):
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")

    def log_message(self, fmt: str, *args: Any) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
