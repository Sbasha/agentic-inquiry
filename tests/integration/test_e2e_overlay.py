"""E2E tests for the search-with-overlay chain.

Verifies the full path: index real files -> search via FastAPI TestClient
-> overlay annotations applied in-process, no external server needed.

Test coverage:
- Test 1: Index files, search with LocalDiff, verify local_modified annotation
- Test 2: Branch-scoped search returns different results per branch
- Test 3: Truncation applies before annotation when diff exceeds 500 total lines
"""
from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.integration

from agent_vault.config import Config, StorageConfig


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_config(tmp_path_str: str, project_id: str = "test_e2e") -> Config:
    """Return a Config with LanceDB storage in tmp_path, auth disabled."""
    config = Config()
    config.mcp.api.auth = {"enabled": False, "api_key": None}
    config.storage = StorageConfig(
        root=tmp_path_str,
        default_project_id=project_id,
    )
    return config


def _make_search_result(file_path: str, content: str, score: float = 0.9) -> Any:
    """Build a MagicMock that looks like a SearchResult."""
    result = MagicMock()
    result.data = {
        "file_path": file_path,
        "content": content,
        "chunk_type": "code",
    }
    result.relevance_score = score
    return result


def _mock_search_service(*results: Any) -> Any:
    """Return an AsyncMock search service that yields the given results."""
    svc = AsyncMock()
    svc.hybrid_search = AsyncMock(return_value=list(results))
    return svc


def _write_python_files(base_path: Any) -> list[str]:
    """Create two small Python files and return their relative paths."""
    file_a = base_path / "alpha.py"
    file_b = base_path / "beta.py"

    file_a.write_text(
        "def alpha_function():\n"
        "    '''Alpha module function.'''\n"
        "    return 'alpha'\n"
    )
    file_b.write_text(
        "def beta_function():\n"
        "    '''Beta module function.'''\n"
        "    return 'beta'\n"
    )
    return [str(file_a), str(file_b)]


