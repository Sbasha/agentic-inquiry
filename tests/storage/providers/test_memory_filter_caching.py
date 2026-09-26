"""Regression: memory provider compiles filter predicate once per call.

Earlier revisions routed every matched row through
``MemoryFilterAdapter().translate(filters)``, which re-walked the AST and
recompiled any LIKE regex on each comparison. Provider methods now call
``_compile_predicate`` once up-front. This test pins that by patching
``MemoryFilterAdapter`` and asserting a single instantiation even when the
scan covers many rows.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

pytestmark = pytest.mark.asyncio


async def test_count_compiles_predicate_once_per_call():
    from agentic_inquiry.storage.providers.memory import InMemoryProvider
    from agentic_inquiry.models.document_chunk import DocumentChunk

    provider = InMemoryProvider(project_id="p")
    await provider.initialize()

    # Seed 25 chunks so a per-row recompile would be very visible.
    chunks = [
        DocumentChunk(
            id=f"c{i}",
            doc_id=f"d{i}",
            project_id="p",
            file_path=f"/f{i}.py",
            content=f"content {i}",
            fts_text=f"content {i}",
            content_type="CODE",
            vector=[0.1] * 8,
            line_start=1,
            line_end=1,
            language="python",
        )
        for i in range(25)
    ]
    await provider.upsert_chunks(chunks, "p")

    with patch("agentic_inquiry.database.filters.MemoryFilterAdapter") as mock_adapter:
        # Make the real predicate still work so we count a realistic 25.
        from agentic_inquiry.database.filters.memory_adapter import (
            MemoryFilterAdapter as _Real,
        )

        real_instance = _Real()
        mock_adapter.return_value = real_instance

        total = await provider.count(filters={"content_type": "CODE"}, project_id="p")

    assert total == 25
    # One construction despite scanning 25 rows.
    assert mock_adapter.call_count == 1

    await provider.close()
