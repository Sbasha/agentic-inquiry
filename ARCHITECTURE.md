# Architecture

Agentic Inquiry is a local Python application with one command boundary and one operator-selected library. It reads registered source roots, writes versioned evidence and authored state into the library, and exposes the same operations through the `ai` CLI and a fixed-scope MCP server.

## System boundaries

The application has four external boundaries:

1. Registered source roots are read-only inputs. Inventory applies collection policy before reading eligible regular files.
2. The library directory owns mutable records, knowledge pages, derived search indexes and model caches.
3. Codex and Pi integrations project packaged assets into a project and route native lifecycle events to the selected library.
4. Evaluation studies use their own append-only SQLite database and record supplied evidence. They do not launch agents or models.

The command dispatcher in `src/agentic_inquiry/cli.py` is the shared application interface. The CLI parses arguments into an action and payload, while the MCP server admits a fixed subset of the same actions through `invoke`. This keeps authorization and behavior at one boundary.

## Components

| Component | Responsibility | Durable output |
| --- | --- | --- |
| `library.py` | Library identity, schema, transactions, locking, backup and restore | `records.sqlite3`, identity metadata and knowledge files |
| `store.py` | Source inventory, versioning, chunk publication, embedding and retrieval | Source/version/chunk records and active LanceDB generation |
| `ingestion.py` | Bounded extraction for supported document and text formats | Structured segments and explicit diagnostics |
| `structure.py` | Language-aware spans and token-bounded code chunks | Chunk metadata consumed by indexing |
| `graph.py` | Static symbols, references and bounded relationship traversal | Symbol and relationship records |
| `knowledge.py` | Scoped memory, citations, capture receipts and authored pages | Memory revisions, capture state and `knowledge/` files |
| `integration.py` | Integration policy, selected library, native event handling and retry | Integration configuration and pending work |
| `clients.py` | Preview/apply installation for Codex and Pi | Project assets and ownership receipts |
| `mcp_server.py` | Client-owned stdio server with fixed root, project and write policy | No separate state |
| `evaluation.py` | Frozen-study, trial, judgment and cost evidence accounting | Study-local `evaluation.sqlite3` |
| `cache.py` | Preview/apply removal of inactive derived data | No new durable state |

## Indexing and retrieval

Indexing follows one publication path:

1. A collection registration binds a stable collection identity to a canonical source root and project.
2. Inventory selects tracked and non-ignored files for Git roots, then applies include, exclude, credential-name, dependency-directory, symlink and size rules.
3. Extraction runs on supplied file bytes in an isolated subprocess with time, memory, archive, page, node and output bounds.
4. Structural parsing produces language-aware spans when supported. Other supported files retain format-specific locations such as pages, paragraphs, slides and cells.
5. The store writes immutable source versions, chunks, hashes and diagnostics, then publishes the active derived index generation.
6. Search, read, context and graph operations query the active generation while retaining source identity, version, hash, location and coverage state.

Changed, deleted and unresolved evidence remains identifiable. Current retrieval excludes stale evidence by default. A rebuild creates a fresh derived generation without changing the registered source or authored knowledge.

## Library layout and recovery

The selected library directory contains:

- `records.sqlite3` for collection identity, evidence metadata, memory, citations, capture and integration configuration
- `knowledge/` for authored Markdown pages
- `index/` for replaceable LanceDB generations
- `models/` for replaceable local model caches
- `write.lock` for serialized mutations

Mutations use a file lock and SQLite transactions. File replacement uses a temporary sibling followed by `os.replace`. The library rejects symlinks at protected state paths.

Backups include durable records, knowledge and identity metadata with checksums. They exclude original source files, derived indexes and model caches. Restore validates the snapshot, preserves a recoverable prior destination and requires rebuilding the index before retrieval.

## Memory and knowledge

Memory belongs to an explicit project and retains origin, revision and provenance. Shared writes and shared recall are independent opt-ins. Corrections, supersession, retraction and forgetting require explicit operations; retained history and backups mean forgetting is not secure erasure.

Knowledge pages are ordinary Markdown plus separately recorded citations and dependencies. Writes use the current content hash for concurrency control. When an authored file and a proposed update conflict, the authored file remains authoritative and the pending proposal must be inspected or discarded explicitly.

Capture accepts selected structured observations with stable event IDs. Duplicate delivery returns the original receipt, while different content under the same event ID is rejected. Failed work remains pending for explicit retry or reconciliation.

## Native clients

Codex and Pi assets are packaged with the distribution. Installation previews by default, applies only on request, records ownership and refuses collisions or changes to owned files. Installation does not enable recall, capture or refresh.

Policy activation selects one owner and one library for a project/client pair. Standalone installation and AFP registration are alternative owners. Native hooks resolve the selected library through `ai`, send bounded lifecycle events and leave unsupported events explicit.

The MCP server is launched by its client over stdio. Its library, project and source root are fixed at startup. Read actions are available by default; admitted scoped writes require `--allow-write`. The server cannot change its configured scope or enable shared memory.

## Trust and resource limits

Source content, archives and extracted markup are untrusted input. The implementation excludes symlink sources, rejects symlinks in protected destinations, bounds file and extraction work, defuses XML parsing, and reports partial or failed extraction instead of silently claiming complete coverage.

The default source file limit is 32 MiB. Structured CLI input is limited to a 1 MiB JSON object. Model downloads happen only during explicit preparation or first indexing; ordinary retrieval does not download a missing model. Source exclusion rules reduce accidental credential indexing but do not inspect file contents for secrets.

## Static and generative limits

The graph is static analysis. Dynamic dispatch, runtime behavior, external dependencies and ambiguous bindings remain explicit limitations. Agentic Inquiry retrieves evidence and records operator or client-supplied observations; it does not call a generative-model API or claim that retrieved evidence proves a system's runtime behavior.
