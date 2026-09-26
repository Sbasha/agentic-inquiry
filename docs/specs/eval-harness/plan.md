# Plan: Evaluation harness (Level A/B/C) with competitor parity

## Approach

Build a top-level `evals/` package with the minimum number of modules:
- `data.py`: dataset loading, corpus materialization, gold labels and splits.
- `arms.py`: the five retrieval arms behind one contract.
- `metrics.py`: ranking metrics, budget rendering and paired statistics.
- `run.py`: orchestration, the index cache and the results JSON.
- `answer.py`: Level B.
- `agent.py`: Level C.
- `__main__.py`: the CLI.

Level A comes first because it is free and deterministic, and it gates every later retrieval change. Levels B and C reuse the budgeted hit rendering and the arm handles from Level A.

## Constraints

- No evaluation package in runtime dependencies (ADR-0006).
- Competitors run from isolated venvs under `~/.cache/agentic-inquiry-evals/venvs/`.
- Every corpus is read-only. Arms that write next to their input (Graphify writes `graphify-out/`) work on a hard-linked copy.

## Construction tests

- `tests/evals/test_data.py`: patch pre-image parsing, enclosing-function spans, split assignment, and LOCOMO and LongMemEval gold-unit extraction.
- `tests/evals/test_metrics.py`: nDCG, MRR, recall@k, budgeted coverage, bootstrap, permutation and MDE on hand-computed fixtures.
- `tests/evals/test_arms.py`: Graphify NODE-line parsing, RRF fusion, window chunking.
- `tests/evals/test_agent.py`: citation parsing.

## Design (LLD)

### Design decisions

- **One `Hit` shape for every arm:** `path`, `start`, `end`, `text`. `start` and `end` are 1-based and inclusive; 0 means the whole unit.
  - Memory corpora put a unit marker (`[D1:3]`, `session:<id>`) in each line, so a hit's covered units come from its rendered text. That makes chunked output (Inquiry) and unit output (baselines) comparable.
- **The budget is applied to the rendered output, not to hit counts.** Rendering is `== path:start-end ==` followed by the text, and it stops at the token budget line by line. Graphify's rendered output is its own NODE and EDGE text in its own order.
- **Index caching:** cache key = `arm`, arm config hash and corpus key. The `inquiry` config hash includes the git tree hash of `agentic_inquiry/` and `config/`, plus a hash of any uncommitted diff under those paths.
- **Dense embeddings** are cached in SQLite, keyed by `sha1(model, text)`. SWE-bench snapshots of the same repo share most windows.

### Data & schema

Results file `InquiryEval/v1`:
- `provenance`: `sha`, `dirty`, `started_utc`, dataset `sha256`, `arms{name: config}`, `competitors{name: version}`, `seed`
- `suite`, `split`, `budget_tokens`
- `rows[]`: `{arm, case_id, metrics{...}, latency_ms, returned_tokens}`
- `summary`: `{arm: {metric: mean}}`
- `comparisons[]`: `{metric, a, b, n, mean_diff, ci_low, ci_high, p_perm, mde}`

### Behavior & rules

**SWE-bench gold labels:**
- Parse the unified-diff hunks of `patch`. Each hunk's `-a,b` range gives pre-image lines: deleted lines are gold lines, and a pure insertion contributes the anchor line before it.
- Files created by the patch have no pre-image and are excluded from gold (they cannot be retrieved). A case whose gold is only new files is dropped and counted.
- Gold functions are the innermost enclosing `FunctionDef`, `AsyncFunctionDef` or `ClassDef` spans of the gold lines in the pre-image, parsed with `ast`. Lines outside any definition have no function gold.

**Sample:** seeded (20260926), stratified by repo, with caps summing to 150.

**Splits:** `int(sha256(case_id), 16) % 3 == 0` → dev, otherwise test.

### Failure, edge cases & resilience

- A failure to index or retrieve for one corpus is recorded in the row as `error`, with every metric set to 0 for that case. Failures are counted in the summary and never silently dropped.
- Graphify output with no NODE lines yields zero hits.

## Tasks

### T1: Data layer
Depends on: none
Goal: loaders for all five suites, SWE-bench materialization (`git archive` per base commit), gold labels and splits.
Tests: `tests/evals/test_data.py`.
Done when: tests pass, and `python -m evals cases --suite swebench` prints the sample counts per repo and split.

### T2: Metrics and statistics
Depends on: none
Tests: `tests/evals/test_metrics.py`.
Done when: tests pass.

### T3: Arms
Depends on: T1, T2
Goal: `bm25`, `bm25-paths`, `dense`, `hybrid`, `graphify` (isolated venv) and `inquiry`.
Mode: TDD for parsing and fusion; goal-based for model-backed arms.
Tests: `tests/evals/test_arms.py`, plus a goal check that each arm returns hits on the `requests` snapshot.

### T4: Runner and CLI
Depends on: T3
Goal: `python -m evals run` with the results JSON, a summary table and the cache.
Done when: SciFact BM25 reproduces the published value within 0.03 (AC6), and two runs match (AC7).

### T5: Baseline measurement
Depends on: T4
Goal: run Level A dev for all suites and arms, and commit the results JSON (AC1, AC7).
Mode: goal-based. Done when: `git ls-files evals/results` lists a dev results file per suite.

### T6: Level B (`answer.py`)
Depends on: T4
Tests: token-F1 and kappa unit tests. Done when: a 20-item smoke run completes.

### T7: Level C (`agent.py`)
Depends on: T4
Tests: citation-parser unit tests. Done when: a 3-task smoke run per arm completes.

### T8: Docs and claims
Depends on: T4
Mode: goal-based. Done when: `grep -n "10.0/10" README.md` is empty and `make help` lists `eval-dev`.
Goal: `evals/README.md`, `make eval-dev`, the `tests/golden/README.md` note, and removal of the "10/10" claims.

## Rollout

Developer tooling only; nothing ships to users. Retrieval changes that follow are specified separately (`docs/specs/retrieval-core/`), each measured with this harness.

## Risks

- **Index time for large SWE-bench repos (django, sympy).** Mitigation: cache per commit, dense embeddings cached by text, a parallel corpus pool, and dev at one third of the sample.
- **Subscription rate limits for Level B and C.** Mitigation: sampled sizes, resumable runs keyed by `(arm, case)`.
