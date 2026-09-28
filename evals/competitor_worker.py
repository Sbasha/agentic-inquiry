"""Build and query one memory tool inside its own virtualenv (RFC-0004 claim C1).

Runs under the tool venv's interpreter, so it imports only the standard
library at module level. The harness side is ``evals.arms.Competitor``.

    python competitor_worker.py index <tool> <corpus dir> <store dir>
    python competitor_worker.py search <tool> <store dir> <k>   < queries.json

``index`` writes ``build.json`` only for a healthy build: every session
ingested and at least one item stored. It records the build's LLM usage from
the shim. ``search`` prints one JSON list of ``[context, seconds, usage, error]``
per query; a failed query fails only itself.

Every LLM call goes to ``claude-haiku-4-5-20251001`` through the shim at
``EVALS_SHIM_URL``; each build and each query has its own URL prefix so its
calls are counted. Embeddings come from Ollama ``bge-m3``.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

MODEL = "claude-haiku-4-5-20251001"
SHIM = os.environ.get("EVALS_SHIM_URL", "http://127.0.0.1:8765")
OLLAMA = "http://localhost:11434"
EMBED_MODEL = "bge-m3"
EMBED_DIMS = 1024
USER = "corpus"
MEM0_TOP_K = 200
COGNEE_TOP_K = 20

# "[<marker>] (<date>) <speaker>: <text>"; LongMemEval dates nest parentheses.
_LINE = re.compile(
    r"^\[[^\]]+\]\s*\((?P<date>\d{4}/\d{2}/\d{2} \(\w+\) \d{2}:\d{2}|[^()]*)\)"
    r"\s*(?P<role>[^:]+):\s?(?P<text>.*)$"
)
_LME_DATE = re.compile(r"\((\d{4}/\d{2}/\d{2}) \(\w+\) (\d{2}:\d{2})\)")


def sessions(root: Path) -> list[Path]:
    """Session files in date order (LongMemEval dates sort as text), then by name."""

    def key(path: Path) -> tuple[str, str]:
        first = path.read_text(encoding="utf-8").split("\n", 1)[0]
        date = _LME_DATE.search(first)
        return (" ".join(date.groups()) if date else "", path.name)

    return sorted((p for p in root.rglob("*.txt") if p.is_file()), key=key)


def turns(path: Path) -> list[dict[str, str]]:
    """``{role, content, date}`` per line of a session file."""
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _LINE.match(line)
        if match:
            out.append(
                {
                    "role": "assistant" if match["role"] == "assistant" else "user",
                    "content": match["text"],
                    "date": match["date"],
                }
            )
    return out


def mem0_messages(session: list[dict[str, str]]) -> Iterator[list[dict[str, str]]]:
    """One ``add`` per user and assistant pair, the session date written into each message
    (mem0's open-source SDK rejects the benchmark's ``timestamp`` argument)."""
    for start in range(0, len(session), 2):
        yield [
            {"role": turn["role"], "content": f"[{turn['date']}] {turn['content']}"}
            for turn in session[start : start + 2]
        ]


def cognee_turn_pairs(sid: str, session: list[dict[str, str]]) -> list[str]:
    """Cognee's BEAM representation: one JSON-list item per turn pair, with its date."""
    items = []
    for number, start in enumerate(range(0, len(session), 2), start=1):
        pair = session[start : start + 2]
        user = next((t["content"] for t in pair if t["role"] == "user"), "")
        assistant = next((t["content"] for t in pair if t["role"] == "assistant"), "")
        items.append(
            f"Session: {sid}\nTurn: {number}\nTime anchor: {pair[0]['date']}\n\n"
            f"User:\n{user}\n\nAssistant:\n{assistant}"
        )
    return items


def _base(prefix: str) -> str:
    return f"{SHIM}/{prefix}/v1"


def shim_stats(prefix: str) -> dict[str, int]:
    with urllib.request.urlopen(f"{SHIM}/{prefix}/stats", timeout=30) as response:
        return dict(json.loads(response.read()))


# --------------------------------------------------------------------------
# mem0
# --------------------------------------------------------------------------


def _mem0(store: Path, prefix: str) -> Any:
    os.environ["MEM0_TELEMETRY"] = "False"
    from mem0 import Memory  # type: ignore[import-not-found]

    return Memory.from_config(
        {
            "llm": {
                "provider": "openai",
                "config": {
                    "model": MODEL,
                    "openai_base_url": _base(prefix),
                    "api_key": "shim",
                },
            },
            "embedder": {
                "provider": "openai",
                "config": {
                    "model": EMBED_MODEL,
                    "openai_base_url": f"{OLLAMA}/v1",
                    "api_key": "ollama",
                    "embedding_dims": EMBED_DIMS,
                },
            },
            "vector_store": {
                "provider": "qdrant",
                "config": {
                    "path": str(store / "qdrant"),
                    "collection_name": "mem0",
                    "embedding_model_dims": EMBED_DIMS,
                    "on_disk": True,
                },
            },
            "history_db_path": str(store / "history.db"),
        }
    )


