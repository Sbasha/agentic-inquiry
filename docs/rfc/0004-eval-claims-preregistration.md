# RFC-0004: Claims, benchmarks and pre-registration for comparing Agentic Inquiry

- **Status:** Accepted
- **Author:** Sbasha
- **Approver:** Sbasha
- **Date opened:** 2026-09-27
- **Date closed:** 2026-09-27
- **Decision weight:** heavy
- **Related:** RFC-0003 (superseded for all future test runs), ADR-0006, ADR-0008

## The ask

**Recommendation.** Replace RFC-0003's hypotheses with the three claims below. Test each once, with the smallest sample that can show a statistically significant result, with every tool run under the same conditions and measured on effectiveness, time and cost.

**Why.** RFC-0003 compared Agentic Inquiry (`inquiry`) with retrieval baselines rather than with working without a tool, never ran the competitors under equal conditions, and registered a memory test (LOCOMO, 7 conversations) too small to reach significance.

Decisions taken (the owner accepted the recommendations on 2026-09-27):

| ID | Question | Decision |
| --- | --- | --- |
| D1 | Smallest gap the tests must detect | About 15 to 18 points of accuracy |
| D2 | "No tool" for memory | The whole conversation history in the prompt |
| D3 | Coding-agent tasks | A new set mined from fixes merged after the agent model's training cutoff |
| D4 | Graphify on memory | Not tested; Graphify is compared on code only |

## Claims

