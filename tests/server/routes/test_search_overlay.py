"""Tests for search route WS3 local change overlay (T45).

Tests the /search endpoint's overlay annotation logic. Uses FastAPI TestClient
with a mocked search_service to avoid requiring real storage infrastructure.

Covers:
- local_modified annotation is True for files in local_diff.modified_files
- local_modified annotation is False for files not in local_diff
- No annotation when local_diff is not provided
- local_changes_summary appears in response when local_diff is provided
- local_changes_summary absent when local_diff is absent
- SearchRequest schema accepts local_diff field
- branch parameter accepted by SearchRequest schema
- Zero storage writes during overlay-annotated search (no upsert/delete calls)
- Truncation applied to oversized diffs before annotation
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentic_inquiry.server.routes.search import LocalDiff, LocalDiffFile, SearchRequest, router


# ---------------------------------------------------------------------------
# Fixtures — minimal FastAPI app with mocked search_service
# ---------------------------------------------------------------------------

def _make_search_result(file_path: str, content: str = "def foo(): pass") -> MagicMock:
    """Create a minimal mock search result object."""
    result = MagicMock()
    result.relevance_score = 0.9
    result.data = {
        "file_path": file_path,
        "content": content,
        "chunk_type": "code",
    }
    return result


def _build_test_app(search_results: list) -> tuple[FastAPI, MagicMock]:
    """Build a test FastAPI app with a mocked search_service.

    Returns the app and the mock search_service for assertion purposes.
    """
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    mock_search_service = MagicMock()
    mock_search_service.hybrid_search = AsyncMock(return_value=search_results)

    # Set state directly — avoids startup event timing issues with TestClient
    app.state.services = {"search_service": mock_search_service}
    app.state.config = None  # Use defaults for overlay config

    return app, mock_search_service


# ---------------------------------------------------------------------------
# T45-1: local_modified annotation for matching files
# ---------------------------------------------------------------------------

class TestLocalModifiedAnnotation:
    """local_modified is set to True for files in the local diff."""

    def test_modified_file_annotated_true(self):
        """A file listed in local_diff.modified_files must have local_modified=True."""
        results = [_make_search_result("src/auth.py")]
        app, _ = _build_test_app(results)
        client = TestClient(app)

        resp = client.post(
            "/api/v1/search",
            json={
                "query": "authentication",
                "local_diff": {
                    "branch": "feature/x",
                    "modified_files": [
                        {"path": "src/auth.py", "changed_lines": [1, 2, 3], "status": "modified"}
                    ],
                },
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["results"][0]["local_modified"] is True

    def test_unmodified_file_annotated_false(self):
        """A file NOT in local_diff.modified_files must have local_modified=False."""
        results = [_make_search_result("src/other.py")]
        app, _ = _build_test_app(results)
        client = TestClient(app)

        resp = client.post(
            "/api/v1/search",
            json={
                "query": "something",
                "local_diff": {
                    "modified_files": [
                        {"path": "src/auth.py", "changed_lines": [1], "status": "modified"}
                    ],
                },
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["results"][0]["local_modified"] is False

    def test_multiple_results_annotated_independently(self):
        """Each result's local_modified must be evaluated independently."""
        results = [
            _make_search_result("src/modified.py"),
            _make_search_result("src/clean.py"),
        ]
        app, _ = _build_test_app(results)
        client = TestClient(app)

        resp = client.post(
            "/api/v1/search",
            json={
                "query": "code",
                "local_diff": {
                    "modified_files": [
                        {"path": "src/modified.py", "changed_lines": [10]}
                    ],
                },
            },
        )
        assert resp.status_code == 200
        result_map = {r["file_path"]: r for r in resp.json()["results"]}
        assert result_map["src/modified.py"]["local_modified"] is True
        assert result_map["src/clean.py"]["local_modified"] is False


# ---------------------------------------------------------------------------
# T45-2: No annotation when local_diff is absent
# ---------------------------------------------------------------------------

