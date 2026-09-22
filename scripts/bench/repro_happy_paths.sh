#!/usr/bin/env bash
# Reproduce /ai:search and /ai:index happy paths on a fixture and capture
# stdout for later regression comparison. Companion to tests/golden/bench.py
# for issue #156 (Cluster 0 — Pre-flight).
#
# Usage:
#   scripts/bench/repro_happy_paths.sh                 # run + write transcript
#
# /ai:onboard isn't reproducible from the CLI alone (it's a plugin skill that
# orchestrates multiple agents). Skipped here; the audit issue acknowledges
# this as a manual smoke step.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
# Bench artifacts live outside the repo so the indexer's gitignore walk
# doesn't exclude them — same reasoning as tests/golden/bench.py.
BENCH_ROOT="${TMPDIR:-/tmp}/ai-golden-bench/happy-paths"
TRANSCRIPT_FILE="$BENCH_ROOT/transcript.txt"

FIXTURE_PROJECT="happy_paths_fixture"
FIXTURE_CORPUS="$REPO_ROOT/agentic-inquiry/search"
BENCH_HOME="$BENCH_ROOT/home"

mkdir -p "$BENCH_ROOT"

export INQUIRY_STORAGE_ROOT="$BENCH_HOME"
export INQUIRY_STORAGE_DEFAULT_PROJECT_ID="$FIXTURE_PROJECT"
export INQUIRY_STORAGE_BACKEND="lancedb"
export INQUIRY_LOGGING_LEVEL="WARNING"

run_capture() {
    {
        echo "=== $1 ==="
        shift
        "$@" 2>&1 || echo "(exit $?)"
        echo
    }
}

{
    run_capture "ai --help" uv run --env-file .env ai --help
    run_capture "ai index $FIXTURE_CORPUS --skip-onboard-check --quiet" \
        uv run --env-file .env ai index "$FIXTURE_CORPUS" \
        --project "$FIXTURE_PROJECT" --skip-onboard-check --quiet
    run_capture "ai search 'hybrid search reranking'" \
        uv run --env-file .env ai search "hybrid search reranking" \
        --project "$FIXTURE_PROJECT" --limit 5
} > "$TRANSCRIPT_FILE"

echo "Transcript written: $TRANSCRIPT_FILE"
