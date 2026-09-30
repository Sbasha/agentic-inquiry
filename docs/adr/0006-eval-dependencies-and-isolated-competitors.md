# ADR-0006: Evaluation dependencies live in an optional group; competitors run in isolated environments

- **Status:** Accepted
- **Date:** 2026-09-26
- **Decision-makers:** Sbasha
- **Supersedes:** none
- **Related:** RFC-0003, `docs/specs/eval-harness/spec.md`

## Decision summary

- **Decision:** We add `bm25s` to a new optional `eval` dependency group, and run competitor tools (Graphify `graphifyy==0.9.68`) from isolated virtual environments that the harness creates. Competitor tools never become project dependencies.
- **Because:** the runtime wheel must not carry evaluation code or a competitor's dependency tree, and a competitor has to run exactly as a user would install it.
- **Applies to:** `pyproject.toml` `[dependency-groups].eval`, `evals/`, and the harness cache under `~/.cache/agentic-inquiry-evals/`.
- **Tradeoff accepted:** the first run downloads the competitor packages and embedding models, and needs network access.
- **Revisit if:** `bm25s` becomes unmaintained, or a competitor adapter needs an in-process API that its CLI does not expose.

## Context

RFC-0003 needs a neutral lexical baseline and live competitor arms.

The runtime already depends on `tantivy` through LanceDB FTS, but that path belongs to the system under test. A baseline built on it would inherit our tokenisation and schema choices, so it would not be independent.

Graphify ships as a CLI package with its own dependency tree: networkx, tree-sitter grammars, rapidfuzz and graspologic. Installing it into the project environment could change the resolved versions that Agentic Inquiry itself runs on.

## Decision

- **Lexical baseline.** `bm25s` is a small, widely used BM25 implementation (Lucene variant, sparse scoring) with no service process. It sits in `[dependency-groups].eval`, so `uv sync --group eval` installs it and the wheel never includes it.
- **Dense baseline.** It reuses the existing `sentence-transformers` runtime dependency with `BAAI/bge-m3`. No new package is needed.
- **Competitors.** Each is installed with `uv venv` and `uv pip install <pinned spec>` under `~/.cache/agentic-inquiry-evals/venvs/<name>-<version>`. The harness calls it through its CLI or its MCP server. The pinned version is a constant in `evals/arms.py` and is recorded in every results file.

## Decision drivers

- Keep the runtime dependency surface unchanged.
- A baseline must be independent of the system under test.
- A competitor must run the way its users install it.

## Consequences

- Positive: results name exact competitor versions, and upgrading a competitor is a one-line pin change.
- Negative: the first run needs network access to fetch packages, models and datasets.

## Confirmation

- **Mode:** reviewer-checked.
- **Signal:** `pyproject.toml` `[project].dependencies` gains no evaluation package, and every results JSON records `competitors.<name>.version`.
- **Owner:** Sbasha.

## Alternatives considered

- **`rank-bm25`.** Pure Python, and slow on 10^5-window corpora. Rejected on runtime cost.
- **Using the LanceDB FTS as the baseline.** Not independent of the system under test. Rejected.
- **Adding `graphifyy` to the `eval` group.** Its dependency tree would resolve together with ours and could shift shared pins. Rejected.

## References

- `bm25s`: https://github.com/xhluca/bm25s
- Graphify v8: https://github.com/Graphify-Labs/graphify/tree/v8
