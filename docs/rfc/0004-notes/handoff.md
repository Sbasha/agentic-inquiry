# RFC-0004 implementation handoff

Companion to [`../0004-unified-project-runtime.md`](../0004-unified-project-runtime.md). The review loop on the RFC is closed by the approver on 3 October 2026; this file is the entry point for the implementation sessions. It holds only open tasks, ordered by execution. Remove a task entirely when it lands. Delete the file when the list is empty.

## Standing context for every session

Read in this order before editing: the RFC; `spikes.md` and `living-document-edits.md` in this folder; `~/.claude/plans/why-are-you-recommending-splendid-sprout.md` sections 6e, 7 and 8 (the session plan the RFC refines; where the two disagree the RFC wins); the memory files `unified-context-layer-decision-2026-10-03`, `rfc-0004-session-0-stop-2026-10-03` and `agentic-inquiry-retrieval-state-2026-09-30`; `AGENTS.md`; `docs/CONVENTIONS.md`; `.claude/skills/work-loop/SKILL.md` and `.claude/skills/new-spec/SKILL.md`; `docs/specs/afp-lifecycle-contract/spec.md`, whose criteria the RFC's AC table amends.

Decisions D1 to D8 are closed. The RFC is the authority for the design; the three follow-on specs carry the detail and are validation gates, so a spec that diverges from the RFC is corrected in the same change, never worked around.

Rules: no em dashes; Terse register; no history narration in Markdown; verify every path and API before citing or importing it; read `~/OPINIONS.md` before any framing call; the brain repository is read through its own MCP server and `~/work/brain` is never searched recursively; never search `~/projects/assets/afp` or `~/projects/assets/dotfiles` recursively; commits carry no co-author line; every commit is shown to the approver before it is made; destructive commands (`rm -rf`, dropping tables, `git push --force`) need the approver's confirmation.

Gates for every code session, from `AGENTS.md`:

```bash
uv run --env-file .env pytest -x
uv run --env-file .env mypy agentic_inquiry/
uv run --env-file .env ruff check . --fix
uv run --env-file .env ruff format .
```

Baseline measured 3 October 2026: `uv run pytest tests/unit tests/integration/test_afp_lifecycle_contract.py -q` gave 419 passed, 1 failed (`tests/unit/mcp/utils/test_index_state.py::test_handles_db_manager_exception`, READY reported where SPARSE is expected). The full suite is 4,830 tests and has not been run on this branch; session 1 runs it once and records the number here.

Known-answer validation gates every session from session 3 on; its shape is under Evidence in the RFC and its location is the Bet 1 initiative folder's stage-0 handoff file, section 4.

## Working tree at handoff

Branch `rfc-0003-knowledge-architecture`, nothing committed since `69277f9`. Untracked: `docs/rfc/0004-unified-project-runtime.md` and this folder. Modified and uncommitted from RFC-0003's acceptance, to be staged with the RFC: `README.md`, `docs/architecture/overview.md`, `docs/architecture/search.md`, `docs/product/README.md`, `docs/product/changelog.md`, `docs/product/roadmap.md`, `docs/rfc/0003-knowledge-architecture.md`, `docs/rfc/README.md`, `docs/specs/first-run-reliability/spec.md`, `docs/specs/skill-global-invocation/spec.md`.

Two items stay with the approver and block nothing before session 4: enabling the probe server once in Cursor's MCP settings so the `${workspaceFolder}` run can be recorded in `spikes.md`; the `--root` versus `roots/list` call (open question 2, default `--root` stands until decided).

## Tasks

### Session 0: accept the RFC and open the specs