| Claim | Benchmark | Arms | Effectiveness metric |
| --- | --- | --- | --- |
| **C1. Memory retrieval.** `inquiry` gives an LLM better context for questions about past conversations | LongMemEval-S test split, 100 questions: the lowest seeded hashes within each question type, abstention questions excluded | `inquiry`, no tool (full history in the prompt), `mem0`, `cognee` | Judged answer accuracy |
| **C2. Code retrieval.** `inquiry` returns the code a fix must change more often | SWE-bench Verified: the 104 test-split tasks of the RFC-0003 sample (its 46 dev tasks were used for tuning), each at its base commit | `inquiry`, `graphify`, `cognee` (if its released code pipeline indexes the repositories; otherwise reported as not applicable) | The changed function is inside the returned context |
| **C3. Coding-agent outcomes.** An agent with `inquiry` locates the code to change more often | 100 tasks mined from fixes in public Python repositories with GitHub issue trackers, merged on or after 2026-02-01 (the agent model's training data ends January 2026): the linked issue text is the task, the functions the fix changed are the answer | agent with grep and read only (no tool); plus `inquiry`; plus `graphify` | The agent names a changed function |

Working without a tool is tested where it is meaningful: C1 (full history in the prompt) and C3 (grep and read). C2 compares retrieval tools with each other. ERPNext (6 questions) and LOCOMO are reported as illustrations, never as evidence for a claim.

## Samples

- **C1.** From the LongMemEval-S test split (293 questions without abstention), 100 questions allocated to question types in proportion to their counts, taking the lowest `sha256("20260926:" + question_id)` within each type.
- **C2.** All 104 test-split tasks of the RFC-0003 SWE-bench Verified sample.
- **C3.** Mined once, before any C3 run, from merged pull requests that:
  - were merged between 2026-02-01 and 2026-09-26;
  - close exactly one issue, created on or after 2026-02-01, whose title and body together are 100 to 20,000 characters;
  - change 1 to 5 Python files outside tests (a path with a `tests` or `testing` directory, a `test_*.py` or `*_test.py` file, or `conftest.py` counts as a test);
  - change at least one existing function or class in those files.

  The task is the issue title and body. The code is the repository at the merge commit's first parent. The answer is the changed functions in the non-test Python files. Per repository, the eligible pull requests with the lowest `sha256("20260926:" + task id)` are taken, up to: pytest 15, sympy 15, matplotlib 15, scikit-learn 15, astropy 15, pylint 15, xarray 10. The task list, with each issue text, is committed before any C3 run.

## Measurements, for every tool and every item

| Phase | Effectiveness | Time | Cost |
| --- | --- | --- | --- |
| Setup (index or ingest) | Completed; items stored | Wall-clock build time | LLM calls, input and output tokens, dollars; disk size |
| Query | Context returned | Latency | Context tokens; LLM calls and tokens at query time |
| Answer or agent run | Correct or not | Wall-clock | Tokens, turns, dollars |
| Summary | Accuracy | Time per correct answer | Cost per correct answer |

- Dollars are token counts multiplied by the model provider's published API price on the run date, recorded in the results, whatever billing was used. Cached or subscription calls count at full price. On 2026-09-27 the prices per million input and output tokens were $1 and $5 for `claude-haiku-4-5-20251001` and $2 and $10 for `claude-sonnet-5`.
- Every tool runs on the same machine with the same concurrency, timed from a cold start. Every LLM call any tool makes is logged.

## Equal conditions

- One model for all ingestion and answering: `claude-haiku-4-5-20251001`. One judge for every arm: `claude-sonnet-5`, checked against a second judge from another model family and against a person's review of 100 sampled verdicts.
- One agent model for C3, `claude-sonnet-5`, with the same prompt, turn limit and tools apart from the one under test.
- Calls that stand in for a direct API call (ingestion, answering, judging) run without extended thinking, as the API does by default. The Claude Code CLI turns thinking on unless told otherwise, so these calls switch it off. C3's agent runs are Claude Code sessions and keep its defaults.
- One embedding model (BGE-m3) for every tool we configure. `inquiry` runs as shipped (frozen), with its default `BAAI/bge-small-en-v1.5`; the memory tools get BGE-m3, the larger model.
- One context budget for every retrieval arm in C1 and C2: 2,000 tokens, counted by one tokenizer. The no-tool arm has no budget by definition; its cost is what it pays for that.
- One answer prompt for every arm, neutral about whether the context is excerpts, facts or notes.
- Each competitor runs at its documented defaults, configured the way its own benchmark code configures it: `mem0ai/memory-benchmarks` for mem0, Cognee's `eval_framework`, Graphify's `graphify update` and `query`. Our adapter code and each tool's exact version are published with the results.
- A failure to ingest, retrieve, answer or judge counts as a wrong answer.

## Methods per claim (clarified 2026-09-27, before any run)

- **C1 answering and judging.**
  - Every arm answers with one prompt that gives the question date, as LongMemEval does.
  - The judge uses LongMemEval's official per-type prompts (`xiaowu0162/LongMemEval` @ `9e0b455`, `get_anscheck_prompt`).
  - The no-tool arm puts every session, in date order, into the same prompt.
- **C1 `mem0`**, as in `mem0ai/memory-benchmarks` @ `4b61c5d` for LongMemEval:
  - sessions in date order, one `add` per user and assistant pair, `top_k` 200;
  - the open-source SDK rejects the benchmark's `timestamp` argument, so the session date is written into each message and returned with each memory.
- **C1 `cognee`**, as in its BEAM evaluation (`cognee.eval_framework.beam`):
  - every session is one JSON-list document of turn pairs with their date;
  - ingestion runs `local_ingest` with its defaults: session distillation and the global context index;
  - retrieval is `hybrid_completion` with 20 chunks and 20 entities, context only.
- **C2.**
  - A task counts as found when at least one changed function has a rendered line inside the arm's 2,000-token context. Graphify's location lines count when they point inside the function.
  - `cognee` is not applicable. Its released code search answers structured symbol operations, not issue text, and its text pipeline would run LLM extraction over every file of every repository snapshot.
- **C3.**
  - The agent gets at most 14 turns and must end with up to five `path:line` locations. A task counts as solved when one of them falls inside a changed function.
  - Every arm has Read, Grep and Glob. Each tool arm adds Bash limited to that tool's own command line, which is how both tools integrate with Claude Code: `graphify query`, `graphify path` and `graphify explain` for Graphify, `ai search` for `inquiry`.
  - Graphify's arm gets Graphify's published `CLAUDE.md` rules (`graphify/always_on/claude-md.md`) verbatim, with its graph at `graphify-out/graph.json`. `inquiry` ships its guidance as a Grep hook that suggests its search; hooks and slash commands do not run in a headless session, so that advice is given as a standing instruction (`INQUIRY_GUIDANCE` in `evals/claims.py`).
  - Each arm's share of runs that used its tool is reported.
- **Time.**
  - Wall-clock time is measured at one fixed concurrency for every tool.
  - LLM time is the sum of provider-reported API durations. Calls made through the Claude Code CLI carry a fixed per-call overhead (its system prompt and start-up), measured once on an empty prompt and subtracted from token counts and time.

## Pre-run corrections (2026-09-27, before any C1, C2 or C3 run)

An implementation review found these before any claim ran:

- **Leaked labels.** In LongMemEval-S every session that holds an answer has an ID beginning `answer_` (948 of 948), and no other session does (0 of 22,919). Every haystack shown to a tool or an answerer now uses opaque per-haystack IDs (`s000`, `s001`, ...). Earlier LongMemEval runs, including the `e32fb55` Level A test run, showed those IDs to every arm alike.
- **Build health.** A memory-tool build is retried up to three times for infrastructure failures (timeouts, rate limits), then refused on any failed LLM call, any reply from a different model, or unparseable JSON replies above 1% of its calls.
- **Infrastructure failures.** Failures caused by timeouts or rate limits are recorded as such. A comparison is invalid when either arm has more than 5% of them, and an invalid comparison supports no claim.
- **Time.**
  - C1: an item's time is its haystack's build and query wall-clock plus the answer call's API time. Query time is measured after the tool's client is open, as for `inquiry`. LLM API time is reported separately.
  - C2: an item's time is one cold command-line query per tool (`ai search`, `graphify query`).
  - C3: a run's wall-clock.
  - Builds run once. Each tool keeps its own persistent caches (`inquiry`'s content-hash embedding cache is a product feature), and the shim reports cache hits per build.
- **Cost.**
  - C1 attributes each haystack's build cost to its question.
  - C3 prices every model a Claude Code session used.
- **Graphify** builds with its documented `graphify update .` (AST, clustering and report, no LLM), and the C3 agent sees its whole `graphify-out/`.
- **C3 scoring.**
  - Only the first five `path:line` pairs count, after stripping any absolute prefix naming the working tree or the snapshot.
  - The prompt allows 13 tool calls, keeping the fourteenth turn for the answer.
  - A tool counts as used when its own command ran without error. Any other Bash command that ran is reported.
- **Judging.**
  - A verdict is correct when the judge's reply contains "yes", as in LongMemEval's scorer.
  - The check judge must label at least 95% of answers for a test run to stand.
  - Each C1 run writes a seeded sample of 100 verdicts for a person to review.
- **Prebuilt indexes.** Indexes and memory builds for test corpora may be built before a run starts. They read no labels and produce no scores.
- **Ledger.**
  - A test run commits its start entry before any work.
  - A test run refuses to start unless `inquiry`'s `code_hash` is `a45c43efd352e8db` and no configuration override is set.

## Statistics and sample sizes

- Every comparison is paired by question or task: `inquiry` against each other arm in the claim.
- The test is the exact two-sided sign test on discordant pairs (McNemar). Holm corrects across the comparisons within C2 and C3; C1 uses the sequential design below.
- A claim holds against an arm when its corrected p-value is below 0.05 and `inquiry` is ahead.
- Time and cost are reported as paired ratios with 95% bootstrap intervals.
- With about 30% of paired outcomes disagreeing:
  - C1's 100 questions detect a gap of about 18 points after Holm across three comparisons;
  - C2's 104 tasks and C3's 100 tasks detect about 17 points after Holm across two.
- A smaller true gap reads as no significant difference.

## C1 sequential design (amended 2026-09-28, before any C1 test run)

C1's memory tools cost about $2.75 (mem0) and $7.31 (Cognee) per question at list prices, against $0.0024 for `inquiry` (dev smoke run), almost all of it ingestion. To spend no more than the evidence needs, C1 runs in two looks with early stopping:

- **Look 1** uses the first 50 questions: `c1_sample(test, 50)`, a subset of the registered 100.
- **Look 2** adds the other 50, for comparisons not yet decided.
- **Per comparison:**
  - α is 0.05/3 (Bonferroni across C1's three comparisons, replacing Holm for C1).
  - It is spent with the Lan-DeMets O'Brien-Fleming function at information fractions 0.5 and 1.0.
  - The exact two-sided McNemar p must be below 0.000191 at look 1, or below 0.01661 at look 2. The boundaries were computed for the bivariate normal of the two looks.
- **At look 1:**
  - A comparison that crosses its boundary is decided: in favour of whichever arm won more discordant pairs.
  - That competitor is not ingested for look 2.
  - There is no stopping for futility.
- The no-tool arm is always run for all 100 questions.
- Builds proceed cheapest first: `inquiry`, then `mem0`, then `cognee`.

## Integrity

- This RFC is committed before any run. Each claim runs once. Every result is published, including failures.
- A run records its start before any computation and its results file's sha256 at the end, and the next run cannot start until both are committed.
- `inquiry` is frozen at commit `e32fb55` plus one fix, `111d4ca`: `ai search` closed no storage, so the process never exited after printing results. The fix changes no retrieval output (C1 and C2 query the search service directly, not the command line). Frozen `code_hash` `a45c43efd352e8db`; the index key is unchanged.

**Already known, disclosed:**
- `inquiry`'s settings were chosen on the dev splits of LongMemEval, LOCOMO, SciFact and SWE-bench.
- Retrieval results on the test splits of LongMemEval, LOCOMO, SciFact and ERPNext were seen at `e32fb55`: `inquiry` trailed BGE-m3 dense retrieval on LongMemEval.
- Answers to 200 LOCOMO test questions were seen.
- C1 uses LongMemEval test questions, whose retrieval results were seen but which were never used for tuning.
- C3's tasks are new to everyone.

## Consequences

- The expensive part is C1 ingestion. `mem0` and `cognee` call the LLM for every stored turn, and 100 LongMemEval histories are about 5,000 sessions per tool.
- C2 needs no LLM.
- C3 is 300 agent runs.
- Graphify's LOCOMO and LongMemEval numbers are cited only as its own reported results.
- `claude-haiku-4-5-20251001` retires no sooner than 2026-10-15. If it retires before a claim has run, that claim moves to one replacement model for every arm, recorded here before the run.
