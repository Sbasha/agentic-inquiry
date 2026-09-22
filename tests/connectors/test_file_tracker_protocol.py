# tests/connectors/test_file_tracker_protocol.py
"""Tests for HashTrackerProtocol and implementations."""
import pytest

pytestmark = pytest.mark.unit
from typing import Set

from agentic_inquiry.connectors.protocols import HashTrackerProtocol, has_hash_tracker
from agentic_inquiry.connectors.base import InMemoryFileTracker


class TestHashTrackerProtocol:
    """Tests for HashTrackerProtocol interface."""

    def test_protocol_is_runtime_checkable(self):
        """Test that HashTrackerProtocol can be used with isinstance()."""
        tracker = InMemoryFileTracker()
        assert isinstance(tracker, HashTrackerProtocol)

    def test_has_hash_tracker_with_conforming_implementation(self):
        """Test has_hash_tracker returns True for conforming implementations."""
        tracker = InMemoryFileTracker()
        assert has_hash_tracker(tracker) is True

    def test_has_hash_tracker_with_non_conforming_object(self):
        """Test has_hash_tracker returns False for non-conforming objects."""
        class NotATracker:
            pass

        obj = NotATracker()
        assert has_hash_tracker(obj) is False

    def test_has_hash_tracker_with_partial_implementation(self):
        """Test has_hash_tracker returns False for partial implementations."""
        class PartialTracker:
            async def is_processed(self, file_hash: str) -> bool:
                return False
            # Missing other required methods

        obj = PartialTracker()
        # Partial implementations don't satisfy the protocol
        assert has_hash_tracker(obj) is False


class TestInMemoryFileTracker:
    """Tests for InMemoryFileTracker implementation."""

    @pytest.fixture
    def tracker(self) -> InMemoryFileTracker:
        """Create a fresh tracker for each test."""
        return InMemoryFileTracker()

    @pytest.mark.asyncio
    async def test_implements_protocol(self, tracker: InMemoryFileTracker):
        """Test that InMemoryFileTracker implements HashTrackerProtocol."""
        assert isinstance(tracker, HashTrackerProtocol)

    @pytest.mark.asyncio
    async def test_is_processed_returns_false_for_new_hash(
        self, tracker: InMemoryFileTracker
    ):
        """Test is_processed returns False for never-processed hash."""
        result = await tracker.is_processed("abc123")
        assert result is False

    @pytest.mark.asyncio
    async def test_mark_processed_then_is_processed(
        self, tracker: InMemoryFileTracker
    ):
        """Test that mark_processed makes is_processed return True."""
        file_hash = "abc123def456"

        # Initially not processed
        assert await tracker.is_processed(file_hash) is False

        # Mark as processed
        await tracker.mark_processed(file_hash)

        # Now should be processed
        assert await tracker.is_processed(file_hash) is True

    @pytest.mark.asyncio
    async def test_mark_processed_is_idempotent(
        self, tracker: InMemoryFileTracker
    ):
        """Test that marking the same hash multiple times is safe."""
        file_hash = "abc123"

        await tracker.mark_processed(file_hash)
        await tracker.mark_processed(file_hash)
        await tracker.mark_processed(file_hash)

        # Should still only count as one
        assert await tracker.get_processed_count() == 1
        assert await tracker.is_processed(file_hash) is True

    @pytest.mark.asyncio
    async def test_get_processed_count_initially_zero(
        self, tracker: InMemoryFileTracker
    ):
        """Test that count is zero for new tracker."""
        count = await tracker.get_processed_count()
        assert count == 0

    @pytest.mark.asyncio
    async def test_get_processed_count_increases_with_marks(
        self, tracker: InMemoryFileTracker
    ):
        """Test that count increases as hashes are marked."""
        assert await tracker.get_processed_count() == 0

        await tracker.mark_processed("hash1")
        assert await tracker.get_processed_count() == 1

        await tracker.mark_processed("hash2")
        assert await tracker.get_processed_count() == 2

        await tracker.mark_processed("hash3")
        assert await tracker.get_processed_count() == 3

    @pytest.mark.asyncio
    async def test_clear_removes_all_entries(
        self, tracker: InMemoryFileTracker
    ):
        """Test that clear removes all tracked hashes."""
        # Add some hashes
        await tracker.mark_processed("hash1")
        await tracker.mark_processed("hash2")
        await tracker.mark_processed("hash3")
        assert await tracker.get_processed_count() == 3

        # Clear
        cleared = await tracker.clear()

        # Should return count of cleared entries
        assert cleared == 3

        # Count should be zero
        assert await tracker.get_processed_count() == 0

        # Previously processed hashes should no longer be marked
        assert await tracker.is_processed("hash1") is False
        assert await tracker.is_processed("hash2") is False
        assert await tracker.is_processed("hash3") is False

    @pytest.mark.asyncio
    async def test_clear_on_empty_tracker(
        self, tracker: InMemoryFileTracker
    ):
        """Test that clear on empty tracker returns zero."""
        cleared = await tracker.clear()
        assert cleared == 0

    @pytest.mark.asyncio
    async def test_multiple_different_hashes(
        self, tracker: InMemoryFileTracker
    ):
        """Test tracking multiple different hashes independently."""
        hashes = ["hash_a", "hash_b", "hash_c", "hash_d", "hash_e"]

        # Mark half of them
        for h in hashes[:3]:
            await tracker.mark_processed(h)

        # Check each
        assert await tracker.is_processed("hash_a") is True
        assert await tracker.is_processed("hash_b") is True
        assert await tracker.is_processed("hash_c") is True
        assert await tracker.is_processed("hash_d") is False
        assert await tracker.is_processed("hash_e") is False

        assert await tracker.get_processed_count() == 3


class TestCustomHashTrackerCompliance:
    """Tests to verify custom implementations comply with the protocol."""

    def test_custom_implementation_satisfies_protocol(self):
        """Test that a custom implementation can satisfy the protocol."""

        class CustomTracker:
            """A custom HashTrackerProtocol implementation for testing."""

            def __init__(self):
                self._processed: Set[str] = set()

            async def is_processed(self, file_hash: str) -> bool:
                return file_hash in self._processed

            async def mark_processed(self, file_hash: str) -> None:
                self._processed.add(file_hash)

            async def get_processed_count(self) -> int:
                return len(self._processed)

            async def clear(self) -> int:
                count = len(self._processed)
                self._processed.clear()
                return count

        tracker = CustomTracker()
        assert isinstance(tracker, HashTrackerProtocol)
        assert has_hash_tracker(tracker) is True

    @pytest.mark.asyncio
    async def test_custom_implementation_works_correctly(self):
        """Test that a custom implementation works as expected."""

        class PersistentTracker:
            """Example of a tracker that could persist to storage."""

            def __init__(self):
                self._store: dict[str, bool] = {}

            async def is_processed(self, file_hash: str) -> bool:
                return self._store.get(file_hash, False)

            async def mark_processed(self, file_hash: str) -> None:
                self._store[file_hash] = True

            async def get_processed_count(self) -> int:
                return sum(1 for v in self._store.values() if v)

            async def clear(self) -> int:
                count = len(self._store)
                self._store.clear()
                return count

        tracker = PersistentTracker()

        # Verify protocol compliance
        assert isinstance(tracker, HashTrackerProtocol)

        # Verify functionality
        assert await tracker.is_processed("test") is False
        await tracker.mark_processed("test")
        assert await tracker.is_processed("test") is True
        assert await tracker.get_processed_count() == 1

        cleared = await tracker.clear()
        assert cleared == 1
        assert await tracker.get_processed_count() == 0
