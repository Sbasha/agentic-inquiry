# Agentic Inquiry

A local library for searching documents and code with source citations, remembering selected observations and maintaining authored knowledge pages. The command is `ai`. Embeddings, optional reranking, document extraction and storage run locally; the CLI does not call a generative-model API or upload source files.

Version 0.1.0 is a public preview. The interfaces and stored schema may change before a stable release. See the [architecture](ARCHITECTURE.md), [contribution guide](CONTRIBUTING.md), [security policy](SECURITY.md), [design contract](DESIGN.md) and [remaining implementation plan](IMPLEMENTATION_PLAN.md).

## Install and search

Requires Python 3.11 or newer, Git and [uv](https://docs.astral.sh/uv/). Install the tagged source release with uv. The package is not published to a registry:

```sh
uv tool install "git+https://github.com/Sbasha/agentic-inquiry.git@v0.1.0"
ai --help
```

Replace the paths below with an existing source directory and your chosen library directory. These examples register the source as collection `code` in project `work`. If that root is already registered, use its returned `name` and `project_id` instead.

```sh
inquiry_root=/absolute/project
inquiry_db=/absolute/library

ai setup "$inquiry_root" --db "$inquiry_db" --name code --project work
ai index --collection code --db "$inquiry_db"
ai search "How is authentication handled?" --collection code --db "$inquiry_db" --limit 5
ai context "authentication" --project work --collection code --db "$inquiry_db" --budget 4096
ai status --db "$inquiry_db"
ai doctor --db "$inquiry_db"
```

Pass a result's `id` to `ai read CHUNK_ID --db "$inquiry_db"` to retrieve its cited passage. Search defaults to hybrid keyword and vector retrieval; `--mode lexical` and `--mode vector` select either method. Scope results with `--project`, `--collection`, `--language`, `--path` or `--type`. Context includes evidence and, with an explicit project, relevant memory. Its reported budget uses UTF-8 bytes as a conservative token upper bound, including citation metadata, rather than a provider tokenizer.

`--db` names the whole library directory, containing durable SQLite records, `knowledge/`, derived `index/` generations and a `models/` cache. Without it, `index` and `setup` use `SOURCE/.agentic-inquiry`; other ordinary commands use the current directory's `.agentic-inquiry`. Use the same explicit library from other directories. Exclude `.agentic-inquiry/` from source control when storing it inside a project.

CLI operations return JSON with `schema_version: 1`; `--json` is optional. Structured fields come from `--input FILE` or `--input -` for stdin, limited to a 1 MiB JSON object. Command-line fields override input fields. Exit codes are `0` for success, `1` for partial, unsupported or failed work, and `2` for errors. Reduced extraction coverage, including explicitly omitted Office content, produces `complete: false`. Search and context retain this coverage signal while returning available evidence. Inspect partial reports before relying on their coverage.

## Sources and local models

Supported extraction includes UTF-8 text, Markdown, HTML, JSON, YAML, XML, CSV/TSV, PDF, DOCX, PPTX and XLSX. Citations retain source identity, version and hash, with locations such as code spans, PDF pages, document paragraphs, slides and spreadsheet cells. Structural indexing covers Python, JavaScript, TypeScript/TSX, Java, Go, Rust, C, C++/C# and Apex; other supported code files use text extraction.

Git roots use tracked and non-ignored files. Source files are read-only. Collection policies exclude symlinks, common credential filenames and dependency directories; filename exclusions are not a content-based secret scanner. Extraction has bounded file size, time, memory, archive expansion and output. The default file limit is 32 MiB. Encrypted, malformed, unsupported or resource-limited sources have explicit diagnostics. Changed, deleted and unresolved evidence remains distinguishable from current evidence; default retrieval excludes stale material, with `--include-stale` available for inspection. Run `index` again to reconcile source changes.

First indexing downloads the public `BAAI/bge-small-en-v1.5` embedding model, approximately 67 MB. Later use is local. Hybrid/vector search requires cached embeddings and never downloads a missing model; lexical search does not initialize a model. For optional local reranking, explicitly prepare its approximately 80 MB model, then select it at search time:

```sh
ai setup "$inquiry_root" --db "$inquiry_db" --name code --project work --rerank
ai search "authentication" --db "$inquiry_db" --rerank
HF_HUB_OFFLINE=1 ai search "authentication" --db "$inquiry_db"
```

Reranking uses `Xenova/ms-marco-MiniLM-L-6-v2` on CPU. Offline indexing also needs the embedding cache. Help, capabilities, doctor and status do not download models.

OCR is opt-in and requires a separately installed local Tesseract executable and the selected language data. It supports images and PDF pages that need OCR. First register a collection with `ai collection register /absolute/documents --name documents --project work --db "$inquiry_db"`, then enable English OCR:

```sh
ai collection configure documents --db "$inquiry_db" --input - <<'JSON'
{"settings":{"parser":{"ocr":true,"ocr_language":"eng"}}}
JSON
ai index --collection documents --db "$inquiry_db"
```

Configuration replaces the collection's settings object; include existing `include`/`exclude` patterns and parser settings you want to retain. `doctor` reports local parser and OCR availability. OCR-derived locations identify their provenance; extraction does not establish recognition accuracy.

## Memory and knowledge

Memory requires an explicit project. Records preserve origin, revisions, source citations and capture receipts. Shared writes and shared recall require separate explicit opt-ins (`--shared` and `--include-shared`). An authored preference can be stored without a source citation:

```sh
ai memory add --project work --db "$inquiry_db" --input - <<'JSON'
{"content":"Use English for project documentation.","kind":"preference","origin":"user","provenance":{"source":"explicit project preference"}}
JSON
ai memory recall "documentation" --project work --db "$inquiry_db"
ai memory export --project work --db "$inquiry_db"
```

Use `inspect` to obtain a memory's ID and revision before `correct`, `supersede` or `retract`; these operations require `--expected-revision` and `--reason`. `contradictions` lists or explicitly records conflicting memory claims. `forget` accepts `{"memory_ids":["ID"]}` through `--input`, previews by default and requires `--apply` to remove those records from recall. History and existing backups are retained; forgetting is not secure erasure.

Knowledge pages are Markdown in the library with separately recorded citations and dependencies. This creates an uncited operator note:

```sh
ai knowledge write --project work --db "$inquiry_db" --input - <<'JSON'
{"page_id":"work-notes","body":"# Project notes\n\nDocumentation language: English.\n","expected_hash":null,"citations":[],"dependencies":[]}
JSON
ai knowledge inspect work-notes --project work --db "$inquiry_db"
ai knowledge validate work-notes --project work --db "$inquiry_db"
ai knowledge stale --project work --db "$inquiry_db"
```

For source-backed memory or pages, supply complete `citation` objects returned by search/read in the `citations` array. The library checks their identity, scope, location and current source hash. Page updates require the current `content_hash` as `expected_hash`; `null` is only for a new file. Manual edits are preserved on conflicts. Dependencies are page IDs, checked transitively for changed or unresolved support and cycles. Validation reports stale pages without rewriting them. `knowledge export` returns Markdown and citations, optionally writing new files to a JSON `destination`. `discard-pending` explicitly dismisses a conflicting draft with the expected current file hash.

Capture is disabled until explicitly enabled. `capture enable`, `submit`, `status`, `retry`, `recall` and `disable` operate within a project. Submission requires a stable `event_id` and selected structured `observations`; duplicate delivery returns the existing receipt, while changed content under that ID is rejected. Failures remain pending for retry. Raw transcripts and hidden reasoning are not accepted by the native integration boundary.

## Codex and Pi

The standalone integration and AFP's native registration are alternative owners. Choose one owner per project/client. Installing files, enabling project behavior and observing a live client are separate steps.

From the registered project root, preview the standalone Codex installation, then apply it explicitly:

```sh
cd "$inquiry_root"
ai integration install --client codex --root "$PWD" --db "$inquiry_db"
ai integration install --client codex --root "$PWD" --db "$inquiry_db" --apply
ai integration inspect --client codex --root "$PWD" --db "$inquiry_db"
```

The installer projects the `ai` skill, explorer/command-guide/setup-helper roles and native hooks into the project's `.agents/` and `.codex/` directories. The package also contains a Codex plugin bundle; avoid loading both registrations. Use `--client pi` for the project `.pi/extensions/agentic-inquiry/` extension. Install and uninstall preview by default, preserve unrelated configuration, record ownership receipts and refuse collisions or modified owned files. They do not install global client configuration or enable recall/capture.

Enable policy explicitly after reviewing the installed files. This command writes policy immediately; it does not have an enable preview:

```sh
python3 -c 'import json,os; print(json.dumps({"project_root":os.path.realpath(os.getcwd()),"recall":True,"capture":True,"refresh":True}))' |
  ai integration enable --client codex --owner standalone --db "$inquiry_db" --input -
ai integration library --client codex --root "$PWD"
```

Use `--client pi` in both commands for Pi. The runtime owns the selected-library pointer in the project's `.agentic-inquiry/clients.json`; native hooks resolve it through `ai` rather than keeping their own database setting. Explicitly disable the current owner before changing owners or library selection. For AFP, its pack owns native registration; enable with `--owner afp` through that setup instead of installing standalone assets. Installation does not override an enabled owner.

Start or reload the client in the project, complete any native trust review and ensure `ai` is on its PATH. In Codex, invoke `$ai`. In Pi, use `/ai status`, `/ai search authentication`, `/ai context authentication`, or a JSON argv array such as `/ai ["memory","recall","--project","work"]`. Pi's `ai_remember` tool submits a selected observation using its native tool-call ID.

Lifecycle adapters support startup/prompt recall, selected capture, edited-artifact refresh, compaction and shutdown where their native client provides the event. Pre-compaction does not scrape transcripts; recall is delivered on continuation. There is no claimed `TaskCompleted` parity. Without a native stable mutation ID, capture is refused or left for explicit submission. Check `capture status`, `status` and `integration reconcile` for pending work. `integration disable` uses the same project-root/client/owner fields as enable. `integration uninstall --client CLIENT --root ROOT` previews removal; add `--apply` to remove unchanged owned files.

`ai capabilities --json` reports supported contracts, not proof of a live session. Pi source-extension discovery and direct `/ai` command execution have been observed separately from lifecycle acceptance. Installed-client recall, capture, compaction and recovery require their own native evidence; installation and component tests do not establish them.

## Command reference

Use `ai COMMAND --help` for argument syntax. Family operations accept structured fields through `--input`.

| Commands | Purpose |
| --- | --- |
| `setup`, `index`, `search`, `read`, `context` | Register sources, index and retrieve cited evidence within a budget. |
| `collection register/list/inspect/configure/relocate/detach` | Manage multiple roots and policies in one library. Relocation preserves identity; detach previews unless applied. |
| `symbols`, `entity`, `relations`, `impact`, `lineage` | Navigate static definitions, references and bounded dependency paths with source citations and resolution limits. |
| `patterns`, `services` | Retrieve evidence for host-authored analysis; results do not establish runtime architecture. |
| `memory add/recall/inspect/correct/supersede/retract/forget/export/contradictions` | Manage scoped, revisable observations and explicit conflicts. |
| `knowledge write/inspect/validate/stale/export/discard-pending` | Maintain pages while preserving manual edits and stale evidence. |
| `capture enable/disable/status/submit/retry/recall` | Control durable, idempotent capture and pending retries. |
| `integration install/uninstall/inspect/enable/disable/library/hook/reconcile` | Install client assets, choose policy/ownership and handle bounded native events. |
| `watch`, `status`, `doctor`, `capabilities` | Reconcile sources and inspect state, local dependencies and supported contracts. |
| `remove`, `cache clean`, `backup`, `restore` | Remove selected evidence, reclaim derived storage and preserve durable records. |
| `mcp` | Serve the same local operations over client-owned stdio with a fixed root/project. |
| `evaluation freeze/trial/judge/cost/close/inspect/report` | Record and replay frozen studies, attempts, independent judgments and cost evidence. No model runs are launched. |

For example, `ai relations Library --type callers --db "$inquiry_db"` returns static callers and unresolved relationships; `ai impact Library --depth 3 --max-nodes 100 --db "$inquiry_db"` bounds traversal. Dynamic dispatch, external dependencies and ambiguous bindings remain explicit limitations.

Start a read-only MCP server with `ai mcp --db "$inquiry_db" --root "$inquiry_root" --project work`. A client launches this command and owns its stdio lifecycle. Add `--allow-write` only when that client should be able to perform the admitted scoped writes. Tools cannot change the configured library, project or source root; shared memory is not enabled by this server.

## Maintenance and recovery

`ai watch --db "$inquiry_db"` runs foreground reconciliation with durable checkpoints; `--once` performs one pass. It does not install a background service. `ai integration reconcile --db "$inquiry_db"` retries pending integration work. `ai remove relative/source.py --collection code --db "$inquiry_db"` removes that source's evidence and preserves the original file.

```sh
ai backup /absolute/new-backup --db "$inquiry_db"
ai restore /absolute/new-backup --db /absolute/restored-library
ai index --collection code --db /absolute/restored-library --rebuild
ai cache clean --db "$inquiry_db"
ai cache clean --db "$inquiry_db" --apply
```

Backups include durable records, knowledge files and identity metadata, with checksums. They exclude original source files, derived vectors and model caches. Keep source originals separately. The backup destination must be new and outside the library. Restore validates the snapshot, preserves a recoverable prior destination and requires an index rebuild before search. A restored library needs access to its registered sources and embedding model; if its path changes, explicitly update the client selection after disabling the old policy.

Cache cleanup previews recognized inactive index generations; `--apply` removes them. Add `--models` to also remove model caches, requiring model preparation before later vector/reranked use. Durable SQLite records, memory, knowledge and the active index are retained. To reclaim orphan rows within the active generation, rebuild first, then clean inactive generations. Cleanup refuses conflicting active readers. Deletion and cleanup do not erase existing backups or storage history.

## Validation and limits

```sh
uv sync --locked
uv run pytest
uv run ruff check src tests
uv run ruff format --check src tests
uv build
```

The [design](DESIGN.md) defines behavior and acceptance; the [implementation plan](IMPLEMENTATION_PLAN.md) lists open work. Tests establish checked contracts. Static relationships, retrieval relevance, OCR accuracy and model answers have distinct limits. Comparative answer quality, no-quality-loss claims and cost savings remain unverified without a frozen matched study and independent judgments. The evaluation ledger preserves unknown usage and failed or incomplete attempts rather than treating them as zero cost or successful answers.

## License

Apache-2.0. See [LICENSE](LICENSE). Dependencies and downloaded models retain their own licenses.
