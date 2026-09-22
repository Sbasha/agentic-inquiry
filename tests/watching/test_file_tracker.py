"""Tests for FileTracker with storage consolidation and project isolation."""

import pytest

pytestmark = pytest.mark.integration

from pathlib import Path

import aiosqlite

from agentic_inquiry.config import Config, StorageConfig, FileTrackerConfig
from agentic_inquiry.watching.file_tracker import FileTracker


@pytest.fixture
def temp_dir(tmp_path):
    """Provide a temporary directory for test files."""
    return tmp_path


@pytest.fixture
def temp_db_path(temp_dir):
    """Provide a temporary database path."""
    return temp_dir / "test_tracker.db"


@pytest.fixture
def mock_config(temp_dir):
    """Provide a test configuration with custom storage root."""
    storage = StorageConfig(
        root=str(temp_dir / "storage"),
        default_project_id="test_project",
    )
    storage.file_tracker = FileTrackerConfig(path="file_tracker.db")
    
    config = Config(storage=storage)
    return config


@pytest.fixture
def sample_file(temp_dir):
    """Create a sample file for testing."""
    file_path = temp_dir / "sample.txt"
    file_path.write_text("Hello, World!")
    return str(file_path)


class TestFileTrackerInitialization:
    """Test FileTracker initialization with various configurations."""
    
    @pytest.mark.asyncio
    async def test_init_with_explicit_path(self, temp_db_path):
        """Test initialization with explicit database path."""
        tracker = await FileTracker.from_config(db_path=temp_db_path)
        
        assert tracker.db_path == str(temp_db_path.resolve())
        assert tracker.project_id == "default"  # Uses default from config
        assert Path(tracker.db_path).exists()
    
    @pytest.mark.asyncio
    async def test_init_with_config(self, mock_config):
        """Test initialization with config object."""
        tracker = await FileTracker.from_config(config=mock_config, project_id="test_project")

        expected_path = mock_config.storage.get_file_tracker_path()
        assert tracker.db_path == str(expected_path)
        assert tracker.project_id == "test_project"
        assert Path(tracker.db_path).exists()
    
    @pytest.mark.asyncio
    async def test_init_creates_parent_directories(self, temp_dir):
        """Test that parent directories are created if they don't exist."""
        nested_path = temp_dir / "nested" / "dirs" / "tracker.db"
        tracker = await FileTracker.from_config(db_path=nested_path)
        
        assert Path(tracker.db_path).parent.exists()
        assert Path(tracker.db_path).exists()


