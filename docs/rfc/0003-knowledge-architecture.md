# RFC-0003: Knowledge architecture: governed libraries, project stores and memory

- **Status:** Draft
- **Author:** sammybasha
- **Approver:** sammybasha
- **Date opened:** 2026-09-27
- **Date closed:**
- **Decision weight:** heavy
- **Related:** RFC-0001, RFC-0002, ADR-0004, ADR-0005, `docs/storage-backends.md`, `docs/architecture/search.md`, `docs/architecture/knowledge-graph.md`, AFP `packs/agentic-inquiry`, the brain schema at `~/agentic-workspace/brain/wiki/AGENTS.md`, the toolkit read protocol at `~/projects/assets/agentic-enterprise-toolkit/SOURCES.md`

## Reviewer brief

- **Decision:** how Agentic Inquiry serves one person, and later a team, who work across many confidential projects while reading one centrally governed knowledge base, without copying that knowledge into any project and without any project leaking into another.
- **Recommended outcome:** accept the tier model and the library abstraction; defer the team provider behind the existing external provider contract.
- **Change if accepted:** a read-only, commit-pinned **library** environment kind beside project-local environments; federated search that fans out to the bound project store plus explicitly attached libraries and tags every hit with its origin, pin and licence flag; a promotion path that moves knowledge upward only through a curator, never through a session write.
- **Affected surface:** `agentic_inquiry/storage` (facade, filter AST, `query_across_projects`), the MCP tools `search_docs`, `search_knowledge`, `build_context`, `save_memory` and `recall_memories`, `ai setup` and the environment registry, the AFP pack's SessionStart and UserPromptSubmit read stage, `docs/CHARTER.md`.
- **Stakes:** costly to reverse once consumers depend on result provenance fields; the tier boundaries are a one-way door for confidentiality.
- **Review focus:** the confidentiality rule (a project store never federates with another project store) and the authority rule (canonical knowledge is Markdown in Git, every index is a derived cache).
- **Not in scope:** hosting a shared database, a web UI, generative summarisation inside hooks, replacing the brain curator, changing the brain's schema.

## The ask

- **Recommendation (BLUF):** approve five tiers of knowledge with one authority and one write path each, a `library` environment kind that lets a project session read pinned global knowledge with provenance and licence flags on every result, and a memory promotion path that ends in curated Markdown rather than in a vector row.
- **Why now (SCQA):** Agent Vault, the workspace `llm-wiki` skill, core `project-knowledge` and Agentic Inquiry memory all answer "remember this" today, and only invocation flags keep them apart. The Agent Vault clone is being archived and Agentic Inquiry is the one runtime going forward. Meanwhile the brain in `~/agentic-workspace/brain/` is read by the toolkit through a path and a pin table, never through this runtime, so the one governed knowledge base is the one thing search cannot see. Each new engagement adds a confidential project store that must stay sealed. The question is what a session may read, where each kind of knowledge is maintained, and how knowledge moves between tiers.
- **Decisions requested:**

