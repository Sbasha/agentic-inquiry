"""Tests for onboard gate logic."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

from agent_vault.onboard.gate import check_onboard_gate
from agent_vault.onboard.staleness import StalenessResult


class TestOnboardGate:
    """Tests for check_onboard_gate."""

    async def test_gate_warns_when_no_onboard(self) -> None:
        mock_service = AsyncMock()
        mock_service.get_latest_onboard.return_value = None

        result = await check_onboard_gate(mock_service, Path("/tmp/workspace"))

        assert result is not None
        assert result.reason == "no_onboard"
        assert result.is_stale is True

    async def test_gate_allows_skip(self) -> None:
        mock_service = AsyncMock()
        mock_service.get_latest_onboard.return_value = None

        # Should not raise with skip_gate=True
        result = await check_onboard_gate(
            mock_service,
            Path("/tmp/workspace"),
            skip_gate=True,
        )

        assert result is not None
        assert result.reason == "no_onboard"

    @patch("agent_vault.onboard.gate.check_onboard_staleness")
    async def test_gate_passes_when_fresh(self, mock_check: AsyncMock) -> None:
        mock_check.return_value = StalenessResult(
            is_stale=False,
            reason=None,
            days_since_onboard=1,
            files_changed=0,
            commits_since_onboard=0,
            last_onboard_date="2026-02-15",
            message="Current",
        )
        mock_service = AsyncMock()

        result = await check_onboard_gate(mock_service, Path("/tmp/workspace"))

        assert result is not None
        assert result.is_stale is False

    @patch("agent_vault.onboard.gate.check_onboard_staleness")
    async def test_gate_warns_when_stale(self, mock_check: AsyncMock) -> None:
        mock_check.return_value = StalenessResult(
            is_stale=True,
            reason="days_elapsed",
            days_since_onboard=30,
            files_changed=5,
            commits_since_onboard=3,
            last_onboard_date="2026-01-15",
            message="Stale: 30 days old",
        )
        mock_service = AsyncMock()

        # Stale but not missing — should not raise
        result = await check_onboard_gate(mock_service, Path("/tmp/workspace"))

        assert result is not None
        assert result.is_stale is True

    async def test_gate_disabled_via_config(self) -> None:
        mock_service = AsyncMock()

        class MockOnboardConfig:
            gate_enabled = False

        class MockConfig:
            onboard = MockOnboardConfig()

        result = await check_onboard_gate(
            mock_service,
            Path("/tmp/workspace"),
            config=MockConfig(),
        )

        assert result is None
        mock_service.get_latest_onboard.assert_not_called()