class TestFileTrackerSchema:
    """Test database schema and migration."""
    
    @pytest.mark.asyncio
    async def test_new_database_has_project_id_column(self, temp_db_path):
        """Test that new databases include project_id column."""
        tracker = await FileTracker.from_config(db_path=temp_db_path)
        
        async with aiosqlite.connect(tracker.db_path) as conn:
            cursor = await conn.cursor()
            await cursor.execute("PRAGMA table_info(file_states)")
            columns = {row[1] for row in await cursor.fetchall()}
        
        assert "project_id" in columns
        assert "file_path" in columns
        assert "content_hash" in columns
        assert "last_updated" in columns
    
    @pytest.mark.asyncio
    async def test_legacy_schema_migration(self, temp_db_path):
        """Test migration from legacy schema without project_id."""
        # Create legacy schema
        async with aiosqlite.connect(str(temp_db_path)) as conn:
            cursor = await conn.cursor()
            await cursor.execute("""
                CREATE TABLE file_states (
                    file_path TEXT PRIMARY KEY,
                    content_hash TEXT NOT NULL,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Insert legacy data
            await cursor.execute("""
                INSERT INTO file_states (file_path, content_hash)
                VALUES ('test.txt', 'abc123')
            """)
            await conn.commit()
        
        # Initialize tracker (should trigger migration)
        tracker = await FileTracker.from_config(db_path=temp_db_path)
        
        # Verify schema was migrated
        async with aiosqlite.connect(tracker.db_path) as conn:
            cursor = await conn.cursor()
            await cursor.execute("PRAGMA table_info(file_states)")
            columns = {row[1] for row in await cursor.fetchall()}
            
            assert "project_id" in columns
            
            # Verify data was migrated with project_id
            await cursor.execute("SELECT project_id, file_path, content_hash FROM file_states")
            rows = await cursor.fetchall()
            
            assert len(rows) == 1
            assert rows[0][0] == tracker.project_id
            assert rows[0][1] == "test.txt"
            assert rows[0][2] == "abc123"


class TestFileTrackerOperations:
    """Test basic file tracking operations with project isolation."""
    
    @pytest.mark.asyncio
    async def test_update_and_get_hash(self, temp_db_path, sample_file):
        """Test updating and retrieving file hash."""
        tracker = await FileTracker.from_config(db_path=temp_db_path)
        
        # Update hash
        hash_value = await tracker.update_hash(sample_file)
        assert hash_value is not None
        assert len(hash_value) == 64  # SHA256 hex length
        
        # Get hash
        retrieved_hash = await tracker.get_hash(sample_file)
        assert retrieved_hash == hash_value
    
    @pytest.mark.asyncio
    async def test_has_changed_new_file(self, temp_db_path, sample_file):
        """Test has_changed returns True for untracked file."""
        tracker = await FileTracker.from_config(db_path=temp_db_path)
        
        assert await tracker.has_changed(sample_file) is True
    
    @pytest.mark.asyncio
    async def test_has_changed_unchanged_file(self, temp_db_path, sample_file):
        """Test has_changed returns False for unchanged file."""
        tracker = await FileTracker.from_config(db_path=temp_db_path)
        
        await tracker.update_hash(sample_file)
        assert await tracker.has_changed(sample_file) is False
    
    @pytest.mark.asyncio
    async def test_has_changed_modified_file(self, temp_db_path, sample_file):
        """Test has_changed returns True for modified file."""
        tracker = await FileTracker.from_config(db_path=temp_db_path)
        
        await tracker.update_hash(sample_file)
        
        # Modify file
        Path(sample_file).write_text("Modified content")
        
        assert await tracker.has_changed(sample_file) is True
    
    @pytest.mark.asyncio
    async def test_remove_file(self, temp_db_path, sample_file):
        """Test removing file from tracking."""
        tracker = await FileTracker.from_config(db_path=temp_db_path)
        
        await tracker.update_hash(sample_file)
        assert await tracker.get_hash(sample_file) is not None
        
        removed = await tracker.remove_file(sample_file)
        assert removed is True
        assert await tracker.get_hash(sample_file) is None
        
        # Removing again should return False
        removed = await tracker.remove_file(sample_file)
        assert removed is False
    
    @pytest.mark.asyncio
    async def test_list_tracked_files(self, temp_db_path, temp_dir):
        """Test listing tracked files."""
        tracker = await FileTracker.from_config(db_path=temp_db_path)
        
        # Create and track multiple files
        file1 = temp_dir / "file1.txt"
        file2 = temp_dir / "file2.txt"
        file1.write_text("Content 1")
        file2.write_text("Content 2")
        
        hash1 = await tracker.update_hash(str(file1))
        hash2 = await tracker.update_hash(str(file2))
        
        tracked = await tracker.list_tracked_files()
        assert len(tracked) == 2
        
        tracked_dict = dict(tracked)
        assert tracked_dict[str(file1)] == hash1
        assert tracked_dict[str(file2)] == hash2
    
    @pytest.mark.asyncio
    async def test_clear(self, temp_db_path, sample_file):
        """Test clearing all tracked files."""
        tracker = await FileTracker.from_config(db_path=temp_db_path)
        
        await tracker.update_hash(sample_file)
        assert len(await tracker.list_tracked_files()) == 1
        
        await tracker.clear()
        assert len(await tracker.list_tracked_files()) == 0


class TestProjectIsolation:
    """Test project isolation functionality."""
    
    @pytest.mark.asyncio
    async def test_different_projects_isolated(self, temp_db_path, sample_file):
        """Test that different projects don't see each other's data."""
        # Create tracker for project 1
        storage1 = StorageConfig(root="./storage", default_project_id="project1")
        config1 = Config(storage=storage1)
        tracker1 = await FileTracker.from_config(config=config1, project_id="project1", db_path=temp_db_path)

        # Create tracker for project 2 (same database)
        storage2 = StorageConfig(root="./storage", default_project_id="project2")
        config2 = Config(storage=storage2)
        tracker2 = await FileTracker.from_config(config=config2, project_id="project2", db_path=temp_db_path)
        
        # Track file in project 1
        hash1 = await tracker1.update_hash(sample_file)
        
        # Project 2 should not see project 1's file
        assert await tracker2.get_hash(sample_file) is None
        assert await tracker1.get_hash(sample_file) == hash1
        
        # Track same file in project 2 with different content
        Path(sample_file).write_text("Different content")
        hash2 = await tracker2.update_hash(sample_file)
        
        # Both projects should have their own hashes
        assert await tracker1.get_hash(sample_file) == hash1
        assert await tracker2.get_hash(sample_file) == hash2
        assert hash1 != hash2
    
    @pytest.mark.asyncio
    async def test_list_tracked_files_project_isolation(self, temp_db_path, temp_dir):
        """Test that list_tracked_files only returns current project's files."""
        # Create trackers for two projects
        storage1 = StorageConfig(root="./storage", default_project_id="project1")
        config1 = Config(storage=storage1)
        tracker1 = await FileTracker.from_config(config=config1, project_id="project1", db_path=temp_db_path)

        storage2 = StorageConfig(root="./storage", default_project_id="project2")
        config2 = Config(storage=storage2)
        tracker2 = await FileTracker.from_config(config=config2, project_id="project2", db_path=temp_db_path)
        
        # Create files
        file1 = temp_dir / "file1.txt"
        file2 = temp_dir / "file2.txt"
        file1.write_text("Content 1")
        file2.write_text("Content 2")
        
        # Track files in different projects
        await tracker1.update_hash(str(file1))
        await tracker2.update_hash(str(file2))
        
        # Each project should only see its own files
        tracked1 = await tracker1.list_tracked_files()
        tracked2 = await tracker2.list_tracked_files()
        
        assert len(tracked1) == 1
        assert len(tracked2) == 1
        assert tracked1[0][0] == str(file1)
        assert tracked2[0][0] == str(file2)
    
    @pytest.mark.asyncio
    async def test_clear_only_affects_current_project(self, temp_db_path, sample_file):
        """Test that clear only removes current project's data."""
        # Create trackers for two projects
        storage1 = StorageConfig(root="./storage", default_project_id="project1")
        config1 = Config(storage=storage1)
        tracker1 = await FileTracker.from_config(config=config1, project_id="project1", db_path=temp_db_path)

        storage2 = StorageConfig(root="./storage", default_project_id="project2")
        config2 = Config(storage=storage2)
        tracker2 = await FileTracker.from_config(config=config2, project_id="project2", db_path=temp_db_path)
        
        # Track file in both projects
        await tracker1.update_hash(sample_file)
        await tracker2.update_hash(sample_file)
        
        # Clear project 1
        await tracker1.clear()
        
        # Project 1 should be empty, project 2 should still have data
        assert len(await tracker1.list_tracked_files()) == 0
        assert len(await tracker2.list_tracked_files()) == 1


class TestBackwardCompatibility:
    """Test backward compatibility with legacy usage."""

    @pytest.mark.asyncio
    async def test_default_db_path_with_config(self, mock_config):
        """Test that FileTracker uses config path when no db_path provided."""
        tracker = await FileTracker.from_config(config=mock_config, project_id="test_project")

        expected_path = mock_config.storage.get_file_tracker_path()
        assert tracker.db_path == str(expected_path)

    @pytest.mark.asyncio
    async def test_explicit_path_overrides_config(self, temp_db_path, mock_config):
        """Test that explicit db_path overrides config."""
        tracker = await FileTracker.from_config(config=mock_config, project_id="test_project", db_path=temp_db_path)

        assert tracker.db_path == str(temp_db_path.resolve())
        # But still uses the provided project_id
        assert tracker.project_id == "test_project"


class TestErrorHandling:
    """Test error handling in FileTracker."""
    
    @pytest.mark.asyncio
    async def test_compute_hash_nonexistent_file(self, temp_db_path):
        """Test that computing hash for nonexistent file raises error."""
        tracker = await FileTracker.from_config(db_path=temp_db_path)
        
        with pytest.raises(FileNotFoundError):
            await tracker._compute_hash("nonexistent_file.txt")
    
    @pytest.mark.asyncio
    async def test_has_changed_nonexistent_file(self, temp_db_path):
        """Test that has_changed returns True for nonexistent file."""
        tracker = await FileTracker.from_config(db_path=temp_db_path)
        
        # Should return True (consider it changed) rather than raising error
        assert await tracker.has_changed("nonexistent_file.txt") is True


class TestConcurrentOperations:
    """Test concurrent async operations."""
    
    @pytest.mark.asyncio
    async def test_concurrent_hash_updates(self, temp_db_path, temp_dir):
        """Test concurrent hash updates don't cause conflicts."""
        import asyncio
        
        tracker = await FileTracker.from_config(db_path=temp_db_path)
        
        # Create multiple files
        files = []
        for i in range(10):
            file_path = temp_dir / f"file_{i}.txt"
            file_path.write_text(f"Content {i}")
            files.append(str(file_path))
        
        # Update hashes concurrently
        tasks = [tracker.update_hash(f) for f in files]
        hashes = await asyncio.gather(*tasks)
        
        # Verify all hashes were stored
        assert len(hashes) == 10
        assert all(len(h) == 64 for h in hashes)
        
        # Verify all files are tracked
        tracked = await tracker.list_tracked_files()
        assert len(tracked) == 10
    
    @pytest.mark.asyncio
    async def test_concurrent_has_changed_checks(self, temp_db_path, temp_dir):
        """Test concurrent has_changed checks."""
        import asyncio
        
        tracker = await FileTracker.from_config(db_path=temp_db_path)
        
        # Create and track files
        files = []
        for i in range(10):
            file_path = temp_dir / f"file_{i}.txt"
            file_path.write_text(f"Content {i}")
            files.append(str(file_path))
            await tracker.update_hash(str(file_path))
        
        # Check all files concurrently
        tasks = [tracker.has_changed(f) for f in files]
        results = await asyncio.gather(*tasks)
        
        # All should be unchanged
        assert all(not changed for changed in results)