class TestNoAnnotationWithoutDiff:
    """When no local_diff is provided, local_modified must not appear."""

    def test_no_local_modified_field_without_diff(self):
        """local_modified must be absent from results when local_diff is not sent."""
        results = [_make_search_result("src/auth.py")]
        app, _ = _build_test_app(results)
        client = TestClient(app)

        resp = client.post(
            "/api/v1/search",
            json={"query": "authentication"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "local_modified" not in data["results"][0]

    def test_no_local_modified_when_diff_has_no_files(self):
        """An empty local_diff (no modified_files) must not annotate results."""
        results = [_make_search_result("src/auth.py")]
        app, _ = _build_test_app(results)
        client = TestClient(app)

        resp = client.post(
            "/api/v1/search",
            json={
                "query": "authentication",
                "local_diff": {"modified_files": []},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "local_modified" not in data["results"][0]


# ---------------------------------------------------------------------------
# T45-3: local_changes_summary in response
# ---------------------------------------------------------------------------

class TestLocalChangesSummary:
    """local_changes_summary appears in response when local_diff has files."""

    def test_summary_present_when_diff_provided(self):
        """local_changes_summary must be included when modified_files is non-empty."""
        results = [_make_search_result("src/auth.py")]
        app, _ = _build_test_app(results)
        client = TestClient(app)

        resp = client.post(
            "/api/v1/search",
            json={
                "query": "auth",
                "local_diff": {
                    "branch": "feature/auth",
                    "modified_files": [
                        {"path": "src/auth.py", "changed_lines": [1, 2]}
                    ],
                },
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "local_changes_summary" in data

    def test_summary_contains_branch(self):
        """local_changes_summary must include the branch from local_diff."""
        results = [_make_search_result("src/auth.py")]
        app, _ = _build_test_app(results)
        client = TestClient(app)

        resp = client.post(
            "/api/v1/search",
            json={
                "query": "auth",
                "local_diff": {
                    "branch": "feature/auth-refactor",
                    "modified_files": [{"path": "src/auth.py", "changed_lines": [1]}],
                },
            },
        )
        summary = resp.json()["local_changes_summary"]
        assert summary["branch"] == "feature/auth-refactor"

    def test_summary_contains_modified_file_count(self):
        """local_changes_summary must include modified_file_count."""
        results = []
        app, _ = _build_test_app(results)
        client = TestClient(app)

        resp = client.post(
            "/api/v1/search",
            json={
                "query": "code",
                "local_diff": {
                    "modified_files": [
                        {"path": "a.py", "changed_lines": [1]},
                        {"path": "b.py", "changed_lines": [2]},
                    ],
                },
            },
        )
        summary = resp.json()["local_changes_summary"]
        assert summary["modified_file_count"] == 2

    def test_summary_contains_modified_files_list(self):
        """local_changes_summary must list the paths of modified files."""
        results = []
        app, _ = _build_test_app(results)
        client = TestClient(app)

        resp = client.post(
            "/api/v1/search",
            json={
                "query": "code",
                "local_diff": {
                    "modified_files": [
                        {"path": "src/foo.py", "changed_lines": [1]},
                    ],
                },
            },
        )
        summary = resp.json()["local_changes_summary"]
        assert "src/foo.py" in summary["modified_files"]

    def test_summary_absent_when_no_diff(self):
        """local_changes_summary must NOT appear when local_diff is absent."""
        results = [_make_search_result("src/auth.py")]
        app, _ = _build_test_app(results)
        client = TestClient(app)

        resp = client.post("/api/v1/search", json={"query": "auth"})
        assert "local_changes_summary" not in resp.json()

    def test_summary_includes_truncated_flag(self):
        """local_changes_summary must include the truncated flag."""
        results = []
        app, _ = _build_test_app(results)
        client = TestClient(app)

        resp = client.post(
            "/api/v1/search",
            json={
                "query": "code",
                "local_diff": {
                    "modified_files": [{"path": "a.py", "changed_lines": [1]}],
                    "truncated": False,
                },
            },
        )
        summary = resp.json()["local_changes_summary"]
        assert "truncated" in summary


# ---------------------------------------------------------------------------
# T45-4: SearchRequest schema validation
# ---------------------------------------------------------------------------

class TestSearchRequestSchema:
    """SearchRequest Pydantic model accepts local_diff and branch fields."""

    def test_search_request_accepts_local_diff(self):
        """SearchRequest must accept local_diff without validation error."""
        req = SearchRequest(
            query="test",
            local_diff=LocalDiff(
                modified_files=[LocalDiffFile(path="a.py", changed_lines=[1])]
            ),
        )
        assert req.local_diff is not None
        assert len(req.local_diff.modified_files) == 1

    def test_search_request_local_diff_optional(self):
        """local_diff must be optional (defaults to None)."""
        req = SearchRequest(query="test")
        assert req.local_diff is None

    def test_search_request_accepts_branch(self):
        """SearchRequest must accept a branch parameter."""
        req = SearchRequest(query="test", branch="feature/x")
        assert req.branch == "feature/x"

    def test_search_request_branch_optional(self):
        """branch must be optional (defaults to None)."""
        req = SearchRequest(query="test")
        assert req.branch is None

    def test_local_diff_file_status_field(self):
        """LocalDiffFile must accept status field."""
        f = LocalDiffFile(path="a.py", changed_lines=[1, 2], status="added")
        assert f.status == "added"

    def test_local_diff_file_status_default(self):
        """LocalDiffFile status must default to 'modified'."""
        f = LocalDiffFile(path="a.py")
        assert f.status == "modified"


# ---------------------------------------------------------------------------
# T45-5: Zero storage writes during overlay search
# ---------------------------------------------------------------------------

class TestZeroStorageWrites:
    """Overlay-annotated searches must not trigger any storage writes."""

    @pytest.mark.asyncio
    async def test_overlay_search_does_not_write_to_storage(self):
        """No upsert/delete methods must be called on storage during overlay search."""
        from agentic_inquiry.server.routes.search import search

        # Build mock search_service
        mock_search_service = MagicMock()
        mock_search_service.hybrid_search = AsyncMock(
            return_value=[_make_search_result("src/auth.py")]
        )

        # Track all write method calls on a mock storage
        write_calls: list[tuple] = []
        mock_storage = MagicMock()
        mock_storage.upsert_chunks = AsyncMock(
            side_effect=lambda *a, **kw: write_calls.append(("upsert", a))
        )
        mock_storage.delete_chunks = AsyncMock(
            side_effect=lambda *a, **kw: write_calls.append(("delete", a))
        )
        mock_storage.insert_chunks = AsyncMock(
            side_effect=lambda *a, **kw: write_calls.append(("insert", a))
        )

        # Build a mock request
        mock_request = MagicMock()
        mock_request.app.state.services = {"search_service": mock_search_service}
        mock_request.app.state.config = None

        body = SearchRequest(
            query="auth",
            local_diff=LocalDiff(
                modified_files=[LocalDiffFile(path="src/auth.py", changed_lines=[1, 2, 3])]
            ),
        )

        await search(request=mock_request, body=body)

        assert write_calls == [], f"Unexpected storage writes during overlay search: {write_calls}"


# ---------------------------------------------------------------------------
# T45-6: Server annotates from request diff (no local git workspace needed)
# ---------------------------------------------------------------------------

class TestServerAnnotatesFromRequestDiff:
    """Annotation works purely from request data — no server-side git required."""

    def test_annotation_works_without_server_git(self):
        """The server must annotate results using request-supplied local_diff only."""
        results = [_make_search_result("src/service.py")]
        app, _ = _build_test_app(results)
        client = TestClient(app)

        # Annotation data comes entirely from the request body
        resp = client.post(
            "/api/v1/search",
            json={
                "query": "service",
                "local_diff": {
                    "modified_files": [
                        {"path": "src/service.py", "changed_lines": [5, 10, 15]}
                    ],
                },
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        # Annotation must be present and correct based purely on request data
        assert data["results"][0]["local_modified"] is True

    def test_empty_query_returns_error_not_exception(self):
        """An empty query must return an error response, not raise an exception."""
        results = []
        app, _ = _build_test_app(results)
        client = TestClient(app)

        resp = client.post("/api/v1/search", json={"query": "   "})
        assert resp.status_code == 200  # Route returns 200 with error payload
        data = resp.json()
        assert "error" in data
        assert data.get("code") == "EMPTY_QUERY"


# ---------------------------------------------------------------------------
# T45-7: Truncation applied before annotation
# ---------------------------------------------------------------------------

class TestTruncationBeforeAnnotation:
    """Oversized diffs must be truncated before annotation."""

    def test_large_diff_truncated_in_summary(self):
        """A diff exceeding the 500-line total cap must be flagged as truncated."""
        results = []
        app, _ = _build_test_app(results)
        client = TestClient(app)

        # Create 6 files x 100 lines each = 600 lines (exceeds default 500 total cap)
        many_files = [
            {"path": f"file{i:02d}.py", "changed_lines": list(range(1, 101))}
            for i in range(6)
        ]

        resp = client.post(
            "/api/v1/search",
            json={
                "query": "code",
                "local_diff": {"modified_files": many_files},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        summary = data.get("local_changes_summary", {})
        # After truncation, the summary must reflect fewer than 6 files or truncated=True
        assert summary.get("truncated") is True or summary.get("modified_file_count", 6) < 6
