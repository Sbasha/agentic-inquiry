# Logical Schema Reference (Canonical Field Names)

> Historical reference. This page describes PostgreSQL-family providers, cloud connectors or remote embedders that are not part of this local-only distribution. It is retained as design input for the external provider contract in [storage-backends.md](../storage-backends.md).

This document defines the canonical logical schemas used by Agentic Inquiry. Adapters may store data differently (physical schema), but must map to these logical field names at the boundary.

## Goals

- Prevent drift in field naming across adapters.
- Provide one place to confirm “what columns exist” for query building (`QuerySpec.order_by`, `Filter.field`, `select_columns`).
- Align documentation with the current codebase models and LanceDB tables.

## Naming Rules

- Canonical field names are snake_case.
- Do not rename existing logical fields when introducing an adapter.
- If a backend uses different names, the adapter maps logical → physical.

## Core Tables

### `document_chunks`

Canonical fields (based on `agentic_inquiry/models/document_chunk.py` and current LanceDB schema):

- `id` (str, required)
- `doc_id` (str, required)
- `file_path` (str, required)
- `project_id` (str, required)
- `content` (str, required)
- `fts_text` (str, required)
- `vector` (list[float], required; dim = embeddings default)
  - **Note:** For server-side embedding strategies (AlloyDB), this field may be `NULL` initially and populated by `generate_embeddings()` after indexing
- `content_type` (str, required; e.g. `CODE`, `PROSE`)
- `language` (str)
- `page_number` (int; sentinel `-1`)
- `line_start` (int; sentinel `-1`)
- `line_end` (int; sentinel `-1`)
- `chunk_index` (int)
- `total_chunks` (int)
- `element_type` (str)
- `element_name` (str)
- `parent_id` (str)
- `child_ids` (list[str])
- `symbols` (list[str])
- `indexed_at` (str/datetime; ISO string at storage boundary)
- `source_modified_at` (str/datetime; ISO string at storage boundary)
- `metadata` (JSON/string/struct depending on backend; see `docs/development/parser-guidelines.md`)
- `ranking_signals` (JSON/string/struct depending on backend)

Notes:
- `metadata` contents are constrained (no lists/dicts at the parser chunk level); complex data must be serialized or moved to dedicated fields.

### `graph_entities`

Canonical fields (based on `agentic_inquiry/models/graph_entity.py` and current LanceDB schema):

- `id` (str, required)
- `name` (str, required)
- `type` (str, required; e.g. `code_function`, `doc_section`)
- `file_path` (str, required)
- `doc_id` (str, required)
- `project_id` (str, required)
- `vector` (list[float], required; dim = embeddings default)
  - **Note:** For server-side embedding strategies (AlloyDB), this field may be `NULL` initially and populated by `generate_embeddings()` after indexing
- `line_start` (int; sentinel `-1`)
- `line_end` (int; sentinel `-1`)
- `pagerank` (float, optional)
- `betweenness` (float, optional)
- `community_id` (str, optional)
- `has_ranking_signals` (bool, required)

Important:
- Use `pagerank` (current code + table schema), not `page_rank`.

### `graph_relationships`

Canonical fields (based on `agentic_inquiry/models/graph_relationship.py` and current LanceDB schema):

- `id` (str, required)
- `source_id` (str, required)
- `target_id` (str, required)
- `type` (str, required; e.g. `calls`, `imports`)
- `project_id` (str, required)
- `vector` (list[float], required; dim = embeddings default)
  - **Note:** For server-side embedding strategies (AlloyDB), this field may be `NULL` initially and populated by `generate_embeddings()` after indexing
- `metadata` (JSON/string depending on backend)

Important:
- Use `source_id` / `target_id` (current code), not `source_entity_id`.

## Memory Tables

Memory tables are owned by the memory subsystem but must still adhere to canonical logical field names so adapters can support them.

### `memory_episodic_medium`

Canonical fields (based on `agentic_inquiry/memory/layers/episodic.py`):

- `id` (str)
- `agent_id` (str)
- `session_id` (str)
- `conversation_id` (str)
- `task_id` (str)
- `project_id` (str)
- `content` (str)
- `summary` (str)
- `importance` (float)
- `tier` (str)
- `creator_agent_id` (str)
- `modifier_agent_id` (str)
- `content_source` (str)
- `created_at` (datetime)
- `accessed_at` (datetime)
- `modified_at` (datetime)
- `access_count` (int)
- `vector` (list[float])
- `summary_vector` (list[float])
- `event_type` (str)
- `emotional_valence` (float)
- `emotional_arousal` (float)
- `subject` (str)
- `relationship` (str)
- `object` (str)
- `confidence` (float)
- `metadata` (JSON/string)

### `memory_semantic_high`

Canonical fields (based on `agentic_inquiry/memory/layers/semantic.py`):

- `id` (str)
- `agent_id` (str)
- `conversation_id` (str)
- `subject` (str)
- `relationship` (str)
- `object` (str)
- `content` (str)
- `summary` (str)
- `confidence` (float)
- `importance` (float)
- `tier` (str)
- `creator_agent_id` (str)
- `modifier_agent_id` (str)
- `content_source` (str)
- `created_at` (datetime)
- `accessed_at` (datetime)
- `modified_at` (datetime)
- `access_count` (int)
- `vector` (list[float])
- `summary_vector` (list[float])
- `session_id` (str)
- `task_id` (str)
- `project_id` (str)
- `event_type` (str)
- `emotional_valence` (float)
- `emotional_arousal` (float)
- `metadata` (JSON/string)

## Physical Table Names

Physical table names vary by backend:
- **LanceDB:** Uses logical names directly (`document_chunks`, `graph_entities`, `graph_relationships`)
- **PostgreSQL/CloudSQL/AlloyDB:** Uses `ai_` prefix (`ai_v_chunks`, `ai_g_entities`, `ai_g_relationships`)

Adapters handle the mapping between logical and physical names transparently.

## Adapter Compatibility Notes

- Some backends do not support multi-column FTS. Adapters may:
  - choose a single FTS column (e.g. `fts_text`)
  - or emulate multi-column search in the app layer
- Some backends do not support server-side filtering on nested metadata. Prefer promoting frequently filtered metadata to first-class columns.
- **Server-side embedding (AlloyDB):** When `embedding_strategy: "server_side"`, vector fields are populated after indexing via provider's `generate_embeddings()` method. See [hybrid-embedding-strategy.md](hybrid-embedding-strategy.md) for details.

