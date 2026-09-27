"""OpenAI-compatible chat endpoint that answers with ``claude -p`` (RFC-0004 C1).

Competitors that ingest through an LLM (mem0, Cognee) take an OpenAI-compatible
base URL. This server gives them one pinned Claude model through the Claude
subscription. A structured-output request is passed to ``claude -p --json-schema``
when the request carries its own schema; plain JSON mode and tool calls are
expressed in the prompt. The reply is turned back into an OpenAI message.
Responses are cached by request, so a rerun is reproducible; a cached reply
still counts its original tokens and API time.

A path prefix names a build: ``http://127.0.0.1:8765/<prefix>/v1`` counts that
build's calls, tokens, API time, upstream errors and unparseable replies, served
at ``GET /<prefix>/stats``.

Run: ``python -m evals.claude_shim --port 8765`` (``EVALS_SHIM_SLOTS`` concurrent
``claude -p`` calls, default 8).
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
from collections import Counter, defaultdict
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


def reply_schema(body: dict[str, Any]) -> dict[str, Any] | None:
    """The request's own JSON schema, which constrains the reply; None otherwise.

    Plain JSON mode and tool calls stay prompt-guided: constraining them to a
    generic object schema lets the model return an empty ``{}``.
    """
    response_format = body.get("response_format") or {}
    if response_format.get("type") == "json_schema" and not body.get("tools"):
        schema = (response_format.get("json_schema") or {}).get("schema")
        return schema if isinstance(schema, dict) and schema.get("properties") else None
    return None


STATS: dict[str, Counter[str]] = defaultdict(Counter)
_STATS_LOCK = threading.Lock()
SHIM_LOG = CACHE / "llm-shim-log"


def count(prefix: str, **values: int) -> None:
    with _STATS_LOCK:
        STATS[prefix].update(values)


def reset(prefix: str) -> None:
    """Start a build's counters from zero, so a retried build is not counted twice."""
    with _STATS_LOCK:
        STATS.pop(prefix, None)


def _log(prefix: str, entry: dict[str, Any]) -> None:
    """One JSON line per call under the build's prefix, kept across shim restarts."""
    SHIM_LOG.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", prefix or "unprefixed")
    with _STATS_LOCK, (SHIM_LOG / f"{name}.jsonl").open("a") as log:
        log.write(json.dumps(entry, sort_keys=True) + "\n")


def expects_json(body: dict[str, Any]) -> bool:
    fmt = (body.get("response_format") or {}).get("type")
    return bool(body.get("tools")) or fmt in {"json_object", "json_schema"}


def complete(body: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """One chat completion, served from the cache when the same request was seen."""
    prompt = render_prompt(body)
    schema = reply_schema(body)
    key = hashlib.sha256(
        json.dumps([MODEL, "no-thinking", prompt, schema]).encode()
    ).hexdigest()
    path = SHIM_CACHE / key[:2] / f"{key}.json"
    hit = path.exists()
    if hit:
        record = json.loads(path.read_text())
    else:
        try:
            with _SLOTS:
                record = _claude(MODEL, prompt, schema)
        except Exception as exc:
            count(prefix, upstream_errors=1)
            _log(prefix, {"key": key, "error": str(exc)[-300:]})
            raise
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record))
    unparseable = expects_json(body) and _first_json(record["text"]) is None
    mismatch = record.get("resolved_model", MODEL) != MODEL
    count(
        prefix,
        calls=1,
        schema_calls=int(schema is not None),
        cache_hits=int(hit),
        input_tokens=int(record.get("input_tokens", 0)),
        output_tokens=int(record.get("output_tokens", 0)),
        api_ms=int(record.get("api_ms", 0)),
        unparseable=int(unparseable),
        model_mismatch=int(mismatch),
    )
    _log(
        prefix,
        {
            "key": key,
            "cache_hit": hit,
            "schema": schema is not None,
            "model": MODEL,
            "resolved_model": record.get("resolved_model"),
            "input_tokens": record.get("input_tokens", 0),
            "output_tokens": record.get("output_tokens", 0),
            "api_ms": record.get("api_ms", 0),
            "unparseable": unparseable,
        },
    )
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

    def _prefix(self) -> str:
        head = self.path.strip("/").split("/", 1)[0]
        return "" if head == "v1" else head

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        if self.path.rstrip("/").endswith("/reset"):
            reset(self._prefix())
            self._send(200, {})
        elif self.path.rstrip("/").endswith("/stats"):
            with _STATS_LOCK:
                self._send(200, dict(STATS[self._prefix()]))
        elif self.path.rstrip("/").endswith("/models"):
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
            response = complete(body, self._prefix())
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
