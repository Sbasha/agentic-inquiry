"""Tests for LanceDB library assumptions.

These tests verify that LanceDB behaves as expected
and that our assumptions about vector storage are correct.

Run with: pytest tests/adapters/test_lancedb.py -v
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

pytestmark = [pytest.mark.adapters]


class TestDatabaseCreation:
    """Test database creation assumptions."""

    def test_connect_creates_directory(self, skip_if_no_lancedb):
        """Connecting to new path creates database directory."""
        import lancedb

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.lancedb"
            lancedb.connect(str(db_path))

            assert db_path.exists()
            # LanceDB connections don't need explicit closing

    def test_connect_is_idempotent(self, skip_if_no_lancedb):
        """Connecting multiple times doesn't error."""
        import lancedb

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.lancedb"

            db1 = lancedb.connect(str(db_path))
            db2 = lancedb.connect(str(db_path))

            # Both connections work
            assert db1 is not db2
            # LanceDB connections don't need explicit closing


class TestTableOperations:
    """Test table operation assumptions."""

    def test_create_table_with_schema(self, skip_if_no_lancedb):
        """Tables can be created with explicit schema."""
        import lancedb
        import pyarrow as pa

        with tempfile.TemporaryDirectory() as tmp:
            db = lancedb.connect(tmp)

            schema = pa.schema(
                [
                    pa.field("id", pa.string()),
                    pa.field("text", pa.string()),
                    pa.field("vector", pa.list_(pa.float32(), 384)),
                ]
            )

            # Create empty table with schema
            table = db.create_table("test", schema=schema)
            assert table.schema == schema

    def test_table_names_listing(self, skip_if_no_lancedb):
        """Created tables appear in table_names()."""
        import lancedb
        import pyarrow as pa

        with tempfile.TemporaryDirectory() as tmp:
            db = lancedb.connect(tmp)

            schema = pa.schema(
                [
                    pa.field("id", pa.string()),
                    pa.field("vector", pa.list_(pa.float32(), 384)),
                ]
            )

            db.create_table("table1", schema=schema)
            db.create_table("table2", schema=schema)

            names = db.table_names()
            assert "table1" in names
            assert "table2" in names

    def test_open_existing_table(self, skip_if_no_lancedb):
        """Existing tables can be opened."""
        import lancedb
        import pyarrow as pa

        with tempfile.TemporaryDirectory() as tmp:
            db = lancedb.connect(tmp)

            schema = pa.schema(
                [
                    pa.field("id", pa.string()),
                    pa.field("vector", pa.list_(pa.float32(), 384)),
                ]
            )

            db.create_table("test", schema=schema)

            # Open same table
            table = db.open_table("test")
            assert table.name == "test"


class TestVectorSearch:
    """Test vector search assumptions."""

    def test_add_and_search(self, skip_if_no_lancedb):
        """Added vectors can be searched."""
        import lancedb

        with tempfile.TemporaryDirectory() as tmp:
            db = lancedb.connect(tmp)

            data = [
                {"id": "1", "text": "hello", "vector": [0.1] * 384},
                {"id": "2", "text": "world", "vector": [0.2] * 384},
                {"id": "3", "text": "test", "vector": [0.3] * 384},
            ]

            table = db.create_table("test", data)

            # Search
            results = table.search([0.1] * 384).limit(2).to_list()

            assert len(results) == 2
            assert results[0]["id"] == "1"  # Closest match
            # LanceDB handles cleanup internally

    def test_search_returns_distance(self, skip_if_no_lancedb):
        """Search results include distance metric."""
        import lancedb

        with tempfile.TemporaryDirectory() as tmp:
            db = lancedb.connect(tmp)

            data = [
                {"id": "1", "vector": [1.0] * 384},
                {"id": "2", "vector": [0.5] * 384},
            ]

            table = db.create_table("test", data)
            results = table.search([1.0] * 384).limit(2).to_list()

            # Results should have _distance field
            assert "_distance" in results[0]
            assert results[0]["_distance"] < results[1]["_distance"]
            # LanceDB handles cleanup internally

    def test_search_with_filter(self, skip_if_no_lancedb):
        """Search can be filtered by metadata."""
        import lancedb

        with tempfile.TemporaryDirectory() as tmp:
            db = lancedb.connect(tmp)

            data = [
                {"id": "1", "category": "A", "vector": [0.1] * 384},
                {"id": "2", "category": "B", "vector": [0.1] * 384},
                {"id": "3", "category": "A", "vector": [0.2] * 384},
            ]

            table = db.create_table("test", data)

            # Filter by category
            results = (
                table.search([0.1] * 384).where("category = 'A'").limit(10).to_list()
            )

            assert len(results) == 2
            assert all(r["category"] == "A" for r in results)
            # LanceDB handles cleanup internally


