#!/usr/bin/env bash
# Reproduce /agv:search and /agv:index happy paths on a fixture and capture
# stdout for later regression comparison. Companion to tests/golden/bench.py
# for issue #156 (Cluster 0 — Pre-flight).
#
# Usage:
#   scripts/bench/repro_happy_paths.sh                 # run + write transcript
#
# /agv:onboard isn't reproducible from the CLI alone (it's a plugin skill that
# orchestrates multiple agents). Skipped here; the audit issue acknowledges
# this as a manual smoke step.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
# Bench artifacts live outside the repo so the indexer's gitignore walk
# doesn't exclude them — same reasoning as tests/golden/bench.py.
BENCH_ROOT="${TMPDIR:-/tmp}/agv-golden-bench/happy-paths"
TRANSCRIPT_FILE="$BENCH_ROOT/transcript.txt"

FIXTURE_PROJECT="happy_paths_fixture"
FIXTURE_CORPUS="$REPO_ROOT/agent-vault/search"
BENCH_HOME="$BENCH_ROOT/home"

mkdir -p "$BENCH_ROOT"

export AGV_STORAGE_ROOT="$BENCH_HOME"
export AGV_STORAGE_DEFAULT_PROJECT_ID="$FIXTURE_PROJECT"
export AGV_STORAGE_BACKEND="lancedb"
export AGV_LOGGING_LEVEL="WARNING"

run_capture() {
    {
        echo "=== $1 ==="
        shift
        "$@" 2>&1 || echo "(exit $?)"
        echo
    }
}

{
    run_capture "agv --help" uv run --env-file .env agv --help
    run_capture "agv index $FIXTURE_CORPUS --skip-onboard-check --quiet" \
        uv run --env-file .env agv index "$FIXTURE_CORPUS" \
        --project "$FIXTURE_PROJECT" --skip-onboard-check --quiet
    run_capture "agv search 'hybrid search reranking'" \
        uv run --env-file .env agv search "hybrid search reranking" \
        --project "$FIXTURE_PROJECT" --limit 5
} > "$TRANSCRIPT_FILE"

echo "Transcript written: $TRANSCRIPT_FILE"
