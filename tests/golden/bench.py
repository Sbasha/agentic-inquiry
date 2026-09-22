"""Golden-set bench: pin recall@10 + latency before deletion clusters land.

Indexes a fixed corpus (selected subdirs of this repo) into a temp LanceDB
project, runs the queries from ``tests/golden/queries.json``, and either
writes a baseline (``--pin``) or compares the run against the committed
baseline and exits non-zero on regression.

This is the safety net for issue #156. Re-run ``make bench-pin`` whenever
the corpus or query set changes deliberately; otherwise ``make bench``
should stay green.

Run modes:
    python tests/golden/bench.py            # compare against baseline
    python tests/golden/bench.py --pin      # regenerate baseline
    python tests/golden/bench.py --json     # machine-readable diff
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("golden-bench")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GOLDEN_DIR = REPO_ROOT / "tests" / "golden"
QUERIES_FILE = GOLDEN_DIR / "queries.json"
BASELINE_FILE = GOLDEN_DIR / "baseline.json"

# Bench artifacts live OUTSIDE the repo. The indexer walks up to the project
# root and applies .gitignore; anything under the repo's `.benchmarks/`
# matches `.benchmarks/` in .gitignore and gets excluded silently.
BENCH_ROOT = Path(tempfile.gettempdir()) / "ai-golden-bench"
RESULTS_FILE = BENCH_ROOT / "results.json"
BENCH_INDEX_DIR = BENCH_ROOT / "index"
BENCH_CORPUS_DIR = BENCH_ROOT / "corpus"
INDEX_STATE_FILE = BENCH_INDEX_DIR / "bench-state.json"

# Subset of the repo to index. Each subdir grounds at least one query in
# queries.json; without grounding, vector search returns near-random
# results in the top-10 and recall flips run-to-run. The list is the
# minimum that keeps every query reproducibly answered:
#   search        -> hybrid-search, async-patterns
#   storage       -> storage-facade, async-patterns
#   embeddings    -> embedding-generation
#   parsers       -> tree-sitter-parsing
#   indexing      -> indexing-pipeline, knowledge-graph
#   memory        -> memory-system
#   mcp           -> mcp-tools (without this, "MCP" is not in the corpus)
#   watching      -> file-watching
#   cache         -> document-cache
#   events        -> event-system
#   metrics       -> metrics-correlation
#   connectors    -> config-loading (yaml ignore patterns live here)
#   cli           -> error-handling (rich error surface for CLI commands)
# Re-pin baseline (`make bench-pin`) when this list changes.
CORPUS_SUBDIRS = [
    "search", "storage", "embeddings", "parsers", "indexing", "memory",
    "mcp", "watching", "cache", "events", "metrics", "connectors", "cli",
]

PROJECT_ID = "golden_bench"
SEARCH_LIMIT = 10
LATENCY_ITERATIONS = 5  # per-query reps; we take the min to suppress noise
LATENCY_REGRESSION_TOLERANCE = 1.20  # p95 may not exceed baseline x 1.20


def _run_git(args: list[str]) -> str:
    """Best-effort git metadata helper.

    Returns "" if git is missing (FileNotFoundError) or the command exits
    non-zero (CalledProcessError). Anything else propagates — we don't
    want to swallow programmer errors like passing a wrong type.
    """
    try:
        out = subprocess.check_output(
            ["git", *args], cwd=str(REPO_ROOT), stderr=subprocess.DEVNULL
        )
        return out.decode().strip()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return ""


_ENV_KEYS = (
    "INQUIRY_CONFIG",
    "INQUIRY_STORAGE_ROOT",
    "INQUIRY_STORAGE_DEFAULT_PROJECT_ID",
    "INQUIRY_STORAGE_BACKEND",
    "INQUIRY_LOGGING_LEVEL",
)

# Pin the config source. Without this, Config.load() walks cwd → INQUIRY_CONFIG →
# agentic-inquiry.yaml → config/default.yaml — meaning a developer or CI host
# with ~/.agentic-inquiry/config.yaml or a project-root agentic-inquiry.yaml that defines
# `storage.backends:` would silently override our LanceDB choice. Worse,
# StorageFacade.from_config() ignores the legacy `storage.backend` field
# (which our INQUIRY_STORAGE_BACKEND env override populates) when multi-backend
# `storage.backends` is present. Forcing INQUIRY_CONFIG at the repo's known-good
# default is the only way to guarantee the bench runs against the same
# config every time.
_BENCH_CONFIG_PATH = REPO_ROOT / "config" / "default.yaml"


def _setup_env(temp_root: Path) -> dict[str, str | None]:
    """Point ai at the bench index dir, isolated from any user state.

    Returns the previous values of every key it sets so the caller can
    restore them. Matters in the pytest path: the bench process otherwise
    leaves ``AI_*`` and ``agv_*`` set for the rest of the session, which
    would leak into co-running tests if anyone drops the ``slow`` marker.
    """
    prev: dict[str, str | None] = {k: os.environ.get(k) for k in _ENV_KEYS}
    os.environ["INQUIRY_CONFIG"] = str(_BENCH_CONFIG_PATH)
    os.environ["INQUIRY_STORAGE_ROOT"] = str(temp_root)
    os.environ["INQUIRY_STORAGE_DEFAULT_PROJECT_ID"] = PROJECT_ID
    # Force LanceDB regardless of any user overlay
    os.environ["INQUIRY_STORAGE_BACKEND"] = "lancedb"
    # Quiet the CLI banners
    os.environ.setdefault("INQUIRY_LOGGING_LEVEL", "WARNING")
    return prev


def _restore_env(prev: dict[str, str | None]) -> None:
    for k, v in prev.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _build_corpus_dir(staging: Path) -> tuple[Path, bool]:
    """Mirror the chosen subdirs into a staging dir for indexing.

    We copy (not symlink) because the indexing pipeline counts a symlinked
    directory as a single file and discards it as unparseable. The mirror
    only refreshes when the source mtime is newer than the staged copy,
    so subsequent runs are cheap.

    Returns:
        (staging_path, refreshed) — refreshed=True if any subdir was
        recopied this call. Callers use this to invalidate the LanceDB
        index, which would otherwise be stale relative to the new corpus.
    """
    import shutil

    staging.mkdir(parents=True, exist_ok=True)
    refreshed = False
    for sub in CORPUS_SUBDIRS:
        src = REPO_ROOT / "agentic_inquiry" / sub
        if not src.exists():
            logger.warning("Corpus subdir missing: %s", src)
            continue
        dst = staging / sub
        if dst.exists():
            # Cheap freshness check: if any source file is newer than the
            # staging dir's mtime, blow away and recopy. Avoids walking
            # both trees on every run.
            staging_mtime = dst.stat().st_mtime
            src_mtime = max(
                (p.stat().st_mtime for p in src.rglob("*") if p.is_file()),
                default=0,
            )
            if src_mtime <= staging_mtime:
                continue
            shutil.rmtree(dst)
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        refreshed = True
    return staging, refreshed


async def _index_corpus(corpus_path: Path) -> dict[str, Any]:
    from agentic_inquiry.config import Config
    from agentic_inquiry.embeddings.factory import configure_embedder_for_backend
    from agentic_inquiry.indexing.pipeline import IndexingPipeline
    from agentic_inquiry.storage.facade import StorageFacade

    config = Config.load()
    configure_embedder_for_backend(config, quiet=True)

    storage = await StorageFacade.from_config(config, PROJECT_ID)
    try:
        pipeline = IndexingPipeline(storage, config, PROJECT_ID, project_root=str(corpus_path))
        result = await pipeline.index_directory(path=str(corpus_path), wait=True)
        return result
    finally:
        await storage.close()


async def _run_queries(queries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from agentic_inquiry.config import Config
    from agentic_inquiry.embeddings.factory import configure_embedder_for_backend
    from agentic_inquiry.embeddings.service import EmbeddingService
    from agentic_inquiry.search.service import SearchService
    from agentic_inquiry.storage.facade import StorageFacade

    config = Config.load()
    configure_embedder_for_backend(config, quiet=True)

    storage = await StorageFacade.from_config(config, PROJECT_ID)
    try:
        search = SearchService(storage, config)
        embedding_service = EmbeddingService(config=config)
        # Warm up the embedder so the first query's latency isn't an outlier.
        await embedding_service.embed_async("warmup")

        rows: list[dict[str, Any]] = []
        for q in queries:
            query_text = q["query"]
            expected = [t.lower() for t in q.get("expected_contains", [])]

            query_vector = await embedding_service.embed_async(query_text)

            # Run each query LATENCY_ITERATIONS times and take the min.
            # Min-of-K is a standard bench technique: it strips noise
            # (GC pauses, OS scheduler hiccups, cache-cold first hit) and
            # converges on the steady-state cost we actually care about.
            results = None
            best_ms = float("inf")
            for _ in range(LATENCY_ITERATIONS):
                t0 = time.perf_counter()
                results = await search.hybrid_search(
                    query_vector=query_vector,
                    query_fts=query_text,
                    project_id=PROJECT_ID,
                    limit=SEARCH_LIMIT,
                )
                elapsed = (time.perf_counter() - t0) * 1000.0
                if elapsed < best_ms:
                    best_ms = elapsed
            latency_ms = best_ms

            # Per-query recall: fraction of expected terms found anywhere
            # in the top-K result content. Weak vs. labelled doc-IDs but
            # this is what queries.json encodes.
            content_blob = " ".join(_result_content(r) for r in results).lower()
            if expected:
                hits = sum(1 for term in expected if term in content_blob)
                recall = hits / len(expected)
            else:
                recall = 1.0 if results else 0.0

            rows.append({
                "id": q["id"],
                "query": query_text,
                "recall": round(recall, 4),
                "latency_ms": round(latency_ms, 2),
                "result_count": len(results),
            })
        return rows
    finally:
        await storage.close()


def _result_content(result: Any) -> str:
    """Extract content from a SearchResult or dict."""
    if isinstance(result, dict):
        return str(result.get("content") or result.get("text") or "")
    data = getattr(result, "data", None)
    if isinstance(data, dict):
        return str(data.get("content") or data.get("text") or "")
    return str(getattr(result, "content", "") or "")


def _read_index_state() -> dict[str, Any] | None:
    """Return the cached index build state if one exists."""
    try:
        return json.loads(INDEX_STATE_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _write_index_state(git_sha: str, git_dirty: bool) -> None:
    INDEX_STATE_FILE.write_text(
        json.dumps({"git_sha": git_sha, "git_dirty": git_dirty}, indent=2) + "\n"
    )


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    recalls = [r["recall"] for r in rows]
    latencies = [r["latency_ms"] for r in rows]
    return {
        "recall_at_10": round(statistics.mean(recalls), 4) if recalls else 0.0,
        "median_latency_ms": round(statistics.median(latencies), 2) if latencies else 0.0,
        "p95_latency_ms": round(_percentile(latencies, 95), 2) if latencies else 0.0,
        "query_count": len(rows),
    }


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * (pct / 100.0)
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    if lo == hi:
        return s[lo]
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _build_report(rows: list[dict[str, Any]], index_result: dict[str, Any]) -> dict[str, Any]:
    summary = _summarize(rows)
    return {
        "version": "1.0",
        "summary": summary,
        "config": {
            "backend": "lancedb",
            "search_limit": SEARCH_LIMIT,
            "corpus_subdirs": CORPUS_SUBDIRS,
        },
        "corpus": {
            "files_processed": index_result.get("files_processed"),
            "files_failed": index_result.get("files_failed"),
            "chunk_count": index_result.get("chunk_count")
                or index_result.get("chunks_indexed")
                or index_result.get("total_chunks"),
        },
        "git_sha": _run_git(["rev-parse", "HEAD"]),
        # Untracked files (Claude Code worktrees, IDE droppings, local .env)
        # don't affect reproducibility of the bench — only modified tracked
        # files do. --untracked-files=no makes the dirty bit mean what
        # callers actually want.
        "git_dirty": bool(_run_git(["status", "--porcelain", "--untracked-files=no"])),
        "per_query": rows,
    }


def _diff_against_baseline(report: dict[str, Any], baseline: dict[str, Any]) -> tuple[bool, list[str]]:
    """Return (passed, messages). Recall must not drop; p95 latency budget is
    baseline x LATENCY_REGRESSION_TOLERANCE.
    """
    messages: list[str] = []
    passed = True

    # Query-set drift check. If queries.json gains or loses an entry, the
    # aggregate recall is computed over a different denominator than the
    # baseline — the gate could pass while measuring less. Force a re-pin
    # for any deliberate query-set change.
    base_ids = sorted(r["id"] for r in baseline.get("per_query", []))
    cur_ids = sorted(r["id"] for r in report.get("per_query", []))
    if base_ids != cur_ids:
        passed = False
        added = sorted(set(cur_ids) - set(base_ids))
        removed = sorted(set(base_ids) - set(cur_ids))
        detail = []
        if added:
            detail.append(f"added: {added}")
        if removed:
            detail.append(f"removed: {removed}")
        messages.append(
            f"FAIL query set drift ({', '.join(detail)}). "
            f"Run `make bench-pin` to accept the new query set."
        )
        # Stop here — the rest of the comparison is meaningless when the
        # denominator changed.
        return passed, messages

    base_summary = baseline["summary"]
    cur_summary = report["summary"]

    if cur_summary["recall_at_10"] < base_summary["recall_at_10"] - 1e-6:
        passed = False
        messages.append(
            f"FAIL recall@10: {cur_summary['recall_at_10']:.4f} < baseline {base_summary['recall_at_10']:.4f}"
        )
    else:
        messages.append(
            f"  OK recall@10: {cur_summary['recall_at_10']:.4f} (baseline {base_summary['recall_at_10']:.4f})"
        )

    p95_budget = base_summary["p95_latency_ms"] * LATENCY_REGRESSION_TOLERANCE
    if cur_summary["p95_latency_ms"] > p95_budget:
        passed = False
        messages.append(
            f"FAIL p95 latency: {cur_summary['p95_latency_ms']:.1f}ms > budget {p95_budget:.1f}ms "
            f"(baseline {base_summary['p95_latency_ms']:.1f}ms × {LATENCY_REGRESSION_TOLERANCE})"
        )
    else:
        messages.append(
            f"  OK p95 latency: {cur_summary['p95_latency_ms']:.1f}ms (baseline {base_summary['p95_latency_ms']:.1f}ms, budget {p95_budget:.1f}ms)"
        )

    # Per-query recall regressions also fail the build. The aggregate
    # recall@10 check above can hide a 1.0 -> 0.0 swing on one query if
    # other queries improve to compensate — that's a real ranking
    # regression the gate must catch.
    base_per = {r["id"]: r for r in baseline.get("per_query", [])}
    cur_per = {r["id"]: r for r in report.get("per_query", [])}
    for qid, cur in cur_per.items():
        base = base_per.get(qid)
        if base is None:
            continue
        if cur["recall"] < base["recall"] - 1e-6:
            passed = False
            messages.append(
                f"FAIL recall regression on '{qid}': {cur['recall']:.2f} < baseline {base['recall']:.2f}"
            )

    return passed, messages


async def run_bench(reindex: bool = False) -> tuple[bool, list[str], dict[str, Any]]:
    """Public bench entry point.

    Indexes the corpus (if needed) and runs the query suite. Returns the
    diff against the pinned baseline. Both ``main()`` and the pytest
    wrapper call through here so the test stays insulated from the
    private helpers (``_setup_env``, ``_index_corpus``, etc.) which are
    free to be refactored.

    Args:
        reindex: If True, force a rebuild of the LanceDB index even if
            one exists. The function will also auto-reindex when
            ``_build_corpus_dir`` reports the staged corpus changed,
            so callers rarely need to pass this explicitly.

    Returns:
        ``(passed, messages, report)``. ``passed`` is True when no
        baseline regression was detected (or when there is no
        baseline yet — caller decides what that means). ``report`` is
        the full per-run summary that gets written to baseline.json
        on a pin.
    """
    BENCH_INDEX_DIR.mkdir(parents=True, exist_ok=True)
    prev_env = _setup_env(BENCH_INDEX_DIR)
    try:
        queries = json.loads(QUERIES_FILE.read_text())["queries"]
        current_git_sha = _run_git(["rev-parse", "HEAD"])
        current_git_dirty = bool(
            _run_git(["status", "--porcelain", "--untracked-files=no"])
        )
        index_state = _read_index_state()

        corpus, refreshed = _build_corpus_dir(BENCH_CORPUS_DIR)

        index_exists = (BENCH_INDEX_DIR / "lancedb").exists()
        needs_index = (
            reindex
            or refreshed
            or not index_exists
            or current_git_dirty
        )
        if not needs_index:
            needs_index = (
                index_state is None
                or index_state.get("git_sha") != current_git_sha
                or bool(index_state.get("git_dirty"))
            )

        if needs_index:
            # Wipe the old index when the corpus changed under our feet —
            # otherwise the LanceDB tables hold stale chunks alongside fresh
            # ones and recall numbers stop reflecting the staged corpus.
            if refreshed and (BENCH_INDEX_DIR / "lancedb").exists():
                import shutil
                logger.info("Corpus refreshed; wiping stale index at %s", BENCH_INDEX_DIR)
                shutil.rmtree(BENCH_INDEX_DIR / "lancedb", ignore_errors=True)
            logger.info("Indexing corpus at %s ...", corpus)
            index_result = await _index_corpus(corpus)
            logger.info("Index complete: %s", index_result.get("status"))
        else:
            logger.info("Reusing existing bench index at %s (use --reindex to rebuild)", BENCH_INDEX_DIR)
            index_result = {"status": "reused"}

        rows = await _run_queries(queries)
        report = _build_report(rows, index_result)

        RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        RESULTS_FILE.write_text(json.dumps(report, indent=2) + "\n")
        _write_index_state(report["git_sha"], report["git_dirty"])

        if not BASELINE_FILE.exists():
            return True, ["(no baseline yet)"], report

        baseline = json.loads(BASELINE_FILE.read_text())
        passed, messages = _diff_against_baseline(report, baseline)
        return passed, messages, report
    finally:
        _restore_env(prev_env)


async def _run_async(args: argparse.Namespace) -> int:
    passed, messages, report = await run_bench(reindex=args.reindex)

    if args.pin:
        BASELINE_FILE.write_text(json.dumps(report, indent=2) + "\n")
        print(f"Pinned baseline: {BASELINE_FILE}")
        print(f"  recall@10:        {report['summary']['recall_at_10']:.4f}")
        print(f"  median latency:   {report['summary']['median_latency_ms']:.1f}ms")
        print(f"  p95 latency:      {report['summary']['p95_latency_ms']:.1f}ms")
        return 0

    if messages == ["(no baseline yet)"]:
        print(f"No baseline at {BASELINE_FILE}. Run with --pin to create one.", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({"passed": passed, "report": report["summary"], "messages": messages}, indent=2))
    else:
        for m in messages:
            print(m)
        print(f"\nDetails: {RESULTS_FILE}")

    return 0 if passed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Golden-set recall@10 + latency bench")
    parser.add_argument("--pin", action="store_true", help="Write baseline.json (regenerate the pinned baseline)")
    parser.add_argument("--reindex", action="store_true", help="Rebuild the bench index even if it exists")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable diff")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return asyncio.run(_run_async(args))


if __name__ == "__main__":
    sys.exit(main())
