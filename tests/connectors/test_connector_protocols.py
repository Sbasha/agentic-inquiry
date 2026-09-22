"""Tests for connector protocols.

Tests cover:
- Protocol runtime checking
- Capability detection helpers
"""
from __future__ import annotations

from typing import AsyncIterator

import pytest

pytestmark = pytest.mark.unit

from agent_vault.connectors.protocols import (
    AuthCapability,
    ChangeDetectionCapability,
    ConnectorProtocol,
    WatchCapability,
    WatchEventType,
    has_auth_capability,
    has_change_detection,
    has_watch_capability,
)
from agent_vault.connectors.types import SourceContent, SourceItem


class MockConnector:
    """Mock connector implementing ConnectorProtocol."""

    async def list(self, root: str) -> AsyncIterator[SourceItem]:
        """Mock list implementation."""
        yield SourceItem(uri="/test/file.py")

    async def open(self, item: SourceItem) -> SourceContent:
        """Mock open implementation."""
        return SourceContent(data=b"test", encoding="utf-8")


class MockWatchableConnector(MockConnector):
    """Mock connector with WatchCapability."""

    async def watch(
        self, root: str
    ) -> AsyncIterator[tuple[WatchEventType, SourceItem]]:
        """Mock watch implementation."""
        yield WatchEventType.CREATED, SourceItem(uri="/test/new.py")


class MockAuthConnector(MockConnector):
    """Mock connector with AuthCapability."""

    def __init__(self) -> None:
        self._authenticated = False

    async def authenticate(self) -> None:
        """Mock authenticate."""
        self._authenticated = True

    async def refresh_auth(self) -> None:
        """Mock refresh_auth."""
        pass

    @property
    def is_authenticated(self) -> bool:
        """Mock is_authenticated."""
        return self._authenticated


class MockChangeDetectionConnector(MockConnector):
    """Mock connector with ChangeDetectionCapability."""

    async def has_changed(self, item: SourceItem) -> bool:
        """Mock has_changed."""
        return True

    async def mark_processed(self, item: SourceItem) -> None:
        """Mock mark_processed."""
        pass


class TestConnectorProtocol:
    """Tests for ConnectorProtocol runtime checking."""

    def test_isinstance_basic_connector(self) -> None:
        """Basic connector passes isinstance check."""
        connector = MockConnector()
        assert isinstance(connector, ConnectorProtocol)

    def test_isinstance_watchable_connector(self) -> None:
        """Watchable connector passes ConnectorProtocol check."""
        connector = MockWatchableConnector()
        assert isinstance(connector, ConnectorProtocol)

    def test_isinstance_auth_connector(self) -> None:
        """Auth connector passes ConnectorProtocol check."""
        connector = MockAuthConnector()
        assert isinstance(connector, ConnectorProtocol)


class TestWatchCapability:
    """Tests for WatchCapability runtime checking."""

    def test_isinstance_watchable(self) -> None:
        """Watchable connector passes WatchCapability check."""
        connector = MockWatchableConnector()
        assert isinstance(connector, WatchCapability)

    def test_isinstance_not_watchable(self) -> None:
        """Basic connector fails WatchCapability check."""
        connector = MockConnector()
        assert not isinstance(connector, WatchCapability)


class TestAuthCapability:
    """Tests for AuthCapability runtime checking."""

    def test_isinstance_auth(self) -> None:
        """Auth connector passes AuthCapability check."""
        connector = MockAuthConnector()
        assert isinstance(connector, AuthCapability)

    def test_isinstance_not_auth(self) -> None:
        """Basic connector fails AuthCapability check."""
        connector = MockConnector()
        assert not isinstance(connector, AuthCapability)


class TestChangeDetectionCapability:
    """Tests for ChangeDetectionCapability runtime checking."""

    def test_isinstance_change_detection(self) -> None:
        """Change detection connector passes check."""
        connector = MockChangeDetectionConnector()
        assert isinstance(connector, ChangeDetectionCapability)

    def test_isinstance_not_change_detection(self) -> None:
        """Basic connector fails ChangeDetectionCapability check."""
        connector = MockConnector()
        assert not isinstance(connector, ChangeDetectionCapability)


class TestCapabilityHelpers:
    """Tests for capability detection helper functions."""

    def test_has_watch_capability_true(self) -> None:
        """has_watch_capability returns True for watchable connector."""
        connector = MockWatchableConnector()
        assert has_watch_capability(connector) is True

    def test_has_watch_capability_false(self) -> None:
        """has_watch_capability returns False for basic connector."""
        connector = MockConnector()
        assert has_watch_capability(connector) is False

    def test_has_auth_capability_true(self) -> None:
        """has_auth_capability returns True for auth connector."""
        connector = MockAuthConnector()
        assert has_auth_capability(connector) is True

    def test_has_auth_capability_false(self) -> None:
        """has_auth_capability returns False for basic connector."""
        connector = MockConnector()
        assert has_auth_capability(connector) is False

    def test_has_change_detection_true(self) -> None:
        """has_change_detection returns True for change detection connector."""
        connector = MockChangeDetectionConnector()
        assert has_change_detection(connector) is True

    def test_has_change_detection_false(self) -> None:
        """has_change_detection returns False for basic connector."""
        connector = MockConnector()
        assert has_change_detection(connector) is False


class TestConnectorUsage:
    """Tests for actual connector usage patterns."""

    @pytest.mark.asyncio
    async def test_list_and_open(self) -> None:
        """Connector can list and open files."""
        connector = MockConnector()

        items = []
        async for item in connector.list("/test"):
            items.append(item)

        assert len(items) == 1
        assert items[0].uri == "/test/file.py"

        content = await connector.open(items[0])
        assert content.text == "test"

    @pytest.mark.asyncio
    async def test_watch_events(self) -> None:
        """Watchable connector yields events."""
        connector = MockWatchableConnector()

        events = []
        async for event_type, item in connector.watch("/test"):
            events.append((event_type, item))
            break  # Don't run forever

        assert len(events) == 1
        assert events[0][0] == WatchEventType.CREATED
        assert events[0][1].uri == "/test/new.py"

    @pytest.mark.asyncio
    async def test_authenticate(self) -> None:
        """Auth connector can authenticate."""
        connector = MockAuthConnector()

        assert connector.is_authenticated is False
        await connector.authenticate()
        assert connector.is_authenticated is True

    @pytest.mark.asyncio
    async def test_change_detection(self) -> None:
        """Change detection connector tracks changes."""
        connector = MockChangeDetectionConnector()
        item = SourceItem(uri="/test/file.py")

        assert await connector.has_changed(item) is True
        await connector.mark_processed(item)