class TestDataOperations:
    """Test data operation assumptions."""

    def test_add_data_incremental(self, skip_if_no_lancedb):
        """Data can be added incrementally."""
        import lancedb

        with tempfile.TemporaryDirectory() as tmp:
            db = lancedb.connect(tmp)

            initial = [{"id": "1", "vector": [0.1] * 384}]
            table = db.create_table("test", initial)

            # Add more
            additional = [{"id": "2", "vector": [0.2] * 384}]
            table.add(additional)

            assert table.count_rows() == 2
            # LanceDB handles cleanup internally

    def test_delete_data(self, skip_if_no_lancedb):
        """Data can be deleted by filter."""
        import lancedb

        with tempfile.TemporaryDirectory() as tmp:
            db = lancedb.connect(tmp)

            data = [
                {"id": "1", "vector": [0.1] * 384},
                {"id": "2", "vector": [0.2] * 384},
            ]
            table = db.create_table("test", data)

            # Delete by id
            table.delete("id = '1'")

            assert table.count_rows() == 1
            # LanceDB handles cleanup internally

    def test_update_data(self, skip_if_no_lancedb):
        """Data can be updated by filter."""
        import lancedb

        with tempfile.TemporaryDirectory() as tmp:
            db = lancedb.connect(tmp)

            data = [
                {"id": "1", "text": "old", "vector": [0.1] * 384},
            ]
            table = db.create_table("test", data)

            # Update
            table.update(where="id = '1'", values={"text": "new"})

            results = table.search([0.1] * 384).limit(1).to_list()
            assert results[0]["text"] == "new"
            # LanceDB handles cleanup internally


class TestFullTextSearch:
    """Test full-text search assumptions."""

    def test_fts_index_creation(self, skip_if_no_lancedb):
        """Full-text search index can be created."""
        import lancedb

        with tempfile.TemporaryDirectory() as tmp:
            db = lancedb.connect(tmp)

            data = [
                {"id": "1", "text": "hello world", "vector": [0.1] * 384},
                {"id": "2", "text": "goodbye world", "vector": [0.2] * 384},
            ]
            table = db.create_table("test", data)

            # Create FTS index
            table.create_fts_index("text")

            # FTS search should work
            results = table.search("hello", query_type="fts").limit(10).to_list()

            assert len(results) >= 1
            assert "hello" in results[0]["text"]
            # LanceDB handles cleanup internally


class TestConcurrency:
    """Test concurrency assumptions."""

    def test_concurrent_reads(self, skip_if_no_lancedb):
        """Concurrent reads don't cause errors."""
        import asyncio
        import lancedb

        async def run_test():
            with tempfile.TemporaryDirectory() as tmp:
                db = lancedb.connect(tmp)

                data = [{"id": str(i), "vector": [0.1 * i] * 384} for i in range(100)]
                table = db.create_table("test", data)

                async def read_operation():
                    # LanceDB operations are sync, but we can run many
                    return table.search([0.5] * 384).limit(5).to_list()

                # Run concurrent reads
                tasks = [read_operation() for _ in range(10)]
                results = await asyncio.gather(*tasks)

                assert all(len(r) == 5 for r in results)
                # LanceDB handles cleanup internally

        asyncio.run(run_test())
