# RFC-0003: Evaluation harness and competitor parity

- **Status:** Accepted
- **Author:** Sbasha
- **Approver:** Sbasha
- **Date opened:** 2026-09-26
- **Date closed:** 2026-09-26
- **Decision weight:** standard
- **Related:** RFC-0001 (golden bench, superseded by this RFC as a quality gate), ADR-0004, ADR-0006, `docs/specs/eval-harness/spec.md`

## Reviewer brief

- **Decision:** add a top-level `evals/` harness that scores Agentic Inquiry against baselines and Graphify on externally labelled datasets. This document is also the pre-registered protocol.
- **Recommended outcome:** accept.
- **Change if accepted:**
  - a new `evals/` package with three evidence levels
  - an optional `eval` dependency group
  - the term-presence golden bench stops being a quality gate
- **Affected surface:** a new top-level directory, `pyproject.toml`, `Makefile`, `.gitignore`, `tests/evals/`. No runtime package code.
- **Stakes:** reversible. The harness ships outside the wheel.
- **Review focus:**
  - whether the metrics are fair to arms whose output shape differs (code chunks, one-line graph nodes, single conversation turns)
  - whether the split and test-run rules make the pre-registered thresholds binding
- **Not in scope:**
  - retrieval changes (later PRs, each measured here)
  - Graphify's unreleased BGE-m3/SurrealDB engine

## The ask

**Recommendation.** Accept `evals/` as the only source of search-quality claims.

**Why now.**
- **Situation.** Search has been retuned repeatedly (RRF constants, boosts, thresholds), then rewritten, then replaced by an imported codebase.
- **Complication.**
  - The only automated gate scores 1.0 on all 15 queries. Most expected terms are words from the query itself, and the corpus is our own source.
  - The one independent measurement (AFP, a 20-query SciFact sample) put plain BM25 at nDCG@10 0.60 and us at 0.33.
  - Competitor claims (Graphify BENCHMARKS.md) come from an unpublished harness, with n=6 code questions.
- **Question.** How do we get defensible, repeatable numbers at close to zero cost?

| ID | Question | Recommendation | Why | Decide by | Reviewer action |
| --- | --- | --- | --- | --- | --- |
| D1 | Where does the harness live? | Top-level `evals/`, outside the wheel | Runs before any search change merges; never ships to users | this review | confirm |
| D2 | What labels? | Only labels that already exist, authored by others (see Level A) | No self-authored answers, no leakage, no cost | this review | confirm the datasets |
| D3 | How is Graphify compared? | Live `graphifyy==0.9.68` on code corpora through the same contract. Its self-reported memory numbers go only in a separate "reported" table | Its harness and benchmark engine are unpublished | this review | confirm |
| D4 | What counts as "differentiated"? | The pre-registered hypotheses below | Stops the goalposts moving after results arrive | this review | confirm thresholds |

## Problem & goals

**Problem.** No measurement in the repository can show that a search change helps, so tuning follows anecdote.

**Goals.**
- Deterministic, zero-cost retrieval metrics (Level A) comparing every arm under one contract.
- Cheap sampled answer-quality metrics (Level B), plus agent-level confirmation (Level C) at zero marginal cost.
- Paired, cluster-aware statistics with a pre-registered minimum detectable effect.
- Results JSON that pins code, data, models and seeds.

