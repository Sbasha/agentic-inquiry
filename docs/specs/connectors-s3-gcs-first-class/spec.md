# Spec: S3/GCS connectors first-class

- **Status:** Implementing <!-- Draft | Approved | Implementing | Shipped | Archived -->
- **Owner:** s-ananthanarayan_accent
- **Plan:** [`plan.md`](plan.md)
- **Constrained by:** Issue #82 (Cluster 4); none (no ADR — `s3 = ["s3fs>=2024.1.0"]` and `gcs = ["gcsfs>=2024.1.0"]` already exist under `[project.optional-dependencies]` in `pyproject.toml`)

> **Spec contract:** this document defines what "done" means. The implementing
> PR must match this spec, or update it. Verification must be derivable from it.

## Objective

A multi-cloud client who installs Agent-Vault with the `gcs` extra and asks for
a `gcs` connector must actually get one. Today the `GCSConnector` class carries
`@register_connector("gcs")`, but nothing imports `agent_vault.connectors.gcs`
at runtime, so the decorator never fires — `get_connector("gcs", ...)` raises
`KeyError` and `"gcs"` never appears in `list_connectors()`. GCS is documented
as a first-class content source but is unreachable. This spec makes GCS
genuinely first-class: registered at import time (guarded on `gcsfs`
availability, like S3), URI-consistent with its registered name and the docs
(`gcs://` everywhere, not the current `gs://`), covered by the same contract
tests S3 has, and advertised in the README alongside S3. Success: an operator
can `pip install agent-vault[gcs]`, call `get_connector("gcs", bucket=...)`,
and round-trip a `gcs://bucket/key` URI — and the README and connector guide
agree on what's supported. Secondarily, this spec establishes the opt-in
`cloud_smoke` live-access test pattern for **both** cloud connectors (S3 and
GCS), so the supported matrix has a credential-gated verification path rather
than only mocked coverage.

## Boundaries

The three-tier guard that keeps an implementing agent inside the lines.
*Always do* applies without asking; *Ask first* requires human sign-off
before proceeding; *Never do* is a hard rule, even under time pressure.

### Always do

- Mirror the existing S3 pattern (`s3.py`, `test_s3.py`, the `try/except
  ImportError` registration in `_register_builtin_connectors`) for GCS — same
  shape, same guards, same test structure.
- Keep optional-dependency guards: importing `agent_vault.connectors` with
  neither `s3fs` nor `gcsfs` installed must still succeed (cloud connectors
  degrade to "not registered", never an import-time crash).
- Keep README and `docs/development/connector-guide.md` agreeing on the
  supported source matrix and URI schemes.

### Ask first

- Any change to the `s3://` scheme or existing S3 behavior (this spec only
  touches GCS scheme and registration).
- Adding runtime URI-prefix dispatch (`get_connector` resolution from a
  source URI) anywhere in production code — that is a separate feature.

### Never do

- **No new top-level dependency** — `s3fs`/`gcsfs` already exist as optional
  extras; add nothing else.
- **No new module boundary or abstraction layer** (no dispatcher, factory, or
  resolver) — this is registration + tests + docs, not re-architecture.
- Do not delete `hash_cache.py` / `lru_cache.py` or rewrite the registry
  singleton in this PR — explicitly deferred to a follow-up issue.
- Do not wire connectors into `indexing/pipeline.py` or change its public
  signature.
- **Do not touch `gs://` usage outside `agent_vault/connectors/gcs.py`.**
  `agent_vault/onboard/artifact_storage.py` and `docs/mcp/deployment.md` use
  `gs://` for unrelated GCS-native artifact / vector-DB URIs and must stay
  as-is. The scheme change is scoped to the connector's own `_build_uri` /
  `_uri_to_path` only — no global `gs://` → `gcs://` rename.

## Testing Strategy

- **GCS registration is reachable** (Objective: `get_connector("gcs")` works,
  `"gcs"` in `list_connectors()`) — **TDD**. A failing test first proves the
  current bug (registration absent), then the import fix turns it green. This
  is the core invariant of the spec.
- **GCS URI round-trips on `gcs://`** (Objective: `_build_uri`/`_uri_to_path`
  symmetry, `item.protocol == "gcs"`) — **TDD**. Pure string logic with a
  compressible invariant; mirror `TestS3URIHandling`.
- **GCS connector behavior under mocked fsspec** (list/open/hash, ImportError
  without `gcsfs`) — **TDD**, mocked filesystem. These tests must **drive the
  connector** (`await connector.list()` / `await connector.open(item)` with the
  mock injected as `connector._fs`) and assert on the yielded `SourceItem` /
  `SourceContent`, **not** assert on the mock object directly. (The existing
  `test_s3.py` mock tests assert on the mock — e.g. `len(mock_fs.glob(...))`
  — which proves the mock, not the connector; do not replicate that shape.)
- **Live S3/GCS access** (`cloud_smoke`) — **goal-based check**: the tests
  exist and are collected but skip without creds; verification is that
  `pytest -m cloud_smoke --co` collects them and the default run skips them.
- **README / connector-guide sync** — **goal-based check**: `grep` shows
  `S3Connector`/`GCSConnector`/`s3://`/`gcs://` documented as supported and the
  two docs agree; no automated test.

## Acceptance Criteria

- [ ] After `import agent_vault.connectors`, `"gcs"` and `"s3"` both appear in
      `list_connectors()` **regardless of whether `gcsfs`/`s3fs` are installed**
      (registration is an import-time decorator effect; the cloud-lib check is
      only at construction). With `gcsfs` installed, `get_connector("gcs",
      bucket="b")` returns a `GCSConnector`; without it, that call raises
      `ImportError` from the constructor.
- [ ] Importing `agent_vault.connectors` with neither extra installed does not
      raise; `GCSConnector` is exported (the class — mirroring `S3Connector`,
      the module imports fine without the cloud lib).
- [ ] `GCSConnector._build_uri("b/k") == "gcs://b/k"` and
      `_uri_to_path("gcs://b/k") == "b/k"`; a listed item's `.protocol == "gcs"`.
- [ ] `tests/connectors/test_gcs.py` mirrors `test_s3.py` coverage (creation,
      prefix handling, root path, URI handling, mocked list/open/hash,
      ImportError path, registration) and passes in CI.
- [ ] At least one `@pytest.mark.cloud_smoke` test each for live S3 and GCS
      exists, is collected under `-m cloud_smoke`, and is skipped by default.
- [ ] README has a "Content sources" subsection listing filesystem, S3
      (`[s3]`), and GCS (`[gcs]`); `connector-guide.md` URI schemes match the
      code (`s3://`, `gcs://`).
- [ ] `make bench` recall@10 stays green (connectors change doesn't touch
      search), and `ruff`/`mypy`/`pytest` gates pass.
- [ ] The deferred 4.3 work (registry rewrite, `hash_cache.py` removal) is
      recorded as a filed GitHub issue whose number is linked in the PR body
      (verifiable from the PR, not from the diff).