def mem0_index(root: Path, store: Path, prefix: str) -> int:
    memory = _mem0(store, prefix)
    for path in sessions(root):
        session = turns(path)
        date = session[0]["date"] if session else ""
        for messages in mem0_messages(session):
            memory.add(messages, user_id=USER, metadata={"session_date": date})
    stored = memory.get_all(filters={"user_id": USER}, top_k=100_000)
    rows = stored.get("results", stored) if isinstance(stored, dict) else stored
    return len(rows)


def mem0_raw_index(root: Path, store: Path, prefix: str) -> int:
    """mem0 with ``infer=False``: raw messages stored with embeddings, no LLM extraction."""
    memory = _mem0(store, prefix)
    for path in sessions(root):
        session = turns(path)
        date = session[0]["date"] if session else ""
        for messages in mem0_messages(session):
            memory.add(
                messages, user_id=USER, metadata={"session_date": date}, infer=False
            )
    stored = memory.get_all(filters={"user_id": USER}, top_k=100_000)
    rows = stored.get("results", stored) if isinstance(stored, dict) else stored
    return len(rows)


def mem0_open(store: Path, prefix: str) -> Any:
    return _mem0(store, prefix)


def mem0_search(memory: Any, query: str) -> str:
    found = memory.search(query, top_k=MEM0_TOP_K, filters={"user_id": USER})
    rows = found.get("results", found) if isinstance(found, dict) else found
    lines = []
    for row in rows:
        date, memory = (
            (row.get("metadata") or {}).get("session_date", ""),
            str(row.get("memory", "")),
        )
        # Raw memories already begin with the date written into the message.
        lines.append(memory if memory.startswith(f"[{date}]") else f"[{date}] {memory}")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Cognee
# --------------------------------------------------------------------------


def _cognee(store: Path, prefix: str) -> Any:
    os.environ.update(
        {
            "LLM_PROVIDER": "openai",
            "LLM_MODEL": f"openai/{MODEL}",
            "LLM_ENDPOINT": _base(prefix),
            "LLM_API_KEY": "shim",
            "EMBEDDING_PROVIDER": "ollama",
            "EMBEDDING_MODEL": EMBED_MODEL,
            "EMBEDDING_ENDPOINT": f"{OLLAMA}/api/embed",
            "EMBEDDING_DIMENSIONS": str(EMBED_DIMS),
            "HUGGINGFACE_TOKENIZER": "BAAI/bge-m3",
            "SYSTEM_ROOT_DIRECTORY": str(store / "system"),
            "DATA_ROOT_DIRECTORY": str(store / "data"),
            "TELEMETRY_DISABLED": "1",
        }
    )
    # cognee.eval_framework.beam.local_ingest sets these when imported; the
    # query process sets them too so it reads the memory the way ingest wrote it.
    for key, value in (
        ("CACHING", "true"),
        ("CACHE_BACKEND", "fs"),
        ("AUTO_FEEDBACK", "true"),
    ):
        os.environ.setdefault(key, value)
    import cognee  # type: ignore[import-not-found]

    return cognee


def cognee_index(root: Path, store: Path, prefix: str) -> int:
    _cognee(store, prefix)
    from cognee.eval_framework.beam import local_ingest  # type: ignore[import-not-found]

    folder = store / "sessions"
    folder.mkdir(parents=True, exist_ok=True)
    for number, path in enumerate(sessions(root), start=1):
        items = cognee_turn_pairs(path.stem, turns(path))
        (folder / f"session_{number:04d}_{path.stem}.json").write_text(
            json.dumps(items)
        )
    args = local_ingest.build_parser().parse_args(
        [str(folder), "--dataset-name", USER, "--run-dir", str(store / "run")]
    )
    report = asyncio.run(local_ingest.main_async(args))
    summary = report["summary"]
    expected = len(list(folder.glob("*.json")))
    if summary["session_count"] != expected:
        raise RuntimeError(
            f"cognee ingested {summary['session_count']} of {expected} sessions"
        )
    return int(summary["turn_count"])


def _write_sessions(root: Path, store: Path) -> list[Path]:
    folder = store / "sessions"
    folder.mkdir(parents=True, exist_ok=True)
    files = []
    for number, path in enumerate(sessions(root), start=1):
        target = folder / f"session_{number:04d}_{path.stem}.json"
        target.write_text(json.dumps(cognee_turn_pairs(path.stem, turns(path))))
        files.append(target)
    return files