**Non-goals.**
- Reproducing Graphify's unpublished LOCOMO adapter or SurrealDB engine.
- Hand-authored question sets for Level A.
- Paid API runs when no key is configured. The Moonshot `kimi-k2.6` route (Graphify's model) is supported when a key exists.

## Proposal

### Adapter contract

Every arm implements:
- `index(corpus) -> handle`
- `search(handle, queries, k=50) -> ranked hits`

A hit is `(path, start, end, display text)`. The runner renders each arm's hits in rank order and stops at the token budget, one line at a time, counting with tiktoken `cl100k_base`. An arm pays for exactly what an agent would read.

| Arm | Definition |
| --- | --- |
| `bm25` | `bm25s` (Lucene BM25, English stopwords, Snowball stemmer) over retrieval units. Display: `== path:start-end ==` followed by the unit text |
| `bm25-paths` | Control arm. The same ranking as `bm25`, displayed as one `path:start-end` line per hit with no text. It shows how a list of pointers scores on each metric |
| `dense` | `BAAI/bge-m3`, normalized, cosine, max 512 tokens per unit. Same display as `bm25` |
| `hybrid` | RRF (k=60) of the top 100 from `bm25` and `dense`. Same display |
| `graphify` | Live `graphifyy==0.9.68` in an isolated venv. `graphify update` builds the graph (AST only, no LLM). `graphify query "<q>" --budget 100000 --graph …` is called so that our 2,000-token cut, not Graphify's own estimator, is the one that binds. Every output line is displayed verbatim in Graphify's order. `NODE … src=<path> loc=L<n>` lines become hits covering line `n` |
| `inquiry` | The package at the checked-out SHA: `IndexingPipeline` for indexing, and `SearchService.hybrid_search` for search (the entry point `ai search` and the MCP search tool call). Display: `== path:start-end ==` followed by the chunk content |

Units for `bm25`, `dense` and `hybrid` are fixed:

| Corpus | Unit |
| --- | --- |
| Code | 50-line windows, stride 50, no overlap, over text files under 1 MB |
| LOCOMO | One turn per unit |
| LongMemEval | One session per unit |
| SciFact | One abstract per unit |

All arms read the same materialized files. For each case and arm, the harness reports the share of gold files present in that arm's index.

**Query text is the dataset's question verbatim.** For SWE-bench that means `problem_statement` only; `hints_text` is never used.

**Failures:**
- A per-arm, per-corpus timeout of 30 minutes to index and 120 s per query.
- A failed case is kept in the per-arm failure rate and dropped from the paired comparison (it is a harness defect, not a score).
- A comparison is invalid when either arm fails on more than 5% of cases.

### Level A: $0, deterministic

| Suite | Cases | Gold | Split unit |
| --- | --- | --- | --- |
| `swebench` | SWE-bench Verified, seeded (20260926) repo-stratified sample of 150; each indexed at `base_commit` | Pre-image lines of the gold patch, their files, and the innermost enclosing `def`/`class` (for an insertion, the innermost definition containing both neighbouring lines) | task id |
| `erpnext` | The 6 AFP ERPNext questions at `df8b7f9648c2`; rubrics read in place from the AFP checkout | Evidence path and line spans of each fact | test only |
| `locomo` | LOCOMO categories 1 to 4 (1,540 questions); category 5 (adversarial) excluded, as in the mem0 and Zep literature | Normalized `evidence` dialog IDs present in the conversation | conversation id |
| `longmemeval` | LongMemEval-S cleaned, `_abs` questions excluded | `answer_session_ids` | question id |
| `scifact` | BEIR SciFact test set, 300 queries | Official qrels | query id |

The SWE-bench caps are: django 42, sympy 20, sphinx 15, matplotlib 15, scikit-learn 15, astropy 10, xarray 10, pytest 10, pylint 5, requests 5, seaborn 2, flask 1.

**Metrics.** B denotes the 2,000-token budget; the same metrics are also reported at 1,000, 4,000 and 8,000 tokens.

| Suite | Primary (within B) | Co-primary | Secondary |
| --- | --- | --- | --- |
| Code | **function hit rate**: the share of gold definitions that have at least one rendered line (a code line, or a Graphify NODE location) inside their span | **evidence line recall**: gold lines rendered as text. A NODE line renders its location only, so pointer-only arms score near zero here by construction, and `bm25-paths` shows that floor | file recall; file nDCG@10 and MRR@10 in presentation order; acc@5; latency; index time; returned tokens |
| Memory | **unit recall**: gold units in the rendered text | none | recall@10 over the first 10 distinct units in rank order (recall_any@10 and recall_all@10 for LongMemEval) |
| SciFact | nDCG@10 over documents in rank order | none | recall@100 |

### Level B: sampled answer quality

- **Sample:** 200 LOCOMO test-split questions, stratified by category.
- **Context:** each arm's rendered text within 2,000 tokens.
- **Answerer:** `claude -p --model claude-haiku-4-5-20251001`, the same for every arm.
- **Primary judge:** `claude -p --model claude-sonnet-5`, using the pinned mem0-style CORRECT/WRONG prompt in `evals/answer.py`.
- **Second judge:** from a different model family, zero cost. A local open-weights model through Ollama, pinned by digest in the results.
- **Also reported:** LOCOMO's official token F1.
- **Kimi route:** with `MOONSHOT_API_KEY`, the answerer and primary judge become `kimi-k2.6` (Graphify's model).
- **Answer text and judge prompts** are retained in the results.

### Level C: agent localization

- **Agent:** `claude -p --model claude-sonnet-5`, at most 14 turns.
- **Isolation:**
  - cwd is the read-only task snapshot, outside any repository (the agent has no write tools)
  - `--setting-sources project` (the snapshot has no `.claude/`, so no user plugins, hooks or skills load)
  - `--disable-slash-commands`, `--strict-mcp-config` with the arm's MCP server only
  - `--allowedTools` names Grep, Glob, Read and that arm's MCP tools, and every other built-in tool is disallowed
  - the tool manifest the agent reports is recorded per run and checked against the arm definition
- **Arms:**
  - floor (no MCP server)
  - floor plus Graphify's MCP server (`query_graph` and its node tools)
  - floor plus Agentic Inquiry's MCP server (its search tools)
- **Tasks:**
  - the first 30 SWE-bench test-split tasks by the seeded hash, with prompt = `problem_statement` plus a fixed instruction to list the code locations to change as `path:line`
  - the 6 ERPNext questions, answered with citations
- **Scoring:** only the first 5 distinct cited files count. Reported per run: cited gold-file recall, citation precision, gold-function hit, turns, and provider-reported tokens.
- **Repeats:** 3 per task and arm, averaged per task before pairing.
- **Contamination caveat.** SWE-bench Verified predates the model, and memorized locations lift every arm equally, which compresses the differences between them. The ERPNext questions were written after the model's training data.

### Statistics

- Comparisons are paired by case.
- **CI:** a 95% bootstrap CI (10,000 resamples, seed 20260926) that resamples clusters: repositories for SWE-bench, conversations for LOCOMO, cases otherwise.
- **p-value:** a sign-flip permutation p-value on case differences.
- **MDE:** at 80% power, computed from the dev-split SD and recorded in the test ledger before the first test run.

### Splits and test runs

- A suite assigns a case to `dev` when `sha256(split unit) mod 3 == 0`, and to `test` otherwise. LOCOMO splits by conversation, so no dev turn appears in a test haystack.
- Tuning reads `dev` only.
- `--split test` refuses to run on a dirty tree. It appends `{utc, sha, suite, arms, rfc_sha256, summary}` to the committed `evals/results/test-ledger.jsonl`.
- **Every** test run is reported, never only the best.
- Changing a threshold after any test run requires a superseding RFC that cites the ledger.

### Pre-registered hypotheses (test split)

"Beats" means that the 95% cluster-bootstrap CI of the paired difference excludes 0 against **every** listed baseline. This is an intersection-union test, so no multiplicity correction is needed.

1. **H1, code localization (Level A, SWE-bench).**
   - `inquiry` beats `bm25`, `dense`, `hybrid` and `graphify` on function hit rate within budget.
   - `inquiry` is at least as good as `hybrid` on evidence line recall within budget: CI lower bound ≥ -0.02.
2. **H2, text retrieval (Level A, SciFact).** `inquiry` is at least as good as `bm25` on nDCG@10: CI lower bound ≥ -0.01.
3. **H3, conversation memory (Level A, LOCOMO and LongMemEval).** `inquiry` beats `bm25`, `dense` and `hybrid` on unit recall within budget.
4. **H4, answers (Level B).** `inquiry` context beats the best baseline context (by dev accuracy) on judged accuracy, with judge agreement κ ≥ 0.6. Below that agreement, only token F1 is reported.
5. **H5, agent (Level C).** Floor plus `inquiry` beats floor-only and floor plus `graphify` on per-task mean gold-function hit, without increasing median input tokens: the CI upper bound of the token ratio is ≤ 1.10.

A hypothesis that fails is reported as failed.

### Reported numbers from competitors

A separate table reproduces Graphify BENCHMARKS.md values with their n, judge and harness caveats:
- LOCOMO recall@10: 0.497 graph-expand, 0.362 BM25, 0.439 dense
- LongMemEval-S recall@10: 0.844, 0.710 and 0.848 respectively

Our `bm25` and `dense` rows are shown beside them only as a calibration check of the unit definition. They are never compared to our `inquiry` score.

## Options considered

The axis is who authors the labels:

| Option | Who labels | Verdict |
| --- | --- | --- |
| Extend the term-presence golden bench | Us, by picking terms | Rejected. It already scores 1.0 everywhere and uses our own source as the corpus. |
| Hand-author question and answer sets | Us or a contractor | Rejected for Level A: cost and author bias. Only the six independently authored AFP ERPNext questions are used. |
| Externally labelled public benchmarks | Dataset authors | **Chosen.** Free, public, and standard in the literature. |
| Extend the AFP harness | AFP authors | Rejected as the primary route because of its operating cost. It remains the independent cross-project study. |

## Consequences

- A search change is not merged without Level A dev deltas against the pinned baseline results file `evals/results/baseline-dev.json`. A regression on a primary metric larger than its dev CI half-width needs a stated reason.
- The unmeasured "10.0/10" claims are withdrawn from `README.md` and `docs/architecture/search.md`.
- Indexing a SWE-bench snapshot per task costs compute, not money. Indexes are cached by arm configuration hash, repository and commit.
- **Known confounds, reported rather than removed:**
  - each arm's index file coverage
  - the embedder truncation (BGE-m3 at 512 tokens; the Inquiry embedder at its own limit)
  - a shared model family between the Level B answerer and primary judge, which is equal across arms because the design is paired
