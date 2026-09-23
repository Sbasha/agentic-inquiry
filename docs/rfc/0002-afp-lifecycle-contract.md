# RFC-0002: AFP lifecycle contract

- **Status:** Accepted
- **Author:** sammybasha
- **Approver:** sammybasha
- **Date opened:** 2026-09-22
- **Date closed:** 2026-09-22
- **Decision weight:** heavy
- **Related:** ADR-0004, ADR-0005, `docs/specs/afp-lifecycle-contract/spec.md`, `contracts/jsonschema/`, AFP `packs/agentic-inquiry`

## Reviewer brief

- **Decision:** make the lifecycle contract the AFP pack already targets a supported public surface of the `ai` command, implemented in the runtime, and amend the charter's delivery surfaces accordingly.
- **Recommended outcome:** accept.
- **Change if accepted:** a new `agentic_inquiry/integration/` package and five CLI verbs; `agentic_inquiry/__init__.py` loses its import-time side effects; `contracts/jsonschema/` becomes a top-level directory; `docs/CHARTER.md` lists the contract as a delivery surface.
- **Affected surface:** the `ai` CLI, the package import graph, the charter, the AFP pack (consumer), the standalone Claude plugin (unchanged now, migrated later).
- **Stakes:** costly to reverse once adapters depend on the JSON shapes; the shapes are versioned to make evolution possible.
- **Review focus:** the hot-path budget (stdlib and SQLite only) and the queued-then-reconciled capture model.
- **Not in scope:** knowledge pages, backup and restore, semantic ranking inside hooks, Gemini or Codex plugin mirrors, in-hook commitment of captures.

## The ask

- **Recommendation (BLUF):** approve the lifecycle contract as a supported surface at `schema_version` 1, implemented as `agentic_inquiry/integration/` with stdlib and SQLite on its hot paths, and amend the charter's "two delivery surfaces" to three.
- **Why now (SCQA):** the AFP pack `packs/agentic-inquiry` 0.2.1 drives Agentic Inquiry through `ai capabilities --json` and `ai integration hook`, a contract the 0.1.0 preview implemented. On 2026-09-22 the Agent Vault base replaced that codebase on `main`, so the pack now fails on every event, and its own hook refuses Claude Code, the one client the base supports. Which runtime carries the name, and where the host-integration logic lives, has to be decided before either repository moves.
- **Decisions requested:**

| ID | Question | Recommendation | Why | Decide by | Reviewer action |
| --- | --- | --- | --- | --- | --- |
| D1 | Which codebase is Agentic Inquiry? | The Agent Vault base; the 0.1.0 preview stays at tag `v0.1.0` (ADR-0004) | A working search, index and memory stack with 4,700 tests outranks a contract that costs a few hundred lines to port | this review | confirm |
| D2 | Where does host-integration logic live? | In the runtime, behind one client-neutral CLI contract (ADR-0005); adapters are thin translators | One implementation for three clients; tested once; no plugin imports the package from an ambient interpreter | this review | confirm the budget and the queued model |
| D3 | Does the charter change? | Yes: delivery surfaces become plugins (primary), the lifecycle contract for host adapters, and the MCP server | The contract is a supported interface with external consumers, which the charter must name | this review | rule on wording |
| D4 | New top-level `contracts/` directory? | Yes, `contracts/jsonschema/` for the three shapes | The shapes are machine-checked in tests and copied by the consumer; a canonical location beats prose | this review | confirm |
| D5 | What happens to the standalone Claude plugin? | Unchanged now except loopback binding; migrates onto the contract in its own spec; double enablement is refused | Two owners writing two stores is the failure to prevent today; the rewrite is separate work | 2026-10-31 | confirm the interim rule |

## Problem & goals

The consumer's contract is small and exact: on each native event, one process start, bounded JSON in, one JSON object out with a status, a context block with byte accounting, receipts with durable identifiers, pending work and errors; before the first call, a capability report. Its budgets are 2 s for discovery and about 9 s per event. Measured on this workstation, `import agentic_inquiry` alone costs 1.5 s warm, imports lancedb, pyarrow and pandas, and creates a `logs` directory in the current directory; the embedding model costs about 6.5 s warm. The base's own Claude plugin ignores those constraints by design: it imports the package in the ambient interpreter, starts an HTTP server on all interfaces on demand, injects a behavioural contract at session start and a mandatory prompt on every Stop. Durable memory sits in a gitignored, CWD-relative directory.

**Goals.**

- The AFP pack works against `main` without changing its contract, for Claude Code, Codex and Pi.
- Every hook answers inside its budget, with the model never loaded and no process left behind.
- Every durable claim carries a receipt; a repeated delivery never creates a second record; a project that never opted in costs one file stat.
- Durable records survive `git clean` and worktrees.

**Non-goals.**

- Reviving the preview's knowledge pages, collections or backup and restore. Each needs its own spec.
- Semantic ranking inside hooks; hook-path recall is recency and lexical.
- Committing captures inside the hook; commitment is a separate step.
- Converting the Gemini or claimed Codex mirrors of the standalone plugin.
- Windows path semantics; the runtime targets the POSIX platforms `uv tool install` serves today.