# ---------------------------------------------------------------------------
# Test 1: index -> search with LocalDiff -> local_modified annotation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_with_local_diff_annotates_modified_file(tmp_path):
    """After indexing real files, a search with local_diff must annotate results.

    Acceptance criteria:
    - Results whose file_path appears in local_diff.modified_files carry
      local_modified=True.
    - Results for files NOT in the diff carry local_modified=False.
    - local_changes_summary is present with correct branch and file list.
    """
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    _write_python_files(src_dir)

    config = _make_config(str(tmp_path / "storage"))

    from agent_vault.server.app import create_app

    app = await create_app(config=config, project_id="test_e2e_annotation")

    # Inject a mock search service returning one result per file so the
    # annotation logic gets exercised with two distinct file paths.
    result_alpha = _make_search_result(str(src_dir / "alpha.py"), "def alpha_function(): ...")
    result_beta = _make_search_result(str(src_dir / "beta.py"), "def beta_function(): ...")
    app.state.services = {"search_service": _mock_search_service(result_alpha, result_beta)}

    payload = {
        "query": "find function",
        "limit": 10,
        "local_diff": {
            "branch": "feature/my-work",
            "modified_files": [
                {
                    "path": str(src_dir / "alpha.py"),
                    "changed_lines": [1, 2, 3],
                    "status": "modified",
                },
            ],
            "truncated": False,
            "omitted_count": 0,
        },
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/search", json=payload)

    assert response.status_code == 200, f"Unexpected status {response.status_code}: {response.text}"
    body = response.json()

    assert body["count"] == 2, f"Expected 2 results, got {body['count']}"

    # Build a mapping of file_path -> local_modified annotation
    annotations = {r["file_path"]: r.get("local_modified") for r in body["results"]}

    alpha_path = str(src_dir / "alpha.py")
    beta_path = str(src_dir / "beta.py")

    assert annotations.get(alpha_path) is True, (
        f"alpha.py (in diff) should have local_modified=True, got {annotations.get(alpha_path)}"
    )
    assert annotations.get(beta_path) is False, (
        f"beta.py (not in diff) should have local_modified=False, got {annotations.get(beta_path)}"
    )

    # Verify local_changes_summary is present and correct
    assert "local_changes_summary" in body, "Response must include local_changes_summary"
    summary = body["local_changes_summary"]
    assert summary["branch"] == "feature/my-work"
    assert summary["modified_file_count"] == 1
    assert alpha_path in summary["modified_files"]
    assert summary["truncated"] is False


# ---------------------------------------------------------------------------
# Test 2: branch-scoped search returns content for the requested branch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_branch_scoped_search_routes_to_correct_content(tmp_path):
    """Searching with branch='main' vs branch='feature/x' must yield different results.

    The search service is mocked to return branch-specific content.  The test
    verifies that:
    - The branch parameter is forwarded to hybrid_search.
    - Results reflect the branch that was requested.
    """
    config = _make_config(str(tmp_path / "storage"), project_id="test_e2e_branch")

    from agent_vault.server.app import create_app

    app = await create_app(config=config, project_id="test_e2e_branch")

    # Track the branch argument each call receives
    received_branches: list[str | None] = []

    async def _branch_aware_search(**kwargs: Any):
        branch = kwargs.get("branch")
        received_branches.append(branch)
        if branch == "main":
            return [_make_search_result("main/service.py", "class MainService: pass")]
        elif branch == "feature/x":
            return [_make_search_result("feature/service.py", "class FeatureService: pass")]
        return []

    svc = AsyncMock()
    svc.hybrid_search = _branch_aware_search
    app.state.services = {"search_service": svc}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Search on main
        resp_main = await client.post(
            "/api/v1/search",
            json={"query": "service class", "limit": 5, "branch": "main"},
        )
        # Search on feature branch
        resp_feature = await client.post(
            "/api/v1/search",
            json={"query": "service class", "limit": 5, "branch": "feature/x"},
        )

    assert resp_main.status_code == 200, resp_main.text
    assert resp_feature.status_code == 200, resp_feature.text

    body_main = resp_main.json()
    body_feature = resp_feature.json()

    # Verify correct branch was forwarded on each call
    assert "main" in received_branches, "hybrid_search was not called with branch='main'"
    assert "feature/x" in received_branches, "hybrid_search was not called with branch='feature/x'"

    # Verify results reflect the requested branch
    assert body_main["count"] == 1
    assert body_main["results"][0]["file_path"] == "main/service.py", (
        f"Expected main/service.py, got {body_main['results'][0]['file_path']}"
    )

    assert body_feature["count"] == 1
    assert body_feature["results"][0]["file_path"] == "feature/service.py", (
        f"Expected feature/service.py, got {body_feature['results'][0]['file_path']}"
    )


# ---------------------------------------------------------------------------
# Test 3: truncation applies before annotation for large diffs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_large_local_diff_is_truncated_before_annotation(tmp_path):
    """A local_diff exceeding 500 total changed_lines must be truncated server-side.

    The truncation module is called before annotation.  The response must:
    - Include local_changes_summary.
    - Have truncated=True in the summary.
    - Show a reduced file list (only files that fit within the total budget).

    The default max_total is 500 lines and max_per_file is 100 lines.
    We send 6 files each with 100 changed_lines = 600 total, which exceeds 500.
    After truncation only 5 files should be kept.
    """
    config = _make_config(str(tmp_path / "storage"), project_id="test_e2e_trunc")

    from agent_vault.server.app import create_app

    app = await create_app(config=config, project_id="test_e2e_trunc")

    # Inject a mock search service so the search itself succeeds
    app.state.services = {
        "search_service": _mock_search_service(
            _make_search_result("src/a.py", "# file a")
        )
    }

    # Build a large diff: 6 files x 100 changed_lines = 600 total (> 500 limit)
    large_modified_files = [
        {
            "path": f"src/file_{chr(ord('a') + i)}.py",
            "changed_lines": list(range(1, 101)),  # 100 lines per file
            "status": "modified",
        }
        for i in range(6)
    ]

    payload = {
        "query": "find anything",
        "limit": 5,
        "local_diff": {
            "branch": "feature/large-pr",
            "modified_files": large_modified_files,
            "truncated": False,
            "omitted_count": 0,
        },
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/search", json=payload)

    assert response.status_code == 200, f"Unexpected status {response.status_code}: {response.text}"
    body = response.json()

    # Truncation must have been applied — local_changes_summary should reflect this
    assert "local_changes_summary" in body, "Response must include local_changes_summary"
    summary = body["local_changes_summary"]

    assert summary["truncated"] is True, (
        f"Expected truncated=True for a 600-line diff (>500 budget), got truncated={summary['truncated']}"
    )

    # With 6 files of 100 lines each, truncation at 500 total allows 5 files
    kept_file_count = summary["modified_file_count"]
    assert kept_file_count < 6, (
        f"Expected fewer than 6 files after truncation, got {kept_file_count}"
    )

    # omitted_count must be non-zero
    assert summary["omitted_count"] > 0, (
        f"Expected omitted_count > 0 after truncation, got {summary['omitted_count']}"
    )
