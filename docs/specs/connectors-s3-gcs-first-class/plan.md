# Plan: S3/GCS connectors first-class

- **Spec:** [`spec.md`](spec.md)
- **Status:** Done <!-- Drafting | Executing | Done -->

> **Plan contract:** this is the implementation strategy. Unlike the spec, this
> document is allowed to change as you learn. When it changes substantially
> (a different approach, not just a re-ordering), note why in the changelog
> at the bottom.

## Approach

Three independent, low-risk slices. **T1** fixes the actual bug: register
`GCSConnector` at import time (guarded on `gcsfs`, mirroring S3) and export it
from `connectors/__init__.py`, and align its URI scheme from `gs://` to
`gcs://` so the emitted `item.protocol` matches the registered name `"gcs"` and
the docs. **T2** adds the test coverage GCS lacks — `test_gcs.py` mirroring
`test_s3.py` (unit + mocked fsspec), a registry assertion that both `s3` and
`gcs` register on import, and `cloud_smoke`-marked live tests for S3 and GCS.
**T3** is docs: a README "Content sources" subsection and a connector-guide
sync. The riskiest part is the URI scheme change in T1 — but since GCS has
never been reachable at runtime there is no stored `gs://` data to migrate, so
the blast radius is the connector's own (currently untested) string logic,
which T1's own RED-first tests pin. T1+T2 form one sequential TDD unit (T1
writes the failing contract tests and the fix; T2 broadens coverage); T3 (docs)
is independent. Small enough to do single-agent in order — no fan-out.

## Constraints

- Issue #82 (Cluster 4) — revised scope: S3/GCS stay first-class; test +
  document + sync.
- No ADR: `s3 = ["s3fs>=2024.1.0"]` and `gcs = ["gcsfs>=2024.1.0"]` already
  exist in `pyproject.toml` `[project.optional-dependencies]`. No new
  dependency is introduced.
- `cloud_smoke` pytest marker already registered in `tests/conftest.py`
  (added in Cluster 3) — reuse it, do not redefine.
- Deferred (out of scope, follow-up issue): registry singleton →
  module-dict rewrite, `hash_cache.py` deletion.

## Construction tests

Most construction tests live under **Tasks** below. Cross-cutting:

