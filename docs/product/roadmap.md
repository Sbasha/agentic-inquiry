# Roadmap

> Direction for the next 2-4 quarters. **Not** commitments.

**Last updated:** 2026-09-30
**Reviewed:** quarterly. Next review: 2026-12-30.

## Now (current quarter)

- **Honest local engine.** Docs and capability reports describe LanceDB, SQLite, and the lifecycle contract. The default search blend is the linear combination the config actually uses.
- **Cache that maintains itself.** A second `ai index` skips unchanged files. Relationship rows converge. Branch expiry goes through the storage manager. Full-text queries are sanitized on every path. Ledger rows can be rebuilt.
- **Memory stays off Git.** Session captures live under `INQUIRY_HOME` with a 45-day default life and a row cap. A session never writes Markdown into a project repository or into the brain.

## Next (following 1-2 quarters)

- **Workspace library.** One shared index of `~/agentic-workspace/brain/wiki/` and `thought-leadership/`, attached by default for every project, opt-out per project. `brain/raw/` is not indexed. [RFC: RFC-0003]
- **Hook delivery.** The lifecycle hook returns a small keyword slice from the last good library index. A deeper look is the existing search tool over that same index. Session end refreshes the library when the workspace commit moved, expires old ledger rows, and compacts. No background daemon.
- **Licence filter.** Client projects default to `render` and never receive a licensed hit. Personal projects can be `builder`.

## Later

- Team sharing of a library, behind the external provider contract.
- Collapsing the storage facade and the older database package into one query path.

## Not in scope

- Writing session memory into Git, into client `docs/knowledge/`, or into the brain from a hook.
- Copying the brain into each project index.
- Indexing `brain/raw/`.
- A hosted database, a web UI, or a background process the person did not start.
- A code-editing agent. This product retrieves and remembers. The coding assistant edits.

## How this file is maintained

- **Owners:** sammybasha
- **Updates:** items move between sections via small PRs. Substantive additions go through an RFC.
- **Review cadence:** quarterly.
