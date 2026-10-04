# RFC-0004 living-document edits

Companion to [`../0004-unified-project-runtime.md`](../0004-unified-project-runtime.md). The RFC's Migration section states what each living document says after this change; this file lists the phrase-level edits the `subtraction` spec lands. Quoted text is the current wording.

## `docs/product/roadmap.md`

- Now: drop "A session never writes Markdown into a project repository or into the brain", "Session captures live under `INQUIRY_HOME` with a 45-day default life" and "Ledger rows can be rebuilt"; add "A session writes only proposed pages into the project and nothing into the brain; a person accepts".
- Next: drop "Workspace library", "Hook delivery" and "Licence filter" (the filter moves to the brain's own roadmap).
- Not in scope: keep "Writing session memory into Git, into client `docs/knowledge/`, or into the brain from a hook"; add "Indexing the brain"; reword "retrieves and remembers" to "retrieves and records proposals".

## `docs/CHARTER.md`

- Mission: "exposed through Claude Code plugin skills" becomes "exposed through MCP tools and the skills, commands and hooks an AFP pack projects into each harness".
- Principle 2: "The plugins are the primary interface" becomes "The AFP pack is the primary interface; the Claude plugin is one projection of it"; its example drops "a plugin command" for "an MCP tool and a CLI verb".
- Principle 4: gains the `context/` exception, synchronous file I/O and the lock file reached from async callers through `asyncio.to_thread`, beside the ledger's `sqlite3` exception.
- Scope: "Persistent multi-tier memory" is replaced by "Governed project context"; "Two delivery surfaces" names MCP as primary.

## `AGENTS.md`

- Drop "(with a secondary MCP surface)", "(secondary to plugins)", "reconcile", the `/ai:memory` row and the Memory row of the core architecture table.
- Add `/ctx` to the skills table and `agentic_inquiry/context/` to the core architecture table.
- Beside the async bullet's ledger exception, add: `agentic_inquiry/context/` uses synchronous file I/O and a lock file; a caller with an event loop reaches it through `asyncio.to_thread`.

## Other pages

- `docs/architecture/integration.md`, `docs/architecture/overview.md` and `docs/guides/reference/lifecycle-cli.md`: drop reconcile, receipts and the memory sweep; `lifecycle-cli.md` also loses the `capture_exhausted` advisory, `reconcile --retry`, `--force` and the third-reset refusal.
- `docs/backlog.md`: drop "Rebuild memory rows from the ledger", "Framing in the standalone skills", "Standalone Claude plugin as a translator" and "Authenticated non-loopback MCP".
- `README.md` and `CONTRIBUTING.md`: drop the REST server, `ai shell` and memory sections; reword `ai serve` as an alias of `ai mcp`.
