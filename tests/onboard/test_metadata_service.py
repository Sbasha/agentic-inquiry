"""Tests for onboard metadata service and SQLite provider."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agentic_inquiry.onboard.models import OnboardRun
from agentic_inquiry.onboard.providers.sqlite import SQLiteOnboardMetadataProvider
from agentic_inquiry.onboard.metadata_service import OnboardMetadataService


@pytest.fixture
async def provider(tmp_path: Path) -> SQLiteOnboardMetadataProvider:
    """Create and initialize a test SQLite provider."""
    db_path = tmp_path / "test_onboard.db"
    p = SQLiteOnboardMetadataProvider(db_path=db_path, project_id="test")
    await p.initialize()
    yield p
    await p.close()


@pytest.fixture
async def service(provider: SQLiteOnboardMetadataProvider) -> OnboardMetadataService:
    """Create a metadata service wrapping the test provider."""
    return OnboardMetadataService(provider=provider, project_id="test-project")


class TestSQLiteProvider:
    """Tests for SQLiteOnboardMetadataProvider."""

    async def test_create_and_get_run(self, provider: SQLiteOnboardMetadataProvider) -> None:
        run = OnboardRun(
            run_id=str(uuid.uuid4()),
            project_id="test-project",
            timestamp=datetime.now(timezone.utc),
            status="pending",
            artifact_path="/tmp/test",
        )
        await provider.create_run(run)

        fetched = await provider.get_run(run.run_id)
        assert fetched is not None
        assert fetched.run_id == run.run_id
        assert fetched.project_id == "test-project"
        assert fetched.status == "pending"

    async def test_update_run(self, provider: SQLiteOnboardMetadataProvider) -> None:
        run = OnboardRun(
            run_id=str(uuid.uuid4()),
            project_id="test-project",
            timestamp=datetime.now(timezone.utc),
            status="pending",
            artifact_path="/tmp/test",
        )
        await provider.create_run(run)

        await provider.update_run(run.run_id, {
            "status": "completed",
            "file_count": 100,
            "chunk_count": 500,
        })

        fetched = await provider.get_run(run.run_id)
        assert fetched is not None
        assert fetched.status == "completed"
        assert fetched.file_count == 100
        assert fetched.chunk_count == 500

    async def test_get_latest_run(self, provider: SQLiteOnboardMetadataProvider) -> None:
        # Create two runs
        run1_id = str(uuid.uuid4())
        run2_id = str(uuid.uuid4())

        run1 = OnboardRun(
            run_id=run1_id,
            project_id="test-project",
            timestamp=datetime.now(timezone.utc) - timedelta(days=5),
            status="completed",
            artifact_path="/tmp/test1",
        )
        run2 = OnboardRun(
            run_id=run2_id,
            project_id="test-project",
            timestamp=datetime.now(timezone.utc),
            status="completed",
            artifact_path="/tmp/test2",
        )

        await provider.create_run(run1)
        await provider.create_run(run2)
        await provider.mark_latest(run2_id)

        latest = await provider.get_latest_run("test-project")
        assert latest is not None
        assert latest.run_id == run2_id
        assert latest.is_latest is True

    async def test_mark_latest_clears_previous(
        self, provider: SQLiteOnboardMetadataProvider
    ) -> None:
        run1_id = str(uuid.uuid4())
        run2_id = str(uuid.uuid4())

        run1 = OnboardRun(
            run_id=run1_id,
            project_id="test-project",
            timestamp=datetime.now(timezone.utc) - timedelta(days=5),
            status="completed",
            artifact_path="/tmp/test1",
        )
        run2 = OnboardRun(
            run_id=run2_id,
            project_id="test-project",
            timestamp=datetime.now(timezone.utc),
            status="completed",
            artifact_path="/tmp/test2",
        )

        await provider.create_run(run1)
        await provider.create_run(run2)

        await provider.mark_latest(run1_id)
        latest = await provider.get_latest_run("test-project")
        assert latest is not None
        assert latest.run_id == run1_id

        # Now mark run2 as latest — run1 should lose is_latest
        await provider.mark_latest(run2_id)
        latest = await provider.get_latest_run("test-project")
        assert latest is not None
        assert latest.run_id == run2_id

        # Verify run1 is no longer latest
        old = await provider.get_run(run1_id)
        assert old is not None
        assert old.is_latest is False

    async def test_list_runs(self, provider: SQLiteOnboardMetadataProvider) -> None:
        for i in range(5):
            run = OnboardRun(
                run_id=str(uuid.uuid4()),
                project_id="test-project",
                timestamp=datetime.now(timezone.utc) - timedelta(days=i),
                status="completed",
                artifact_path=f"/tmp/test{i}",
            )
            await provider.create_run(run)

        runs = await provider.list_runs("test-project", limit=3)
        assert len(runs) == 3
        # Should be ordered by timestamp DESC
        assert runs[0].timestamp >= runs[1].timestamp

    async def test_get_nonexistent_run(
        self, provider: SQLiteOnboardMetadataProvider
    ) -> None:
        result = await provider.get_run("nonexistent")
        assert result is None

    async def test_get_latest_no_runs(
        self, provider: SQLiteOnboardMetadataProvider
    ) -> None:
        result = await provider.get_latest_run("no-project")
        assert result is None


class TestMetadataService:
    """Tests for OnboardMetadataService."""

    async def test_create_and_complete_run(
        self, service: OnboardMetadataService
    ) -> None:
        run = await service.create_onboard_run(
            artifact_path="/tmp/artifacts",
            commit_sha="abc123",
        )
        assert run.status == "pending"
        assert run.commit_sha == "abc123"

        await service.complete_onboard_run(
            run.run_id, file_count=100, chunk_count=500, entity_count=200,
        )

        latest = await service.get_latest_onboard()
        assert latest is not None
        assert latest.run_id == run.run_id
        assert latest.status == "completed"
        assert latest.file_count == 100

    async def test_fail_run(self, service: OnboardMetadataService) -> None:
        run = await service.create_onboard_run(artifact_path="/tmp/artifacts")
        await service.fail_onboard_run(run.run_id, "Connection timeout")

        runs = await service.list_runs()
        assert len(runs) == 1
        assert runs[0].status == "failed"
        assert runs[0].error_message == "Connection timeout"

    async def test_no_latest_when_empty(
        self, service: OnboardMetadataService
    ) -> None:
        result = await service.get_latest_onboard()
        assert result is None