1. Set the RFC status to `Accepted` with the close date, and update the status cells of RFC-0003 and RFC-0004 in `docs/rfc/README.md`.
2. Record the Errata entries the RFC's Follow-on section names: on RFC-0002 (the criteria table and the D3 and D5 plugin timeline) and on RFC-0003 (one per-item fate list: D1's project-memory tier, D3, D5 and the first arrow of D4 superseded for this runtime; D6 reversed in its quoted sentence only; closed decision 3 reversed; closed decisions 1 and 2 and the Graph mapping section unchanged). Use the same list everywhere the RFC names RFC-0003's fate.
3. Write the four ADRs the Follow-on section lists through `new-adr`; the third supersedes ADR-0005 and the fourth is the dependency ADR `AGENTS.md` requires before `pyproject.toml` changes.
4. Open `docs/specs/subtraction/` through `new-spec`. Inputs: the RFC's Remove list, Keep list, AC table, the erratum text for every amended and retired criterion of the three shipped specs, the pack 0.4.0 contract, `living-document-edits.md`, and these review items the RFC leaves to it: the complete pack reference set (`.apm/commands/help.md`, `.apm/skills/ai/SKILL.md`, the pack `README.md`, `pack.toml` capture note and receipt verification, `.claude-plugin/plugin.json` `./skills/memory` entry, `tests/test_inquiry_plugin.py`); removing `extensions/gemini/ai/hooks/` and `extensions/claude/ai/tests/` whole; the Affected surface additions (`storage/facade.py`, `parsers/implementations/document.py`, `mcp/server.py`, the `mcp/tools/` files the RFC edits, `mcp/services/context_builder.py`, `docs/mcp/*`, `docs/architecture/embeddings.md`, `docs/mcp/security.md`, `docs/mcp/configuration.md`); the AC25 rule that unknown policy keys (`capture`, `refresh`, `ignore_patterns`) are ignored, not unparseable; `.odp` and `.ods` evidence (cite the pandoc cause or keep them) and `.ppt` beside `.doc` on the LibreOffice sentence; one primary interface named the same way in the charter's Scope and Principle 2.
5. Open `docs/specs/index-lifecycle/` through `new-spec`. Inputs: resolution steps 1 to 5 and the enable transition, nested-root exclusion, dead-file pruning, unchanged-file skip keyed on embedder identity, `UNKNOWN` health, FTS sanitising, the D7 install-size and start-time criteria with derivation, `purge --identity`, and these review items: the Vocabulary replacement sentences for storage namespace and ledger home; `project.toml` called the identity file; whether `--root` and `--project-root` are one flag; the Problem paragraph's chunk count corrected to 258,773 and 30 September; the Migration sentence on brain artifacts replaced by the invariant (the brain holds no Agentic Inquiry index or configuration and step 4 refuses to build one); Option H's 111,511 lines sourced as Python lines under `agentic_inquiry/` on 3 October.
6. Open `docs/specs/context-face/` through `new-spec`. Inputs: the page schema, store, acceptance log, tools, CLI, `/ctx`, the validation set, the deferrals the RFC names (flow-scalar quoting, `supersedes` edge cases, `accept` on an accepted page, same-day slug collision across branches), and these review items: the filter invariant "every MCP and CLI read path, status and validity", covering `mcp/tools/info.py`, `search_docs` and `search/graph_search.py`; `context_propose` gains `valid_to` and author-set `licensed`, or the spec states they come only from a hand edit before acceptance; `init` refuses an initialised root and the log records the `README.md` hash; the lock is `flock` on a never-unlinked file under the AC10 home checks; the slug is capped at 58 characters before any suffix; `/ctx` is pack-only and the AGENTS.md row says so, or the standalone plugin gains `ctx` with `disable-model-invocation`; open question 1's decide-by reads "from the cross-harness run, no later than 2026-11-07, else the default stands".
7. Stage the RFC, this folder, the Errata, the ADRs, the three spec folders and the ten modified documents listed above; show the commit to the approver; commit on approval.

### Session 1: subtraction

8. Work `docs/specs/subtraction/` through `work-loop`: remove the memory tiers as a write path, the REST server and clients, the standalone plugin hooks and daemon, the Gemini daemon files, the lifecycle capture, refresh and reconcile paths, and their tests; keep every retired schema field, code and receipt kind accepted and never emitted; `runtime.capture` becomes `false`. Run the full suite once before and once after and record both counts here.

### Session 2: binding, pruning, dependency diet

9. Work `docs/specs/index-lifecycle/`: `integration/resolve.py` and every entry point on it (`ai index`, `ai search`, `ai status`, `ai integration status`, `ai mcp`, the skills); `enable` re-rooting and the below-toplevel refusal; `ai mcp` changing directory to the root; nested-root exclusion; dead-file pruning; unchanged-file skip; `UNKNOWN` health and the `index_state.py` fix; `purge --identity`; `fastembed` default with the `torch` extra, `mypy` and `ruff` to dev, `tantivy` removed, `requires-python >= 3.11`, the `xlsx` extra kept and the pandoc formats dropped. Gate: startup under 1.5 s warm; `ai index` run twice on the Bet 1 initiative folder leaves no missing files.

### Sessions 3 and 4: the context face

10. Work `docs/specs/context-face/` runtime side: `agentic_inquiry/context/` (`pages.py`, `store.py`, `graph.py`), `cli/context.py`, `mcp/tools/context_pages.py`, the live status and validity filter on every read path, `initialize.instructions`, the acceptance log, `check`, `eval`. Gate: unit tests on a fixture store, `check` catches each violation class, the project-tier eval passes in-process.

### Session 5: pack 0.4.0

11. In `~/projects/assets/afp/packs/agentic-inquiry`: hooks reduced to SessionStart, `inquiry-lifecycle.py` resolving the root by step 1's markers, `.apm/commands/ctx.md`, `pi-command-aliases.json`, the skill text replaced by the context-page contract and consultation order, the Cursor MCP projection at repo scope with `--root ${workspaceFolder}`, the removals, the version floor `ai >=0.4.0`, the README's trust and enable steps per harness, the pack test asserting the one-event set and the root resolution. Gate: `make test-packs` and the catalogue lint from the AFP repository root. The pack ships no later than the runtime.

### Sessions 6 and 7: brain retrieval (own repository, parallel)

12. `~/work/brain`: plan section 7a as written; independent of sessions 1 to 5; gate is graph-mode recall 8 of 9 with zero licensed leaks. Read the brain through its MCP server and its own `AGENTS.md`; never search it recursively.

### Session 8: adoption and cross-harness evaluation

13. Brain commit first: `rules/AGENTS.md` section 4.4 admits `docs/context/` and `.agentic-inquiry/` and `tools/check-folder.py` checks both. Then the Bet 1 initiative folder gets its context folder and three seed pages accepted by the approver; `ai integration purge` on every old ledger (`--identity` for the two orphaned ones); the four duplicated Claude Code memory folders deduplicated; one live, recorded session per harness (Claude Code, Codex, Cursor, Pi through `pi-mcp-adapter`) running the known-answer set; the negatives from the RFC's Validation paragraph. Record the qualification table in the pack README.

## Gates and commands

Per session: the four commands above plus the session's own gate. Before any commit: `grep -c "—"` over every Markdown file touched prints 0, and every path cited in a changed document exists or is marked as new.