| ID | Question | Recommendation | Why | Decide by | Reviewer action |
| --- | --- | --- | --- | --- | --- |
| D1 | What are the tiers? | Five: global governed brain; team shared knowledge (future); project knowledge base; project memory; session working memory | Each has a different owner, lifetime, confidentiality and write path | this review | confirm the five and their owners |
| D2 | Where is authority? | Canonical knowledge is Markdown in Git (OKF pages, claims, `docs/knowledge/`, the engagement record); every LanceDB or SQLite index is a derived cache rebuildable from a commit | An index that is authority cannot be reviewed, diffed, licensed or pinned | this review | confirm |
| D3 | How does a project read the brain? | A `library` environment: read-only, bound to a Git path and a commit, indexed once per pin, attached to a project by explicit declaration, queried in federation with the project store | Copying the brain into projects breaks the pin and licence rules the toolkit already enforces; reading it by path without an index leaves it unsearchable | this review | confirm the read-only and pinned properties |
| D4 | What may cross project boundaries? | Libraries flow down into any project; nothing flows across projects; knowledge flows up only through a curator inbox | Client confidentiality is absolute; the brain's provenance rules require a human curator | this review | confirm the three arrows |
| D5 | How are licence and citation enforced? | As query-time filters in the facade: a result carries `licensed`, `claim_id`, `verified` and `origin`; a caller declares an audience (`builder` or `render`) and `render` never receives a licensed hit | Enforcing in prompts fails silently; enforcing in the store loses the builder view | this review | confirm the audience flag |
| D6 | How does memory become knowledge? | Working memory is the session; episodic memory is the hook-captured ledger; semantic memory is explicit `save_memory`; promotion to the project knowledge base is a distillation the person approves; promotion to the brain is a curator request | Deliberate promotion is the only step that survives context rot and audit | this review | confirm the promotion ladder |
| D7 | What does a team need? | Nothing new in the runtime now; the external provider contract in `docs/storage-backends.md` gains a library role with tenancy, append-only audit and pin verification; hosting is a later RFC | The contract exists; a hosted provider without a team is speculation | 2026-11-30 | confirm the deferral |

## Problem & goals

One person today runs many engagements, each in its own repository with its own confidential documents, code and decisions, and maintains one governed brain of thought leadership whose pages carry claim ids, verification dates and licence flags. Agentic Inquiry can index and search a project. It cannot read the brain except by treating a copy of it as project files, which loses the pin and lets licensed material land in a client repository. Memory today is per project and per user, which is right for confidentiality and wrong for the brain, which is neither. The AFP pack's hooks read only the project-local store within a two-second budget, so any federation must stay off the hook path.

**Goals.**

- One query, many sources: a session asks once and receives project hits and brain hits together, each labelled with where it came from, which commit it was read at, and whether it may render.
- Confidentiality by construction: a project store is never a source for another project.
- Authority in Git: every durable fact has a reviewed Markdown home; indexes are rebuilt, never edited.
- Promotion is deliberate: knowledge moves up one tier at a time, through a person or a curator, with provenance kept.
- Team-ready contract: the same tiers hold when a team shares the brain and shares an engagement, with tenancy and audit added by a provider and not by the runtime.
- Measurable: the golden bench (RFC-0001) gains brain queries with citation correctness, zero licence leakage to `render`, zero cross-project hits and pin freshness.

**Non-goals.**

- Replacing the brain curator or the OKF schema. The runtime indexes what the curator publishes.
- Generative summaries inside hooks or query paths; ranking uses lexical, vector and graph signals only.
- A hosted service, authentication or a web UI in this RFC.
- Migrating the workspace `llm-wiki` skill; it is retired in the AFP catalogue and its OKF conventions already live in the brain schema.

## Proposal

**Tiers, owners and write paths (D1, D2).**

| Tier | Home | Authority | Writer | Lifetime | Confidentiality |
| --- | --- | --- | --- | --- | --- |
| Global governed brain | `~/agentic-workspace/brain/wiki/` in Git | Markdown pages, claims with `licensed`, `verified`, `status_label` | the brain curator only | years | internal; licensed pages never render |
| Team shared knowledge (future) | a Git repository per team, same OKF schema | Markdown | named curators, review-bound | years | team |
| Project knowledge base | the engagement repository: `docs/knowledge/`, the engagement record, indexed client documents and code | Markdown and the record | core `project-knowledge` and the record's propose and accept path | the engagement | client; never leaves the repository |
| Project memory | `INQUIRY_HOME/projects/<id>/` ledger and LanceDB memory rows | the ledger | the lifecycle hook (episodic) and `save_memory` (semantic) | the engagement | per user, per project |
| Session working memory | the harness context | none | the session | the session | none |

