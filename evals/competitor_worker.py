"""Build and query one live competitor inside its own virtualenv (RFC-0003 live arms).

Runs under the competitor venv's interpreter, so it imports only the standard
library at module level. The harness side is ``evals.arms.Competitor``.

    python competitor_worker.py index <tool> <corpus dir> <store dir>
    python competitor_worker.py search <tool> <store dir> <k>   < queries.json

``search`` prints one JSON list of ``[context text, milliseconds]`` per query.
Every LLM call goes to ``claude-haiku-4-5-20251001`` on the Claude
subscription: Graphify through its own ``claude-cli`` backend, the others
through the OpenAI-compatible shim at ``EVALS_SHIM_URL``. Embeddings come from
Ollama ``bge-m3``.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

MODEL = "claude-haiku-4-5-20251001"
SHIM = os.environ.get("EVALS_SHIM_URL", "http://127.0.0.1:8765/v1")
OLLAMA = "http://localhost:11434"
EMBED_MODEL = "bge-m3"
EMBED_DIMS = 1024
USER = "corpus"

_LINE = re.compile(r"^\[[^\]]+\]\s*(?P<body>.*)$")
_LME_DATE = re.compile(r"\((\d{4}/\d{2}/\d{2}) \(\w+\) (\d{2}:\d{2})\)")


def sessions(root: Path) -> list[Path]:
    """Session files in conversation order: by LongMemEval date, else by number in the name."""

    def key(path: Path) -> tuple[str, int, str]:
        first = path.read_text(encoding="utf-8").split("\n", 1)[0]
        date = _LME_DATE.search(first)
        number = re.search(r"(\d+)(?=\.\w+$)", path.name)
        return (
            " ".join(date.groups()) if date else "",
            int(number.group(1)) if number else 0,
            path.name,
        )

    return sorted((p for p in root.rglob("*") if p.is_file()), key=key)


def turns(path: Path) -> list[dict[str, str]]:
    """Chat messages for one session; the dialog id tag is dropped, the date kept."""
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _LINE.match(line)
        body = match.group("body") if match else line
        if not body.strip():
            continue
        role = "assistant" if re.search(r"\)\s*assistant:", body) else "user"
        out.append({"role": role, "content": body})
    return out


def _shim_env() -> None:
    os.environ.update(
        {
            "OPENAI_API_KEY": "shim",
            "OPENAI_BASE_URL": SHIM,
            "OPENAI_API_BASE": SHIM,
            # The Agents SDK uploads traces to OpenAI by default; eval data stays local.
            "OPENAI_AGENTS_DISABLE_TRACING": "1",
        }
    )


# --------------------------------------------------------------------------
# mem0: one add per session, search over extracted memories
# --------------------------------------------------------------------------


def _mem0(store: Path) -> Any:
    os.environ["MEM0_TELEMETRY"] = "False"
    from mem0 import Memory  # type: ignore[import-not-found]

    return Memory.from_config(
        {
            "llm": {
                "provider": "openai",
                "config": {"model": MODEL, "openai_base_url": SHIM, "api_key": "shim"},
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


def mem0_index(root: Path, store: Path) -> None:
    memory = _mem0(store)
    for path in sessions(root):
        memory.add(turns(path), user_id=USER)


def mem0_search(store: Path, queries: list[str], k: int) -> Iterator[str]:
    memory = _mem0(store)
    for query in queries:
        found = memory.search(query, top_k=k, filters={"user_id": USER})
        rows = found.get("results", found) if isinstance(found, dict) else found
        yield "\n".join(str(row.get("memory", "")) for row in rows)


# --------------------------------------------------------------------------
# OpenKB: compiled wiki per corpus, its query agent decides what to read
# --------------------------------------------------------------------------

OPENKB_MODEL = f"openai/{MODEL}"


def _openkb(*args: str, cwd: Path) -> None:
    binary = Path(sys.executable).parent / "openkb"
    # init prompts for an API key even with --model; an empty answer skips it.
    subprocess.run(
        [str(binary), *args],
        cwd=cwd,
        check=True,
        env=os.environ.copy(),
        input="\n",
        text=True,
    )


def openkb_index(root: Path, store: Path) -> None:
    _shim_env()
    store.mkdir(parents=True, exist_ok=True)
    _openkb("init", "--model", OPENKB_MODEL, "--language", "en", cwd=store)
    _openkb("add", str(root), cwd=store)


def _read_rank(call: str) -> int:
    """Source text first, synthesized pages next, the index listing last."""
    if "get_page_content" in call or "sources/" in call:
        return 0
    if "index.md" in call:
        return 2
    return 1


def openkb_search(store: Path, queries: list[str], k: int) -> Iterator[str]:
    _shim_env()
    from agents import Runner  # type: ignore[import-not-found]
    from agents.items import ToolCallItem, ToolCallOutputItem  # type: ignore[import-not-found]

    from openkb.agent.query import MAX_TURNS, build_query_agent  # type: ignore[import-not-found]

    agent = build_query_agent(str(store / "wiki"), OPENKB_MODEL, language="en")
    for query in queries:
        result = asyncio.run(Runner.run(agent, query, max_turns=MAX_TURNS))
        calls: dict[str, str] = {}
        reads: list[tuple[int, int, str]] = []
        for item in result.new_items:
            raw = item.raw_item
            if isinstance(item, ToolCallItem):
                call_id = str(getattr(raw, "call_id", None) or getattr(raw, "id", ""))
                calls[call_id] = (
                    f"{getattr(raw, 'name', '')} {getattr(raw, 'arguments', '')}"
                )
            elif isinstance(item, ToolCallOutputItem):
                call_id = (
                    raw.get("call_id", "")
                    if isinstance(raw, dict)
                    else getattr(raw, "call_id", "")
                )
                call = calls.get(call_id, "")
                reads.append(
                    (_read_rank(call), len(reads), f"## {call}\n{item.output}")
                )
        yield "\n".join(text for _, _, text in sorted(reads))


# --------------------------------------------------------------------------
# Graphify text path: semantic extraction, then its budgeted query
# --------------------------------------------------------------------------


def _graphify() -> str:
    return str(Path(sys.executable).parent / "graphify")


def _graphify_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.endswith("_API_KEY")}
    env["GRAPHIFY_CLAUDE_CLI_MODEL"] = MODEL
    return env


def graphify_index(root: Path, store: Path) -> None:
    tree = store / "tree"
    shutil.rmtree(tree, ignore_errors=True)
    store.mkdir(parents=True, exist_ok=True)
    subprocess.run(["cp", "-R", f"{root}/.", str(tree)], check=True)
    subprocess.run(
        [_graphify(), "extract", ".", "--backend", "claude-cli"],
        cwd=tree,
        env=_graphify_env(),
        check=True,
    )
    shutil.move(str(tree / "graphify-out" / "graph.json"), store / "graph.json")
    shutil.rmtree(tree)


def graphify_search(store: Path, queries: list[str], k: int) -> Iterator[str]:
    for query in queries:
        result = subprocess.run(
            [_graphify(), "query", query, "--budget", "2000", "--graph", "graph.json"],
            cwd=store,
            env=_graphify_env(),
            capture_output=True,
            text=True,
            check=True,
        )
        yield result.stdout


# --------------------------------------------------------------------------
# Cognee: add plus cognify per corpus, default (hybrid) search context
# --------------------------------------------------------------------------


def _cognee(store: Path) -> Any:
    os.environ.update(
        {
            "LLM_PROVIDER": "openai",
            "LLM_MODEL": f"openai/{MODEL}",
            "LLM_ENDPOINT": SHIM,
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
    import cognee  # type: ignore[import-not-found]

    return cognee


def cognee_index(root: Path, store: Path) -> None:
    cognee = _cognee(store)

    async def build() -> None:
        await cognee.add([str(p) for p in sessions(root)], dataset_name=USER)
        await cognee.cognify(datasets=[USER])

    asyncio.run(build())


def _cognee_text(result: Any) -> str:
    """The context inside a search result, without Cognee's answer-prompt wrapper."""
    payload = getattr(result, "search_result", result)
    if isinstance(payload, dict) and "search_result" in payload:
        payload = payload["search_result"]
    if isinstance(payload, list):
        return "\n".join(_cognee_text(item) for item in payload)
    if not isinstance(payload, str):
        return json.dumps(payload, default=str)
    _, marker, context = payload.partition("Context:\n")
    return context.strip().strip("`") if marker else payload