def cognee_chunks_index(root: Path, store: Path, prefix: str) -> int:
    """Cognee's eval-framework ``JustChunks`` pipeline: chunks embedded, no graph, no LLM."""
    cognee = _cognee(store, prefix)
    from cognee.eval_framework.corpus_builder.task_getters.get_default_tasks_by_indices import (  # type: ignore[import-not-found]
        get_just_chunks_tasks,
    )
    from cognee.modules.chunking.JsonListChunker import JsonListChunker  # type: ignore[import-not-found]
    from cognee.modules.pipelines import run_pipeline  # type: ignore[import-not-found]

    files = _write_sessions(root, store)

    async def build() -> None:
        await cognee.add([str(f) for f in files], dataset_name=USER)
        tasks = await get_just_chunks_tasks(chunker=JsonListChunker)
        # No connection test: this mode makes no LLM calls at all.
        async for _ in run_pipeline(
            tasks=tasks, datasets=[USER], skip_connection_test=True
        ):
            pass

    asyncio.run(build())
    return sum(len(json.loads(f.read_text())) for f in files)


def cognee_chunks_search(client: Any, query: str) -> str:
    cognee, search_type = client

    async def one() -> str:
        results = await cognee.search(
            query, query_type=search_type.CHUNKS, datasets=[USER], top_k=COGNEE_TOP_K
        )
        return "\n".join(_context(r) for r in results)

    return asyncio.run(one())


def _context(result: Any) -> str:
    payload = getattr(result, "search_result", result)
    if isinstance(payload, dict) and "search_result" in payload:
        payload = payload["search_result"]
    if isinstance(payload, list):
        return "\n".join(_context(item) for item in payload)
    if isinstance(payload, dict) and isinstance(payload.get("text"), str):
        return payload["text"]
    return payload if isinstance(payload, str) else json.dumps(payload, default=str)


def cognee_open(store: Path, prefix: str) -> Any:
    cognee = _cognee(store, prefix)
    from cognee.modules.search.types import SearchType  # type: ignore[import-not-found]

    return cognee, SearchType


def cognee_search(client: Any, query: str) -> str:
    cognee, search_type = client

    async def one() -> str:
        results = await cognee.search(
            query,
            query_type=search_type.HYBRID_COMPLETION,
            datasets=[USER],
            only_context=True,
            retriever_specific_config={
                "chunks_top_k": COGNEE_TOP_K,
                "entities_top_k": COGNEE_TOP_K,
            },
        )
        return "\n".join(_context(r) for r in results)

    return asyncio.run(one())


TOOLS = {
    "mem0": (mem0_index, mem0_open, mem0_search),
    "cognee": (cognee_index, cognee_open, cognee_search),
    # No-LLM modes (RFC-0004 C1a): each tool's raw retrieval over the same history.
    "mem0-raw": (mem0_raw_index, mem0_open, mem0_search),
    "cognee-chunks": (cognee_chunks_index, cognee_open, cognee_chunks_search),
}
MAX_UNPARSEABLE_SHARE = 0.01


def health_problem(stats: dict[str, int]) -> str | None:
    """Why a build's LLM calls make it unusable, or None (RFC-0004 build health)."""
    calls = stats.get("calls", 0)
    if stats.get("upstream_errors", 0):
        return f"{stats['upstream_errors']} LLM calls failed"
    if stats.get("model_mismatch", 0):
        return f"{stats['model_mismatch']} replies came from another model"
    if calls and stats.get("unparseable", 0) > MAX_UNPARSEABLE_SHARE * calls:
        return f"{stats['unparseable']} of {calls} JSON replies were unparseable"
    return None


def _reset(prefix: str) -> None:
    urllib.request.urlopen(f"{SHIM}/{prefix}/reset", timeout=30).read()


def main() -> None:
    command, tool = sys.argv[1], sys.argv[2]
    build, open_client, search = TOOLS[tool]
    if command == "index":
        root, store = Path(sys.argv[3]).resolve(), Path(sys.argv[4]).resolve()
        prefix = f"{tool}-{store.name}"
        _reset(prefix)
        t0 = time.perf_counter()
        items = build(root, store, prefix)
        seconds = round(time.perf_counter() - t0, 2)
        stats = shim_stats(prefix)
        problem = health_problem(stats) or (None if items >= 1 else "stored nothing")
        if problem:
            raise SystemExit(f"{tool} build for {root.name} refused: {problem}")
        (store / "build.json").write_text(
            json.dumps({"seconds": seconds, "items": items, "llm": stats})
        )
        return
    store = Path(sys.argv[3]).resolve()
    queries = json.loads(sys.stdin.read())
    out = []
    for number, query in enumerate(queries):
        prefix = f"{tool}-{store.name}-q{number}-{time.time_ns()}"
        try:
            # Opened before timing: every arm's query is timed on a warm client.
            client = open_client(store, prefix)
            t0 = time.perf_counter()
            context, error = search(client, query), None
        except Exception as exc:  # noqa: BLE001 - one failed query fails only its case
            t0 = time.perf_counter()
            context, error = "", f"{type(exc).__name__}: {exc}"[-500:]
        out.append(
            [context, round(time.perf_counter() - t0, 3), shim_stats(prefix), error]
        )
    print(json.dumps(out))


if __name__ == "__main__":
    main()
