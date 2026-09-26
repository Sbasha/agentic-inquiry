# Evaluation harness

`evals/` scores Agentic Inquiry retrieval against baselines and Graphify on
datasets whose labels were written by someone else. The protocol, the
pre-registered hypotheses and the split rules are
[RFC-0003](../docs/rfc/0003-eval-harness-and-competitor-parity.md). The
dependency policy is [ADR-0006](../docs/adr/0006-eval-dependencies-and-isolated-competitors.md).

## Levels

| Level | Command | Cost | What it measures |
| --- | --- | --- | --- |
| A | `python -m evals run --suite <suite> --split dev` | $0, deterministic | Retrieval quality within a token budget, per arm |
| B | `python -m evals answer --split dev --n 200` | subscription or Moonshot key | LOCOMO answer accuracy from each arm's context, two judges |
| C | `python -m evals agent --split test` | subscription | A tool-using code agent per arm: localization and tokens |

Run every command with the `eval` dependency group, `uv run --group eval python -m evals ...`. `make eval-dev` runs Level A dev for every suite.

## Suites

| Suite | Cases | Gold labels |
| --- | --- | --- |
| `swebench` | 150 SWE-bench Verified tasks (repo-stratified), each indexed at its `base_commit` | Gold patch pre-image lines, files and enclosing definitions |
| `erpnext` | 6 AFP ERPNext questions (test only) | Rubric evidence spans, read from the AFP checkout (`AFP_BENCH_ROOT`) |
| `locomo` | LOCOMO categories 1 to 4 | Evidence dialog IDs; split by conversation |
| `longmemeval` | LongMemEval-S cleaned, abstention questions excluded | Answer session IDs |
| `scifact` | BEIR SciFact test queries | Official qrels |

## Arms

| Arm | Definition |
| --- | --- |
| `bm25` | `bm25s`, English stopwords, Snowball stemmer, over fixed units (50-line code windows, one turn, one session, one abstract) |
| `bm25-paths` | The `bm25` ranking rendered as `path:start-end` pointers only; the control arm for pointer-shaped output |
| `dense` | `BAAI/bge-m3`, 512 tokens, cosine |
| `hybrid` | RRF (k=60) of `bm25` and `dense` |
| `graphify` | `graphifyy==0.9.68` from an isolated venv; code suites only |
| `inquiry` | The checked-out package: `IndexingPipeline` and `SearchService.hybrid_search` |

Every arm's hits are rendered in rank order and cut at a token budget
(tiktoken `cl100k_base`), so an arm pays for exactly what an agent would read.

## Results

`evals/results/<suite>/<split>-<utc>-<sha8>.json` (schema `InquiryEval/v1`)
holds the provenance, per-case metrics per arm, a summary per arm and paired
comparisons against `inquiry`. Each comparison carries a 95% cluster-bootstrap
CI, a permutation p-value and the minimum detectable effect. A `--split test`
run refuses a dirty tree and appends to `evals/results/test-ledger.jsonl`.

## Cache

Datasets, repository clones, snapshots, corpora, indexes, embeddings, the
Graphify venv and LLM completions live under `~/.cache/agentic-inquiry-evals/`
(override with `INQUIRY_EVAL_CACHE`). Indexes are keyed by arm configuration.
The `inquiry` key includes a hash of `agentic_inquiry/`, `config/` and any
uncommitted diff, so a code change re-indexes.