**Libraries (D3).** A library is an environment kind beside `project-local`. It declares a Git path, a commit, an OKF root and a licence policy. `ai library add brain --path ~/agentic-workspace/brain --pin <commit>` indexes the wiki once for that pin into a store under `INQUIRY_HOME/libraries/<name>/<commit>/`; `ai library refresh` re-pins and re-indexes; nothing in a library store is ever written by a session. A project attaches a library in `.agentic-inquiry/project.toml` (`libraries = ["brain"]`), committed, so every collaborator on the project reads the same library at the same pin. The pin is the same value the toolkit's `SOURCES.md` pin table records, so one number answers "which brain did this session read".

**Federated search (D4).** `search_docs`, `search_knowledge` and `build_context` fan out to the bound project store and the attached libraries, run the existing hybrid pipeline per store, fuse with reciprocal rank fusion, and return each hit with `origin` (`project` or the library name), `pin`, `licensed`, `claim_id` and `verified` where the source page carries them. `query_across_projects` stays restricted to libraries; two project stores never appear in one result set. The hook path (SessionStart, UserPromptSubmit) reads only the project store, as ADR-0005's budget requires; library reads happen on MCP and CLI paths.

**Licence and citation as filters (D5).** Every search call carries `audience`: `builder` returns licensed hits flagged; `render` filters them out before ranking so a licensed chunk cannot displace a renderable one. The filter AST gains `licensed`, `claim_id`, `verified_after` and `origin` fields; each provider translates them and rejects unknown fields as today. A hit from a brain page returns the claim ids the page cites, so a consumer can print "source name, verification date, URL" without ever printing the id, which is the toolkit's rule 3.

**Graph mapping.** The brain is already a graph: claims are nodes with `about` edges to pages, summaries `evidenced_by` claims, entities carry `contradicts` relations. The library indexer maps OKF frontmatter and claim records onto `graph_entities` and relationships so `graph_traverse` and `analyze_impact` work over the brain the way they work over code: "what cites this claim", "what contradicts this entity", "which pages go stale if this source is superseded". This is the hand-curated equivalent of community summaries: the concept page is the summary and a person wrote it.

**Memory promotion (D6).** Working memory stays in the session. Episodic memory is what the lifecycle hook captures into the ledger, queued then reconciled (RFC-0002). Semantic memory is an explicit `save_memory` with a reason. Promotion upward is explicit: `ai memory distill` proposes a Markdown observation into `docs/knowledge/` through core `project-knowledge`, which stays the only writer of that directory; the record's propose and accept path handles engagement facts; a fact that belongs to the brain becomes a curator request, never a write. Memory rows are rebuildable from the ledger, closing the open item in `docs/backlog.md`.

**Team readiness (D7).** The external provider contract gains a `library` role: tenancy maps `project_id` and library name to principals, events are append-only within a retention window, the pin is verified against the Git commit before a library is served, and embeddings may be produced server-side. Team shared knowledge is a second library with named curators. No hosting decision is taken here.

**Migration.** Existing project environments are unchanged. The brain is attached as the first library by the workspace and the toolkit. The workspace `llm-wiki` skill and the Agent Vault clone are archived once `ai library` serves the brain. The toolkit's `SOURCES.md` read protocol keeps its pin table and gains the library name.

## Options considered

Axis: where the brain lives relative to a project session. The options exhaust the axis: not indexed, copied in, indexed as a separate read-only store, or served from a shared service.

| Option | Description | Prior art | Trade-off against goals |
| --- | --- | --- | --- |
| A. Do nothing | Sessions read the brain by path when a skill tells them to | Toolkit `SOURCES.md` today | No search over the brain; every consumer re-implements the licence rule; cost of delay is a second memory product per repository |
| B. Copy the brain into each project index | `ai index ~/agentic-workspace/brain` inside the engagement | Common RAG practice | Breaks the pin, puts licensed text in client repositories, duplicates a large index per project |
| C. Library environments, federated read (recommended) | Read-only pinned store per library, attached per project, fused at query time | `query_across_projects` in the vector protocol; Git pins in the toolkit; OpenKB's compile-to-wiki with retrieval over the compiled pages | New environment kind and provenance fields; one index per pin shared by all projects |
| D. Shared hosted knowledge service | One database serving brain and projects | codebase-agent's governed knowledge store; the external provider contract | Right for a team, premature for one person; tenancy and audit must exist first; the contract already reserves the seat |

