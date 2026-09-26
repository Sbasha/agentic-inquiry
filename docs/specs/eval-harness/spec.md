# Spec: Evaluation harness (Level A/B/C) with competitor parity

Mode: full (new top-level directory, new dependency)

- **Status:** Implementing
- **Owner:** Sbasha
- **Plan:** [`plan.md`](plan.md)
- **Constrained by:** RFC-0003, ADR-0006
- **Contract:** none (developer tooling; the results schema is under Acceptance Criteria)

> **Spec contract:** this document defines what "done" means. The implementing
> PR must match this spec, or update it. Verification must be derivable from it.

## Objective

Give every search change a defensible number. `evals/` scores retrieval arms
(`bm25`, `dense`, `hybrid`, `graphify`, `inquiry`) on externally labelled
datasets under one adapter contract (Level A, $0), scores answer quality on a
sampled LOCOMO set (Level B), and scores a tool-using code agent per arm
(Level C). Every run writes a results JSON that pins code, data, models and
seeds, and reports paired differences with bootstrap CIs. The protocol and
pre-registered thresholds are RFC-0003.

## Boundaries

### Always do
- Use only external labels (SWE-bench Verified gold patches, LOCOMO evidence,
  LongMemEval answer sessions, BEIR SciFact qrels, AFP ERPNext evidence spans).
- Pair every comparison by query; report mean difference, 95% bootstrap CI,
  permutation p-value and MDE.
- Record code SHA, dirty flag, dataset file hashes, arm configuration and
  competitor versions in every results file.
- Tune on `dev` only; `test` runs at milestones.

### Ask first
- Any paid API call (Level B or C through a metered key).
- Changing a pre-registered threshold (RFC-0003 amendment).

### Never do
- Ship `evals/` in the wheel or add evaluation packages to runtime dependencies.
- Install a competitor into the project environment.
- Read `test` split results while tuning.

## Testing Strategy

- **TDD** - qrel derivation from patches, metrics, statistics, output parsers
  (Graphify NODE lines, agent citations), split assignment, token budgeting.
- **Goal-based check** - BM25 SciFact nDCG@10 lands within 0.03 of the
  published BEIR value (0.665); two runs of deterministic arms give identical
  per-query scores; `make eval-dev` completes.
- **Manual QA** - run `python -m evals run` end to end for each suite and read
  the summary table and results JSON.

## Acceptance Criteria

- [x] AC0 Query text is the dataset's question verbatim; for SWE-bench `problem_statement` only, never `hints_text`.
- [x] AC1 `python -m evals run --suite {swebench,erpnext,locomo,longmemeval,scifact} --arms ... --split {dev,test}` writes `evals/results/<suite>/<split>-<utc>-<sha8>.json` containing `schema: "InquiryEval/v1"`, provenance, per-query rows per arm and a summary with paired comparisons.
- [x] AC2 SWE-bench qrels come from the gold patch pre-image: changed files, changed line spans and enclosing Python function or class spans; unit tests cover add-only, delete-only, multi-hunk and new-file patches.
- [x] AC3 All five arms implement `index`/`retrieve`; `graphify` runs `graphifyy==0.9.68` from an isolated venv and its NODE output parses to hits; `inquiry` indexes through `IndexingPipeline` and queries `SearchService.hybrid_search`.
- [x] AC4 Metrics nDCG@10, MRR@10, recall@k, budgeted file / evidence recall (tiktoken `cl100k_base`) and function-level hit rate match hand-computed values in unit tests.
- [x] AC5 Paired bootstrap CI, sign-flip permutation p-value and MDE are deterministic under a fixed seed and unit-tested.
- [x] AC6 BM25 on SciFact test reproduces the published nDCG@10 within 0.03.
- [x] AC7 Deterministic arms produce identical per-query scores across two runs.
- [x] AC8 Level B: `python -m evals answer` produces answers from each arm's budgeted context, judged accuracy, LOCOMO token F1, and second-judge Cohen's kappa; model route is `claude-cli` by default and `moonshot` when `MOONSHOT_API_KEY` is set.
- [x] AC9 Level C: `python -m evals agent` runs a `claude -p` agent per arm with at most 14 turns, the floor tools plus exactly one MCP tool, parses `path:line` citations and scores cited gold-file recall and token usage.
- [x] AC10 `make eval-dev` runs Level A dev for every suite; `tests/golden/README.md` states the term-presence bench is a smoke test, not a quality measure.
- [x] AC11 The unmeasured "10/10" claims are removed from `README.md` and `docs/architecture/search.md`.
- [x] AC12 `evals/README.md` documents how to run each level, the cache layout and the results schema.
- [x] AC13 `--split test` refuses a dirty tree and appends `{utc, sha, suite, arms, rfc_sha256, summary, results}` to `evals/results/test-ledger.jsonl`; `evals/results/` is not gitignored.
- [x] AC14 LOCOMO splits by conversation (three lowest seeded hashes are dev); comparisons on SWE-bench and LOCOMO use a cluster bootstrap by repository and conversation.
- [x] AC15 Each dataset file is pinned by sha256 in `evals/data.py`; a mismatch refuses to run.
- [x] AC16 A comparison is marked invalid when either arm fails on more than 5% of its cases; per-arm failure counts appear in the summary.
- [x] AC17 Level C records the tool list each agent run reports and flags a run whose tools differ from its arm definition.

Results schema `InquiryEval/v1`: `provenance` (`sha`, `dirty`, `started_utc`,
`datasets` sha256, `arms{name: config}`, `seed`, `rfc_sha256`, `tokenizer`),
`suite`, `split`, `budget_tokens`, `rows[]` (`arm`, `case`, `metrics` or
`error`, `latency_ms`), `summary{arm: {cases, failures, failure_share,
p50_latency_ms, mean_index_s, metrics}}`, `comparisons[]` (`metric`, `a`, `b`,
`n`, `mean_diff`, `ci_low`, `ci_high`, `p_perm`, `mde`, `valid`, `clustered`).

## Assumptions

- SWE-bench Verified, LOCOMO, LongMemEval-S (cleaned) and BEIR SciFact stay downloadable from their public URLs.
- The Claude Code CLI (`claude -p`) is available for Level B and C; runs use the user's subscription, so marginal cost is zero but rate limits apply.
- Graphify builds code graphs without an LLM (`graphify update`), so it can run live on code corpora only.
