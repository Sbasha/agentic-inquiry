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
| B | `python -m evals answer --split dev --n 200` | subscription or Moonshot key | LOCOMO (or `--suite longmemeval`, `--n` per question type) answer accuracy from each arm's context, two judges |
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

Level B also takes live competitors that rewrite content, so they have no
source spans for Level A. Each is built and queried by
`evals/competitor_worker.py` inside its own venv, and its context is the
tool's native query output:

| Arm | Build | Context |
| --- | --- | --- |
| `graphify-text` | `graphifyy==0.9.68`, `graphify extract` with its `claude-cli` backend | `graphify query --budget 2000` |
| `mem0` | `mem0ai==2.2.1`, one `add` per session, local Qdrant | `search` memories |
| `openkb` | `openkb==0.4.5`, `openkb add` over the corpus | pages and excerpts its query agent read, source excerpts first |
| `cognee` | `cognee==1.6.1`, `add` plus `cognify` | default `HYBRID_COMPLETION` search with `only_context` |

Their LLM calls use `claude-haiku-4-5-20251001` on the Claude subscription.
Graphify calls `claude -p` itself; the others need the OpenAI-compatible shim
running first: `uv run --group eval python -m evals.claude_shim` (responses
cached under `llm-shim/`). Embeddings come from Ollama `bge-m3`.

Every arm's hits are rendered in rank order and cut at a token budget
(tiktoken `cl100k_base`), so an arm pays for exactly what an agent would read.

## Level C runs

Each run is `claude -p` in the task's read-only snapshot, with `--setting-sources project` (no user settings, plugins or hooks), `--strict-mcp-config`, the floor tools Read, Grep and Glob, and at most 14 turns.

| Arm | MCP server | Tools the agent sees |
| --- | --- | --- |
| `floor` | none | Read, Grep, Glob |
| `graphify` | `graphify-mcp` over the task's graph | the floor plus `query_graph`, `get_node`, `get_neighbors`, `shortest_path`, `god_nodes`, `graph_stats`, `get_community` |
| `inquiry` | `ai mcp --tools search` over the task's index | the floor plus `search` |

- Tool arms get a parallel one-paragraph usage note (`ARM_GUIDANCE` in `evals/agent.py`), adapted from Graphify's always-on CLAUDE.md text.
- The prompt states the tool-call budget and asks for `LOCATIONS:` with up to five `path:line` lines.
- A run whose recorded tool list or server status does not match its arm is invalid and excluded, not scored.

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
