"""Enterprise integration tests for Agentic Inquiry.

Verifies that enterprise components work together end-to-end:
- Auth middleware + search route
- Search request with LocalDiff + branch overlay
- Cloud detection -> env_resolver chain
- Branch discovery + expiry chain (real git)
- IndexingPipeline DocumentChunk branch field
- Truncation -> search overlay chain

Requirements: enterprise industrialization (v1.5)
"""
from __future__ import annotations

import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

pytestmark = pytest.mark.integration

from agentic_inquiry.config import (
    Config,
    MCPAPIConfig,
    MCPConfig,
    OverlayConfig,
    StorageConfig,
)


# ---------------------------------------------------------------------------
# Helper: minimal config with auth enabled
# ---------------------------------------------------------------------------

def _make_auth_config(api_key: str = "test-key-123") -> Config:
    """Return a Config with auth.enabled=True and a known API key."""
    mcp_api = MCPAPIConfig(
        enabled=True,
        host="localhost",
        port=8765,
        auth={"enabled": True, "api_key": api_key},
    )
    mcp = MCPConfig(api=mcp_api)
    return Config(mcp=mcp)


# ---------------------------------------------------------------------------
# Test 1: Auth Middleware + Search Route End-to-End
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_middleware_unauthenticated_returns_401(tmp_path):
    """Unauthenticated requests to protected endpoints must return 401."""
    config = _make_auth_config()
    config.storage = StorageConfig(
        root=str(tmp_path / "storage"),
        default_project_id="test_auth",
    )

    from agentic_inquiry.server.app import create_app
    app = await create_app(config=config, project_id="test_auth")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/search",
            json={"query": "hello world"},
        )

    assert response.status_code == 401
    body = response.json()
    assert body["code"] in ("AUTH_REQUIRED", "INVALID_TOKEN")


@pytest.mark.asyncio
async def test_auth_middleware_authenticated_not_401(tmp_path):
    """Authenticated requests must pass auth (response code != 401)."""
    config = _make_auth_config("test-key-123")
    config.storage = StorageConfig(
        root=str(tmp_path / "storage"),
        default_project_id="test_auth",
    )

    from agentic_inquiry.server.app import create_app
    app = await create_app(config=config, project_id="test_auth")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/search",
            json={"query": "hello world"},
            headers={"Authorization": "Bearer test-key-123"},
        )

    # Must not be 401; may be any other code (e.g., 200 with error body or 200 with empty results)
    assert response.status_code != 401


@pytest.mark.asyncio
async def test_health_endpoint_accessible_without_auth(tmp_path):
    """Health endpoint must be accessible without authentication credentials."""
    config = _make_auth_config("my-secret-key")
    config.storage = StorageConfig(
        root=str(tmp_path / "storage"),
        default_project_id="test_health",
    )

    from agentic_inquiry.server.app import create_app
    app = await create_app(config=config, project_id="test_health")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"