**Integration tests:** none beyond per-task tests. Registration is the only
cross-module behavior and it is covered by the registry test in T2.
**Manual verification:** `make bench` recall@10 stays `1.0000` (sanity that the
connectors change didn't perturb search/indexing); `uv run python -c "import
agentic-inquiry.connectors as c; print(c.list_connectors())"` shows `gcs` when
`gcsfs` is installed.

## Tasks

> **Note on T1/T2 ordering.** T1 and T2 are **not** independent and must run
> sequentially as one TDD unit — T1 owns the *contract* tests for its own
> behavior change (red first, then the fix turns them green); T2 adds the
> broader mocked-behavior mirror and the cloud_smoke pattern. Do not fan these
> out in parallel. T3 (docs) is genuinely independent (`Depends on: none`).

### T1: GCS registration + `gcs://` scheme — contract tests green

**Depends on:** none

**Tests:** (write these RED first, before the fix)
- `tests/connectors/test_gcs.py::...::test_gcs_registered_on_import`: after
  `import agentic_inquiry.connectors`, `"gcs"` is in `list_connectors()` and
  `get_connector("gcs", bucket="b")` returns a `GCSConnector`
  (skip-guarded on `gcsfs` availability). RED today (decorator never fires).
- `test_build_uri` / `test_uri_to_path` round-trip: `_build_uri("b/k") ==
  "gcs://b/k"`, `_uri_to_path("gcs://b/k") == "b/k"`, `_uri_to_path("b/k") ==
  "b/k"` (passthrough). RED today (`gs://`).
- `test_protocol_is_gcs`: a `SourceItem` whose uri is `connector._build_uri(...)`
  has `.protocol == "gcs"`.
- `test_import_without_gcsfs` (skip unless `gcsfs` absent) and the
  `agentic_inquiry.connectors.GCSConnector is None` fallback path.

**Approach:**
- In `agentic_inquiry/connectors/registry.py` `_register_builtin_connectors()`,
  add a guarded import of `agentic_inquiry.connectors.gcs` mirroring the existing
  S3 block (`try: from ...gcs import GCSConnector; except ImportError: debug
  log`).
- In `agentic_inquiry/connectors/gcs.py`, change `_build_uri` to return
  `f"gcs://{path}"` and `_uri_to_path` to strip `"gcs://"` (len 6), matching
  the registered name and docs. **Leave `protocol="gcs"` passed to the fsspec
  base unchanged — this is by design: the fsspec *protocol* (what
  `fsspec.filesystem()` receives; gcsfs accepts `gcs`) and the *URI scheme*
  (cosmetic identifier feeding `item.protocol`) are independent. Do not
  "align" one to the other beyond this scheme change.** Keep the
  `_uri_to_path` override for symmetry with `s3.py` (the base would also
  handle `gcs://`, but S3 carries its own override and we mirror it).
- In `agentic_inquiry/connectors/__init__.py`, add the optional `GCSConnector`
  import (guarded `try/except ImportError → None`, mirroring S3) and add
  `"GCSConnector"` to `__all__`.
- In `agentic_inquiry/connectors/types.py` (`SourceItem` docstring, ~lines 24-28),
  add `- GCS: gcs://bucket/object` to the URI-conventions list (it omits GCS
  today, adjacent to the scheme change).

**Done when:** the RED tests above pass; `ruff`/`mypy` clean;
`uv run python -c "import agentic_inquiry.connectors as c; assert 'gcs' in
c.list_connectors()"` succeeds.

### T2: broader GCS mocked-behavior tests + cloud_smoke pattern

**Depends on:** T1

**Tests:**
- `tests/connectors/test_gcs.py` rounded out to mirror `test_s3.py`'s
  *structural* coverage: creation (basic, prefix, prefix-stripped, custom
  ignore/binary), root path (bucket-only, with-prefix). These are pure
  constructor/string assertions — safe to mirror directly.
- Mocked-fsspec behavior tests that **drive the connector**: inject the mock as
  `connector._fs`, then `await connector.list(...)` and `await
  connector.open(item)` and assert on the yielded `SourceItem` /
  `SourceContent` (uri scheme, hash, decoded text). Do **not** assert on the
  mock object directly (the S3 mock tests do `len(mock_fs.glob(...))`, which
  proves the mock, not the connector — do not replicate that anti-shape).
- A registry-level test asserting that after `import agentic_inquiry.connectors`,
  both `"s3"` and `"gcs"` are present in `list_connectors()` (skip-guarded on
  `s3fs`/`gcsfs` availability).
- `@pytest.mark.cloud_smoke` test for live S3 (gated on `AWS_*` creds /
  `AI_SMOKE_S3_BUCKET`) and live GCS (gated on `GOOGLE_APPLICATION_CREDENTIALS`
  / `AI_SMOKE_GCS_BUCKET`): list at least one object and round-trip its hash.

**Approach:**
- Add a `MockGCSFileSystem` fixture in `tests/connectors/conftest.py` mirroring
  `MockS3FileSystem`; wire it onto `connector._fs` so the async methods run
  against it.
- Place the cloud_smoke tests with `pytest.mark.cloud_smoke` and
  credential-based `skip`/`skipif` (reuse the marker from `tests/conftest.py`).
- Extend the `cloud_smoke` marker description in `tests/conftest.py:75-78` to
  mention S3/GCS object storage (`AI_SMOKE_S3_BUCKET` / `AI_SMOKE_GCS_BUCKET`)
  so the marker's registered docstring covers the new tests, not only the
  AWS/Azure backend smoke tests it lists today.

**Done when:** `uv run --env-file .env pytest tests/connectors/ -q` passes;
`uv run pytest tests/connectors -m cloud_smoke --co -q` collects the smoke
tests; a default run reports them skipped.

### T3: README and connector-guide advertise the supported source matrix

**Depends on:** none

**Tests:** goal-based — `grep -n "s3://\|gcs://\|\[s3\]\|\[gcs\]" README.md`
returns the new section; `grep -n "gs://" docs/development/connector-guide.md`
returns nothing (scheme is `gcs://`).

**Approach:**
- Add a short "Content sources" subsection to `README.md` (near the storage
  backends table) listing filesystem (built-in), S3 (`pip install
  agentic-inquiry[s3]`, `s3://bucket/key`), and GCS (`pip install
  agentic-inquiry[gcs]`, `gcs://bucket/object`).
- Update `docs/development/connector-guide.md` to match the code: the URI
  conventions block already says `gcs://bucket/object` (correct after T1);
  **move `GCSConnector` from "Planned/Example Implementations" to "Active
  Implementations"** (it currently lists only filesystem + S3 as active) so the
  guide reflects that GCS is now first-class.

**Done when:** the two greps above hold and README + connector-guide agree on
the supported matrix and schemes.

### T4: connector test suite is robust to registry resets (discovered)

**Depends on:** none

**Discovered during EXECUTE:** with `s3fs`/`gcsfs` installed (which "first-class"
explicitly encourages), `tests/connectors/test_s3.py::TestS3ConnectorRegistration`
fails because `test_registry.py`'s autouse `reset_registry` fixtures reset the
singleton and never restore built-in registrations — leaking an empty registry
to later test files. This is pre-existing (masked because the cloud libs are
normally absent, so those tests skip) and orthogonal to the GCS fix. My GCS
registration tests avoid it by running in a fresh interpreter.

**Tests:** goal-based — `uv run pytest tests/connectors/ -q` passes with
`s3fs`/`gcsfs` installed (no order-dependent failures).

**Approach:**
- In `tests/connectors/test_registry.py`, change both autouse `reset_registry`
  fixtures to snapshot the registered factories before the reset and restore
  them after, instead of leaving the registry empty. Test-only; no production
  change (the registration mechanism itself is deferred 4.3 work).

**Done when:** the full `tests/connectors/` suite passes both with and without
the cloud extras installed.

## Rollout

Big-bang, fully reversible (additive registration + new test file + docs). No
migration, no flag. GCS was unreachable before, so enabling it cannot regress
any existing GCS user (there are none at runtime today).

## Risks

- **URI scheme change (`gs://` → `gcs://`)**: scoped strictly to
  `connectors/gcs.py`'s `_build_uri`/`_uri_to_path`. `_build_uri` now emits
  `gcs://`; `_uri_to_path` parses **both** `gcs://` and legacy `gs://` so any
  URI persisted before the alignment still resolves (backward-compatible per
  PR review). T1's URI tests pin both. **Note:** `onboard/artifact_storage.py`
  and `docs/mcp/deployment.md` use `gs://` for unrelated GCS-native URIs —
  those are fenced off in the spec's Never-do and must not be renamed. Low.
- **`MockGCSFileSystem` divergence from gcsfs's real API**: mocked tests could
  pass while live behavior differs — mitigated by the `cloud_smoke` tests
  (opt-in) and by mirroring the already-working S3 mock shape. Low.
- **`make bench` perturbation**: connectors don't touch search; bench is a
  sanity check, not expected to move. Low.

## Changelog

- 2026-06-30: initial plan.
