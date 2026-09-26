"""Subprocess worker that runs the checked-out Agentic Inquiry package.

``index <root> <store>`` indexes a corpus into its own store; ``search <store>
<root> <request.json> <response.json>`` answers a batch of queries with the
same call the ``ai search`` CLI makes. One process per corpus keeps
configuration, singletons and model state from leaking between corpora.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ID = "eval"


def _configure(store: Path) -> None:
    os.environ.setdefault("INQUIRY_CONFIG", str(REPO_ROOT / "config" / "default.yaml"))
    os.environ["INQUIRY_STORAGE_ROOT"] = str(store)
    os.environ["INQUIRY_STORAGE_DEFAULT_PROJECT_ID"] = PROJECT_ID
    os.environ["INQUIRY_STORAGE_BACKEND"] = "lancedb"
    os.environ.setdefault("INQUIRY_LOGGING_LEVEL", "ERROR")
    # Keep runtime state out of the real home; corpora share the persistent
    # embedding cache kept there.
    from evals.data import CACHE

    os.environ.setdefault("INQUIRY_HOME", str(CACHE / "inquiry-home"))


async def _index(root: Path, store: Path) -> None:
    from agentic_inquiry.config import Config
    from agentic_inquiry.embeddings.factory import configure_embedder_for_backend
    from agentic_inquiry.indexing.pipeline import IndexingPipeline
    from agentic_inquiry.storage.facade import StorageFacade

    config = Config.load()
    configure_embedder_for_backend(config, quiet=True)
    storage = await StorageFacade.from_config(config, PROJECT_ID)
    t0 = time.perf_counter()
    try:
        pipeline = IndexingPipeline(storage, config, PROJECT_ID, project_root=str(root))
        result = await pipeline.index_directory(path=str(root), wait=True)
    finally:
        await storage.close()
    seconds = time.perf_counter() - t0

    import lancedb

    table = lancedb.connect(str(store / "lancedb")).open_table("document_chunks")
    paths = table.to_arrow().column("file_path").to_pylist()
    files = sorted({_relative(p, root) for p in paths if p})
    summary = {k: v for k, v in result.items() if isinstance(v, (int, float, str))}
    (store / "index.json").write_text(json.dumps({"seconds": round(seconds, 2), "result": summary, "files": files}))


def _relative(path: str, root: Path) -> str:
    real_root = os.path.realpath(root)
    real = os.path.realpath(path)
    if real.startswith(real_root + os.sep):
        return Path(real).relative_to(real_root).as_posix()
    return path


def _line(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return number if number > 0 else 0


async def _search(store: Path, root: Path, request: Path, response: Path) -> None:
    from agentic_inquiry.config import Config
    from agentic_inquiry.embeddings.factory import configure_embedder_for_backend
    from agentic_inquiry.embeddings.service import EmbeddingService
    from agentic_inquiry.search.service import SearchService
    from agentic_inquiry.storage.facade import StorageFacade

    payload = json.loads(request.read_text())
    config = Config.load()
    configure_embedder_for_backend(config, quiet=True)
    storage = await StorageFacade.from_config(config, PROJECT_ID)
    rows = []
    try:
        search = SearchService(storage, config)
        embeddings = EmbeddingService(config=config)
        await embeddings.embed_async("warmup")
        for query in payload["queries"]:
            t0 = time.perf_counter()
            vector = await embeddings.embed_async(query)
            results = await search.hybrid_search(
                query_vector=[float(x) for x in vector], query_fts=query, project_id=PROJECT_ID, limit=payload["k"]
            )
            latency = (time.perf_counter() - t0) * 1000
            hits = []
            for result in results:
                data = result.data if hasattr(result, "data") else result
                if not isinstance(data, dict):
                    continue
                start, end = _line(data.get("line_start")), _line(data.get("line_end"))
                hits.append({
                    "path": _relative(str(data.get("file_path", "")), root),
                    "start": start,
                    "end": max(end, start),
                    "text": str(data.get("content") or ""),
                })
            rows.append({"hits": hits, "latency_ms": round(latency, 2)})
    finally:
        await storage.close()
    response.write_text(json.dumps(rows))


def main(argv: list[str]) -> int:
    command = argv[0]
    if command == "index":
        root, store = Path(argv[1]), Path(argv[2])
        _configure(store)
        asyncio.run(_index(root, store))
    elif command == "search":
        store, root, request, response = map(Path, argv[1:5])
        _configure(store)
        asyncio.run(_search(store, root, request, response))
    else:
        raise SystemExit(f"unknown command {command}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