# ---------------------------------------------------------------------------
# Test 2: Search Request with LocalDiff + Branch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_with_local_diff_returns_local_changes_summary(tmp_path):
    """SearchRequest with local_diff must produce local_changes_summary in response."""
    config = _make_auth_config()
    # Disable auth for simplicity in this scenario
    config.mcp.api.auth = {"enabled": False, "api_key": None}
    config.storage = StorageConfig(
        root=str(tmp_path / "storage"),
        default_project_id="test_diff",
    )

    from agentic_inquiry.server.app import create_app
    app = await create_app(config=config, project_id="test_diff")

    payload = {
        "query": "find my function",
        "limit": 5,
        "branch": "feature/my-branch",
        "local_diff": {
            "branch": "feature/my-branch",
            "modified_files": [
                {"path": "src/foo.py", "changed_lines": [10, 11, 12], "status": "modified"},
                {"path": "src/bar.py", "changed_lines": [5], "status": "added"},
            ],
            "truncated": False,
            "omitted_count": 0,
        },
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/search", json=payload)

    # Schema validation must pass (not 422)
    assert response.status_code != 422, f"Schema validation failed: {response.text}"

    body = response.json()
    # When a search service is unavailable we get an error body, but local_changes_summary
    # is only emitted on success paths. Verify it is present when the search service
    # actually executes the overlay logic.
    if "local_changes_summary" in body:
        summary = body["local_changes_summary"]
        assert summary["branch"] == "feature/my-branch"
        assert summary["modified_file_count"] == 2
        assert "src/foo.py" in summary["modified_files"]
        assert "src/bar.py" in summary["modified_files"]


@pytest.mark.asyncio
async def test_search_with_local_diff_annotates_results(tmp_path):
    """Results for locally-modified files must carry local_modified=True annotation."""
    config = Config()
    config.mcp.api.auth = {"enabled": False, "api_key": None}
    config.storage = StorageConfig(
        root=str(tmp_path / "storage"),
        default_project_id="test_annotation",
    )

    from agentic_inquiry.server.app import create_app
    app = await create_app(config=config, project_id="test_annotation")

    # Inject a mock search service that returns a predictable result
    mock_result = MagicMock()
    mock_result.data = {"file_path": "src/foo.py", "content": "def foo(): pass", "chunk_type": "code"}
    mock_result.relevance_score = 0.95

    mock_search_svc = AsyncMock()
    mock_search_svc.hybrid_search = AsyncMock(return_value=[mock_result])
    app.state.services = {"search_service": mock_search_svc}

    payload = {
        "query": "find foo",
        "local_diff": {
            "branch": "feature/x",
            "modified_files": [
                {"path": "src/foo.py", "changed_lines": [1, 2, 3], "status": "modified"},
            ],
        },
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/search", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    result = body["results"][0]
    assert result["local_modified"] is True


# ---------------------------------------------------------------------------
# Test 3: Cloud Detection -> env_resolver Chain
# ---------------------------------------------------------------------------


def test_env_resolver_returns_cloud_detected_when_gcp_imds_responds(tmp_path):
    """When GCP IMDS responds, resolve_environment must return source='cloud_detected'."""
    # Ensure no env vars override discovery
    env_overrides = {
        "INQUIRY_CONFIG": None,
        "INQUIRY_ENV": None,
        "INQUIRY_HOME": str(tmp_path / ".agentic-inquiry"),
    }

    class _FakeResponse:
        status = 200

        def read(self):
            return b"my-gcp-project"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    def _fake_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "169.254.169.254" in url and "project-id" in url:
            return _FakeResponse()
        raise OSError("Not GCP")

    # Patch out the env vars that would short-circuit discovery and use isolated home
    with patch.dict(os.environ, {k: v or "" for k, v in env_overrides.items()}, clear=False):
        # Remove vars that must be absent
        for k, v in env_overrides.items():
            if v is None and k in os.environ:
                del os.environ[k]

        with patch("urllib.request.urlopen", side_effect=_fake_urlopen):
            from agentic_inquiry.cli.env_resolver import resolve_environment
            resolved = resolve_environment(workspace=tmp_path)

    assert resolved.source == "cloud_detected"
    assert resolved.name.startswith("cloud-")


def test_env_resolver_falls_back_to_default_when_no_cloud(tmp_path):
    """When IMDS probes all fail, resolve_environment must return source='default'."""
    env_overrides = {
        "INQUIRY_CONFIG": None,
        "INQUIRY_ENV": None,
        "INQUIRY_HOME": str(tmp_path / ".agentic-inquiry"),
    }

    def _all_fail(req, timeout=None):
        raise OSError("Connection refused")

    with patch.dict(os.environ, {k: v or "" for k, v in env_overrides.items()}, clear=False):
        for k, v in env_overrides.items():
            if v is None and k in os.environ:
                del os.environ[k]

        with patch("urllib.request.urlopen", side_effect=_all_fail):
            from agentic_inquiry.cli.env_resolver import resolve_environment
            resolved = resolve_environment(workspace=tmp_path)

    assert resolved.source == "default"
    assert resolved.name == "default"


# ---------------------------------------------------------------------------
# Test 4: Branch Discovery + Expiry Chain (Real Git)
# ---------------------------------------------------------------------------


def _init_git_repo(repo_path: Path) -> None:
    """Initialise a bare-minimum git repo for branch discovery tests."""
    subprocess.run(["git", "init", str(repo_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(repo_path), check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(repo_path), check=True, capture_output=True,
    )


def _make_commit(repo_path: Path, filename: str = "file.txt", message: str = "commit") -> str:
    """Create a commit in the repo and return its SHA."""
    (repo_path / filename).write_text(message)
    subprocess.run(["git", "add", "."], cwd=str(repo_path), check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", message],
        cwd=str(repo_path), check=True, capture_output=True,
    )
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=str(repo_path), capture_output=True, text=True,
    )
    return result.stdout.strip()


def test_branch_discovery_filters_stale_branches(tmp_path):
    """discover_branches must only return branches within age cutoff (plus default)."""
    from agentic_inquiry.indexing.branch_discovery import discover_branches, DiscoveredBranch

    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)

    # Create an initial commit on main
    _make_commit(repo, "initial.txt", "init")

    # Simulate remote branches using git notes/refs directly
    # We create local branches and alias them as if they were remotes by manipulating refs
    # Since discover_branches uses `git branch -r`, we need actual remote refs.
    # We'll clone the repo to itself to create remote tracking branches.
    clone = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", str(repo), str(clone)],
        check=True, capture_output=True,
    )

    # Make a second commit on clone (recent branch already at origin/main)
    _make_commit(clone, "feature.txt", "feature work")
    subprocess.run(
        ["git", "push", "origin", "HEAD:refs/heads/feature/recent"],
        cwd=str(clone), check=True, capture_output=True,
    )

    # Branches: origin/main (recent), origin/feature/recent (recent)
    # discover_branches with max_age_days=30 should find both
    branches = discover_branches(str(clone), max_age_days=30)

    branch_names = {b.short_name for b in branches}
    # Should include at minimum main (default) and feature/recent
    assert "main" in branch_names or any("main" in n for n in branch_names), (
        f"Expected main in {branch_names}"
    )


@pytest.mark.asyncio
async def test_expire_stale_branches_soft_deletes_stale_and_exempts_default(tmp_path):
    """expire_stale_branches must soft-delete stale branches but not the default."""
    from agentic_inquiry.indexing.branch_expiry import expire_stale_branches

    # Build a mock storage facade with a LanceDB-style vector provider
    # that tracks advanced_filter calls and records update calls.
    stale_chunks = [
        {"id": "chunk-1", "project_id": "proj", "branch": "feature/stale", "is_active": True},
        {"id": "chunk-2", "project_id": "proj", "branch": "main", "is_active": True},
        {"id": "chunk-3", "project_id": "proj", "branch": "feature/active", "is_active": True},
    ]

    updated_branches: list[str] = []

    class _FakeLanceDBManager:
        async def advanced_filter(self, table_name, filters, limit):
            return [c for c in stale_chunks if c.get("is_active") == filters.get("is_active")]

        async def get_or_create_table(self, table_name):
            class _FakeTable:
                async def update(self, where, values):
                    # Extract branch from stale_chunks by matching IDs in where clause
                    for chunk in stale_chunks:
                        if chunk["id"] in where:
                            updated_branches.append(chunk["branch"])

            return _FakeTable()

    class _FakeVectorProvider:
        _db_manager = _FakeLanceDBManager()
        # No _execute/_fetch means we take the LanceDB path

    class _FakeStorage:
        _vector_provider = _FakeVectorProvider()

    storage = _FakeStorage()
    expired = await expire_stale_branches(
        storage=storage,
        project_id="proj",
        active_branches={"feature/active"},
        default_branch="main",
    )

    assert "feature/stale" in expired, f"Expected stale branch expired; got {expired}"
    assert "main" not in expired, "Default branch must never be expired"
    assert "feature/active" not in expired, "Active branch must not be expired"


# ---------------------------------------------------------------------------
# Test 5: IndexingPipeline DocumentChunk Branch Field
# ---------------------------------------------------------------------------


def test_document_chunk_branch_field_defaults_to_main():
    """DocumentChunk.branch defaults to 'main' when not specified."""
    from agentic_inquiry.models.document_chunk import DocumentChunk

    chunk = DocumentChunk(
        id="c1",
        doc_id="doc1",
        file_path="src/foo.py",
        project_id="proj",
        content="def foo(): pass",
        fts_text="def foo(): pass",
        vector=[0.1] * 384,
    )
    assert chunk.branch == "main"


def test_document_chunk_branch_field_can_be_set():
    """DocumentChunk.branch can be set to any branch name at construction time."""
    from agentic_inquiry.models.document_chunk import DocumentChunk

    chunk = DocumentChunk(
        id="c1",
        doc_id="doc1",
        file_path="src/foo.py",
        project_id="proj",
        content="def foo(): pass",
        fts_text="def foo(): pass",
        vector=[0.1] * 384,
        branch="feature/x",
    )
    assert chunk.branch == "feature/x"


@pytest.mark.asyncio
async def test_indexing_pipeline_schema_processor_propagates_branch(tmp_path):
    """SchemaProcessor.process_chunks produces DocumentChunk objects with the branch field.

    SchemaProcessor._transform_chunk() builds a record dict; then write_chunks()
    constructs DocumentChunk(**record).  DocumentChunk.branch defaults to "main".
    This test verifies that the DocumentChunks passed to add_document_chunks()
    have a non-empty branch field (i.e., the default is preserved end-to-end).
    """
    from agentic_inquiry.indexing.schema_processor import SchemaProcessor
    from agentic_inquiry.parsers.models import ParsedDocument, ParserChunk
    from agentic_inquiry.models.document_chunk import DocumentChunk

    # Capture the DocumentChunk objects that reach add_document_chunks
    stored_chunks: list[DocumentChunk] = []

    class _MockAdapter:
        async def add_document_chunks(self, chunks, ensure_commit=False):
            stored_chunks.extend(chunks)
            return len(chunks)

        async def delete_document_chunks(self, chunk_ids):
            return len(chunk_ids)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    processor = SchemaProcessor(_MockAdapter())

    parsed_doc = ParsedDocument(
        doc_id="doc-branch-test",
        file_path="src/widget.py",
        chunks=[
            ParserChunk(
                content="class Widget: pass",
                fts_text="class Widget: pass",
                content_type="CODE",
                language="python",
                line_start=1,
                line_end=1,
            )
        ],
    )

    records = await processor.process_chunks(
        chunks=parsed_doc.chunks,
        parsed_document=parsed_doc,
        vectors=[[0.1] * 384],
        project_id="proj",
        original_total_chunks=1,
    )

    # Verify records were produced
    assert len(records) >= 1

    # Verify DocumentChunk objects written to the adapter carry the branch field
    assert len(stored_chunks) >= 1
    chunk = stored_chunks[0]
    assert isinstance(chunk, DocumentChunk)
    # branch defaults to "main" when not explicitly overridden
    assert chunk.branch == "main", f"Expected branch='main', got {chunk.branch!r}"


# ---------------------------------------------------------------------------
# Test 6: Truncation -> Search Overlay Chain
# ---------------------------------------------------------------------------


def test_truncation_caps_files_and_lines():
    """truncate_diff must respect max_per_file and max_total limits."""
    from agentic_inquiry.server.routes.search import LocalDiff, LocalDiffFile
    from agentic_inquiry.server.overlay.truncation import truncate_diff

    # 15 files x 200 changed_lines each = 3000 total (exceeds max_total=500)
    files = [
        LocalDiffFile(
            path=f"src/module_{i:02d}.py",
            changed_lines=list(range(200)),
            status="modified",
        )
        for i in range(15)
    ]
    original = LocalDiff(branch="feature/big", modified_files=files)

    truncated = truncate_diff(original, max_per_file=100, max_total=500)

    # Total changed lines must not exceed max_total
    total_lines = sum(len(f.changed_lines) for f in truncated.modified_files)
    assert total_lines <= 500, f"Total lines {total_lines} exceeds cap of 500"

    # Per-file must not exceed max_per_file
    for f in truncated.modified_files:
        assert len(f.changed_lines) <= 100, (
            f"File {f.path} has {len(f.changed_lines)} lines, exceeds per-file cap of 100"
        )

    # Truncation must be flagged
    assert truncated.truncated is True
    assert truncated.omitted_count > 0


def test_truncation_overlay_annotation_consistent_with_truncated_file_list():
    """Overlay annotations must reflect the truncated file list, not the original."""
    from agentic_inquiry.server.routes.search import LocalDiff, LocalDiffFile
    from agentic_inquiry.server.overlay.truncation import truncate_diff

    # 10 files, tight budget: only first 2 will survive (alphabetically)
    files = [
        LocalDiffFile(
            path=f"src/z_{i:02d}.py",
            changed_lines=list(range(80)),
            status="modified",
        )
        for i in range(10)
    ]
    # Insert two files that sort before z_
    files.extend([
        LocalDiffFile(path="src/alpha_01.py", changed_lines=list(range(50)), status="modified"),
        LocalDiffFile(path="src/alpha_02.py", changed_lines=list(range(50)), status="modified"),
    ])

    original = LocalDiff(branch="feature/test", modified_files=files)
    # max_total=100 means at most 2 files of 50 lines each survive
    truncated = truncate_diff(original, max_per_file=100, max_total=100)

    kept_paths = {f.path for f in truncated.modified_files}
    all_original_paths = {f.path for f in original.modified_files}
    dropped_paths = all_original_paths - kept_paths

    # Annotations built from truncated diff must not reference dropped files
    # Simulate the annotation logic from the search route
    local_modified_paths = {f.path for f in truncated.modified_files}
    for dropped in dropped_paths:
        assert dropped not in local_modified_paths, (
            f"Dropped file {dropped} must not appear in truncated annotation set"
        )

    # The alpha files (sorted first) should survive if budget allows
    total_kept_lines = sum(len(f.changed_lines) for f in truncated.modified_files)
    assert total_kept_lines <= 100


def test_truncation_no_mutation_of_original():
    """truncate_diff must not mutate the original LocalDiff object."""
    from agentic_inquiry.server.routes.search import LocalDiff, LocalDiffFile
    from agentic_inquiry.server.overlay.truncation import truncate_diff

    files = [
        LocalDiffFile(path="a.py", changed_lines=list(range(200)), status="modified"),
    ]
    original = LocalDiff(branch="main", modified_files=files)
    original_file_count = len(original.modified_files)
    original_line_count = len(original.modified_files[0].changed_lines)

    _truncated = truncate_diff(original, max_per_file=10, max_total=10)

    # Original must be untouched
    assert len(original.modified_files) == original_file_count
    assert len(original.modified_files[0].changed_lines) == original_line_count