## Proposal

**D1, lineage.** `main` continues from the imported base; version 0.3.0 follows; `v0.1.0` is history. Detail in ADR-0004.

**D2, contract in the runtime.** `agentic_inquiry/integration/` owns `capabilities()`, `hook()`, `enable()`, `disable()`, `status()` and `reconcile()`. `cli/__main__.py` dispatches `--version`, `capabilities`, `integration`, `mcp` and `status` before any heavy import, and `agentic_inquiry/__init__.py` becomes side-effect free. The ledger under `INQUIRY_HOME/projects/<project_id>/records.sqlite3` is the durable authority; `<project_root>/.agentic-inquiry/project.toml` carries the committed identity and `integration.json` the machine-local enablement marker the adapter stats first. Mutating events return `queued` receipts; `ai integration reconcile` and the MCP server's maintenance tick commit them. SessionStart and UserPromptSubmit may read the bound LanceDB environment inside a deadline. The shapes, bounds, statuses, error codes and exit codes are in the spec and the three JSON Schemas. Detail in ADR-0005.

**D3, charter.** `docs/CHARTER.md` "Two delivery surfaces" becomes "Three delivery surfaces": Claude Code plugins (primary), the lifecycle contract consumed by host adapters such as the AFP pack, and the MCP server (secondary).

**D4, contracts directory.** `contracts/jsonschema/afp-lifecycle-hook-request.schema.json`, `afp-lifecycle-hook-response.schema.json`, `afp-lifecycle-capabilities.schema.json`, each carrying `x-spec`. Contract tests validate every response against them.

**D5, standalone plugin.** `server/run.py` and `server/lifecycle.py` bind `127.0.0.1` now. `ai integration enable --owner afp` refuses while `.claude/settings.json` enables `ai@agentic-inquiry`; a hook from the other owner receives `owner_conflict`. The plugin's migration onto `ai integration hook --client claude-code --owner standalone` is a backlog item with its own spec.

## Options considered

Axis: where the logic that turns a native lifecycle event into a runtime action executes. The four options exhaust the axis: inside the client's plugin, inside a one-shot runtime process, inside a long-lived runtime process, or nowhere.

| Option | Prior art | Trade-offs against the goals |
| --- | --- | --- |
| A. Inside each harness plugin (status quo, `extensions/claude/ai/`) | Claude Code hooks: a command per event, JSON on stdin and stdout | Claude-only; imports the package from whatever `python3` the harness has; identity, budgets and receipts reimplemented per client; the Stop prompt makes `/exit` a model turn |
| B. One-shot runtime process behind a client-neutral CLI contract (recommended) | Git hooks and Claude Code command hooks for the one-shot shape; LSP `initialize` and MCP `initialize` for capability discovery before use | One implementation, tested once, three clients through the AFP bridge; requires a side-effect-free package import and a queued capture model; recall is recency and lexical |
| C. Long-lived local daemon or HTTP server that plugins call | Language servers and MCP servers proper; the base's own FastAPI server and the Agent Vault socket daemon | Removes per-event start cost but adds a process the user did not start, lifecycle management the pack cannot own, a port, and per-user PID contention across repositories; the preview's design excluded it |
| D. Do nothing: retire the pack, keep the plugin | none | The AFP catalogue loses its knowledge provider, the benchmark's claim 14 stays blocked, and the Codex and Pi routes have no path; cost of delay grows with every AFP release |

## Risks & what would make this wrong

**Pre-mortem.**

- A cold cache makes SessionStart miss its budget. Mitigation: the read stage is deadline-guarded and returns `partial` with `budget_exhausted` rather than a late answer; thresholds are warm-run values.
- Pending rows accumulate because nobody runs `reconcile` or `ai mcp`. Mitigation: every later hook lists them, `ai status` counts them, and the `ai` skill can commit them on request.
- Import hygiene regresses when someone adds a convenience import to `__init__.py`. Mitigation: a subprocess test asserts the heavy-module set is empty and no directory is created.
- Both owners get enabled in one project. Mitigation: `enable` refuses when the other owner is configured or the standalone plugin is enabled; the hook refuses the wrong owner.

**Key assumptions (falsifiable).**

- A stdlib-only interpreter start plus one SQLite write stays under 0.5 s warm on a supported workstation. Measured baseline: 0.28 s for the interpreter.
- The AFP bridge sets `AFP_PLUGIN_CLIENT` for all three clients and normalises Codex and Pi payloads to Claude Code's field names. Verified in `runtime/plugin_hooks.py`; the Codex tool-identity field still needs a live check.
- LanceDB opens and answers a recency query on a small memory table in under 2.5 s warm. Measured `import lancedb`: 0.95 s.

**Drawbacks.** Hook-time capture is `queued`, not committed, so a session can end with visibly pending work. Hook-path recall never uses the model. The standalone plugin and the pack cannot coexist for one project and client.

## Evidence & prior art