Option C now, D behind the contract later. B is the failure mode the toolkit's rules were written to prevent.

## Risks & what would make this wrong

- **Pre-mortem.** Federation makes every query slower: mitigate by indexing a library once per pin and caching its store; measure on the golden bench. Provenance fields get dropped by a consumer and a licensed sentence renders: mitigate with the `render` audience filter in the facade, not in the consumer, and a bench case that must return zero. A project store gets attached as a library by mistake: mitigate by refusing `ai library add` on any path that contains `.agentic-inquiry/project.toml` or an engagement record. Pins drift silently: mitigate by printing the pin in `ai status` and failing `render` queries against a library whose pin is older than a configured age.
- **Key assumptions.** The brain stays Markdown with OKF frontmatter and claim records (true today, `brain/wiki/AGENTS.md` v2). One pinned index of the brain fits a workstation (the wiki is thousands of pages, not millions). Consumers accept a required `audience` argument. Reciprocal rank fusion across stores of different sizes does not bury the small project store; if it does, weight by origin.
- **Drawbacks.** A second environment kind to document and test. Provenance fields widen the result contract. The team provider work is deferred, so a team today shares nothing but Git.

## Evidence & prior art

- **Spike.** Not run. The first spike is `ai library add` over the brain at the current pin, then five golden queries with expected claim ids and one licensed page that must not appear for `render`.
- **Repo precedent.** RFC-0001 golden bench; RFC-0002 and ADR-0005 hook budget and stdlib-only hot path; ADR-0004 three-tier memory on the Agent Vault base; `docs/storage-backends.md` external provider contract and the restriction on `query_across_projects`; `docs/design/result-contract.md` and `filter-ast.md` for the fields this RFC extends; `docs/backlog.md` open item on rebuilding memory rows from the ledger.
- **External prior art, read locally this session.** The brain schema (`brain/wiki/AGENTS.md`): claims, `licensed`, `verified`, source codes. The toolkit's `SOURCES.md`: read protocol, pin table, rules 3 to 5. codebase-agent (`~/projects/assets/codebase-agent`): reviewed knowledge bound to a human review and merged bytes, receipts with path and revision. design-builder (`~/projects/assets/design-builder`): one canonical spec, immutable revisions, proposals accepted per item. OpenKB (`~/projects/assets/OpenKB`): compile raw documents to an OKF wiki, retrieval over the compiled pages by document structure rather than by vectors alone. Web sources on graph-augmented retrieval and hierarchical retrieval were not fetched in this session and are not cited.

## Open questions

1. Should `audience` default to `render` (safe, may hide evidence from builders) or to `builder` (complete, may leak)? Recommended default: `render`, with the AFP pack and the toolkit passing `builder` explicitly. Owner: sammybasha. Decide by: acceptance of this RFC.
2. Does the library index include `brain/raw/` (source documents, some licensed and gitignored) or only `brain/wiki/`? Recommended: wiki only; raw analyst material never enters an index. Owner: sammybasha. Decide by: first spike.
3. Is the ledger under `INQUIRY_HOME` the right home for project memory when a team shares an engagement, or does memory move into the engagement repository? Recommended: stay in `INQUIRY_HOME` per user until D7 lands; the team provider decides. Owner: sammybasha. Decide by: 2026-11-30.

## Follow-on artifacts

- ADR: library environments are read-only and commit-pinned.
- ADR: canonical knowledge is Markdown in Git; indexes are derived.
- Spec: `docs/specs/library-environments/` (environment kind, indexer, `ai library` verbs, project attachment).
- Spec: `docs/specs/federated-search-provenance/` (result contract fields, `audience`, filter AST fields, bench cases).
- Spec: `docs/specs/memory-promotion/` (`ai memory distill`, ledger rebuild).
- Convention change: `docs/CHARTER.md` names libraries as a delivery surface; `docs/storage-backends.md` gains the library role.