def cognee_search(store: Path, queries: list[str], k: int) -> Iterator[str]:
    cognee = _cognee(store)
    from cognee.modules.search.types import SearchType  # type: ignore[import-not-found]

    async def one(query: str) -> str:
        results = await cognee.search(
            query,
            query_type=SearchType.HYBRID_COMPLETION,
            datasets=[USER],
            only_context=True,
        )
        return "\n".join(_cognee_text(r) for r in results)

    for query in queries:
        yield asyncio.run(one(query))


TOOLS = {
    "mem0": (mem0_index, mem0_search),
    "openkb": (openkb_index, openkb_search),
    "graphify-text": (graphify_index, graphify_search),
    "cognee": (cognee_index, cognee_search),
}


def main() -> None:
    command, tool = sys.argv[1], sys.argv[2]
    build, search = TOOLS[tool]
    if command == "index":
        root, store = Path(sys.argv[3]).resolve(), Path(sys.argv[4]).resolve()
        t0 = time.perf_counter()
        build(root, store)
        (store / "build.json").write_text(
            json.dumps({"seconds": round(time.perf_counter() - t0, 2)})
        )
        return
    store, k = Path(sys.argv[3]).resolve(), int(sys.argv[4])
    queries = json.loads(sys.stdin.read())
    out = []
    t0 = time.perf_counter()
    for text in search(store, queries, k):
        out.append([text, (time.perf_counter() - t0) * 1000])
        t0 = time.perf_counter()
    print(json.dumps(out))


if __name__ == "__main__":
    main()