**Spike.** The riskiest assumption is that the contract can be served without paying the package's import cost. Measured on 2026-09-22 (Python 3.13.15, warm cache, `PYTHONDONTWRITEBYTECODE=1`): `import agentic_inquiry` 1.53 s and 4.26 s cold, loading lancedb, pandas and pyarrow; stdlib-only interpreter 0.28 s; `ai --help` 1.50 s; `import lancedb` 0.95 s; `import fastmcp` 2.89 s. The import created `.agentic-inquiry/logs` in a temporary current directory. Conclusion: the contract verbs must avoid `import agentic_inquiry`'s current side effects, which is a precondition task (T1) rather than an optimisation.

**Repo precedent.** `git show 86403f5:src/agentic_inquiry/integration.py` implements the same contract on the preview, including the ledger key, the admitted-field rule and the budget accounting the pack validates today. `git show 86403f5:DESIGN.md` R6 and R7 require explicitly enabled integrations with durable acknowledgements and the same operations through CLI, MCP, Codex and Pi. `docs/CHARTER.md` names two delivery surfaces and requires an RFC for substantive edits. ADR-0001 and ADR-0002 keep storage behind the facade; the ledger is deliberately outside it.

**External prior art.**

- Claude Code hooks reference (https://code.claude.com/docs/en/hooks): command hooks receive JSON on stdin with `session_id`, `cwd`, `hook_event_name` and `transcript_path`; they return JSON on stdout with `continue`, `systemMessage` and `hookSpecificOutput` carrying `hookEventName` and `additionalContext`; exit 0 is success, exit 2 blocks, other codes are non-blocking errors; the default command timeout is 600 s, and `SessionEnd` hooks share a 1.5 s budget. The contract's response shape and the pack's SessionEnd rule follow this page.
- Language Server Protocol 3.17 (https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/): "The initialize request is sent as the first request from the client to the server"; the server answers with `ServerCapabilities`, and clients do not send requests for features the server did not advertise. `ai capabilities --json` plays the server's role and `clients.<client>.supported_events` the capability table.
- Model Context Protocol lifecycle, 2025-06-18 (https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle): initialization "MUST be the first interaction between client and server", both parties "Only use capabilities that were successfully negotiated", and the stdio transport shuts down by closing the child's input stream. `ai mcp` is that stdio child.

## Open questions

1. Should `SessionEnd` stay in `supported_events` while the AFP pack unwires it? Default: yes, for the standalone owner's future use; owner sammybasha; decide by 2026-09-30.
2. Should hook-path recall gain semantic ranking through a cached query embedder? Default: no until a measured warm cost under 0.5 s exists; owner sammybasha; decide when the standalone plugin migrates.
3. Do the path rules need Windows semantics? Default: POSIX only; owner sammybasha; decide when a Windows adopter appears.

## Follow-on artifacts

- ADR-0004: product lineage.
- ADR-0005: the contract as a public surface.
- Spec: `docs/specs/afp-lifecycle-contract/`.
- Charter change: `docs/CHARTER.md`, "Scope", delivery surfaces.
- New top-level directory: `contracts/jsonschema/`.
- Consumer: AFP `packs/agentic-inquiry` 0.3.0 and `docs/decisions/agentic-inquiry-pack-placement.md` in the AFP repository.

## Errata

- **2026-09-22 - purge verb.** The spec-stage security review added `ai integration purge` as a sixth verb so retained ledger payloads have an operator-controlled deletion path; "five CLI verbs" in the Reviewer brief reads as six, and the Proposal's D2 function list gains `purge()`.
- **2026-09-22 - recall source.** The spec-stage adversarial review found that `LanceDBMemoryAdapter.query` applies `limit` before `order_by`, so a store recency query cannot be exact; SessionStart recall reads the ledger's capture rows (ordered by capture time) and never opens the store. The falsifiable assumption "LanceDB opens and answers a recency query on a small memory table in under 2.5 s warm" now applies to the UserPromptSubmit evidence stage only.
- **2026-09-22 - MCP transport bind.** The spec's AC30 widens D5 beyond `server/run.py` and `server/lifecycle.py`: at 0.3.0 the MCP http and sse transports (`MCPServer.run`, `MCPServer.run_async`, `ai serve --host`) refuse every non-loopback bind. An API key is not an escape for them because the REST middleware exempts `/mcp`, so the MCP surface has no authentication of its own. Operators who exposed the transport from the same host move to the reverse-proxy recipe; containerised or orchestrated MCP deployment is withdrawn until an authenticated non-loopback MCP lands (backlog). This is a breaking change to a charter-named surface and the release note names it.
- **2026-09-22 - synchronous ledger.** The spec's Boundaries make `agentic_inquiry/integration/state.py` synchronous `sqlite3` (the hook is a short-lived process where an event loop buys nothing) and reach it from the async `reconcile` path only through `asyncio.to_thread`, one connection per call. Charter Principle 4 (async-only at the I/O boundary) records this as its one exception; the spec's T12 amends the charter and `AGENTS.md`.
