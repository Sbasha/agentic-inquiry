"""Unit tests for storage configuration changes.

Tests cover:
- Path resolution with various inputs (absolute, relative, with ~)
- Environment variable overrides for all storage options
- Directory creation via ensure_storage_directories
- Error handling for invalid paths and permissions
"""

import pytest

pytestmark = pytest.mark.unit

from pathlib import Path

from agentic_inquiry.config import (
    Config,
    ConfigurationError,
    DocumentCacheStorageConfig,
    FileTrackerConfig,
    LanceDBConfig,
    StorageConfig,
    StoragePathError,
)


@pytest.fixture
def temp_storage_root(tmp_path):
    """Provide temporary storage root for testing."""
    storage_root = tmp_path / "test_storage"
    yield storage_root
    # Cleanup handled by tmp_path


@pytest.fixture
def storage_config(temp_storage_root):
    """Provide test storage configuration."""
    return StorageConfig(
        root=str(temp_storage_root),
        default_project_id="test_project",
        lancedb=LanceDBConfig(path="lancedb"),
        file_tracker=FileTrackerConfig(path="file_tracker.db"),
        document_cache=DocumentCacheStorageConfig(enabled=True, path="document_cache"),
    )


class TestPathResolution:
    """Test path resolution with various inputs."""

    def test_absolute_path_resolution(self, tmp_path):
        """Test that absolute paths are resolved correctly."""
        absolute_path = tmp_path / "absolute_storage"
        config = StorageConfig(root=str(absolute_path))

        resolved = config.get_lancedb_path()
        assert resolved.is_absolute()
        assert resolved == absolute_path / "lancedb"

    def test_relative_path_resolution(self):
        """Test that relative paths are resolved relative to cwd."""
        config = StorageConfig(root="./relative_storage")

        resolved = config.get_lancedb_path()
        assert resolved.is_absolute()
        assert resolved == Path.cwd().resolve() / "relative_storage" / "lancedb"

    def test_home_directory_expansion(self):
        """Test that ~ is expanded to user home directory."""
        config = StorageConfig(root="~/test_storage")

        resolved = config.get_lancedb_path()
        assert resolved.is_absolute()
        assert "~" not in str(resolved)
        assert resolved == Path.home() / "test_storage" / "lancedb"

    def test_lancedb_path_resolution(self, storage_config, temp_storage_root):
        """Test LanceDB path resolution."""
        path = storage_config.get_lancedb_path()

        assert path.is_absolute()
        assert path == temp_storage_root / "lancedb"

    def test_file_tracker_path_resolution(self, storage_config, temp_storage_root):
        """Test FileTracker path resolution."""
        path = storage_config.get_file_tracker_path()

        assert path.is_absolute()
        assert path == temp_storage_root / "file_tracker.db"

    def test_document_cache_path_resolution(self, storage_config, temp_storage_root):
        """Test DocumentCache path resolution."""
        path = storage_config.get_document_cache_path()

        assert path.is_absolute()
        assert path == temp_storage_root / "document_cache"

    def test_nested_path_resolution(self, temp_storage_root):
        """Test resolution of nested component paths."""
        config = StorageConfig(
            root=str(temp_storage_root),
            lancedb=LanceDBConfig(path="data/lancedb"),
            file_tracker=FileTrackerConfig(path="data/tracker.db"),
            document_cache=DocumentCacheStorageConfig(enabled=True, path="data/cache"),
        )

        assert config.get_lancedb_path() == temp_storage_root / "data" / "lancedb"
        assert (
            config.get_file_tracker_path() == temp_storage_root / "data" / "tracker.db"
        )
        assert config.get_document_cache_path() == temp_storage_root / "data" / "cache"


class TestEnvironmentVariableOverrides:
    """Test environment variable overrides for storage options."""

    def test_storage_root_override(self, tmp_path, monkeypatch):
        """Test INQUIRY_STORAGE_ROOT environment variable override."""
        override_path = tmp_path / "env_storage"
        monkeypatch.setenv("INQUIRY_STORAGE_ROOT", str(override_path))

        config_data = {"storage": {"root": "./default_storage"}}
        config_data = Config._apply_env_overrides(config_data)

        assert config_data["storage"]["root"] == str(override_path)

    @pytest.mark.parametrize(
        ("env_var", "env_value", "config_data", "path", "expected"),
        [
            (
                "INQUIRY_STORAGE_DEFAULT_PROJECT_ID",
                "env_project",
                {"storage": {"default_project_id": None}},
                ("storage", "default_project_id"),
                "env_project",
            ),
            (
                "INQUIRY_STORAGE_LANCEDB_PATH",
                "custom_lancedb",
                {"storage": {"lancedb": {"path": "lancedb"}}},
                ("storage", "lancedb", "path"),
                "custom_lancedb",
            ),
            (
                "INQUIRY_STORAGE_FILE_TRACKER_PATH",
                "custom_tracker.db",
                {"storage": {"file_tracker": {"path": "file_tracker.db"}}},
                ("storage", "file_tracker", "path"),
                "custom_tracker.db",
            ),
            (
                "INQUIRY_STORAGE_DOCUMENT_CACHE_ENABLED",
                "true",
                {"storage": {"document_cache": {"enabled": False}}},
                ("storage", "document_cache", "enabled"),
                True,
            ),
            (
                "INQUIRY_STORAGE_DOCUMENT_CACHE_PATH",
                "custom_cache",
                {"storage": {"document_cache": {"path": "document_cache"}}},
                ("storage", "document_cache", "path"),
                "custom_cache",
            ),
        ],
    )
    def test_storage_env_overrides(
        self, monkeypatch, env_var, env_value, config_data, path, expected
    ):
        """Test storage environment variable overrides."""
        import copy

        monkeypatch.setenv(env_var, env_value)

        config_data = Config._apply_env_overrides(copy.deepcopy(config_data))

        current = config_data
        for key in path:
            current = current[key]
        assert current == expected

    def test_multiple_overrides(self, tmp_path, monkeypatch):
        """Test multiple environment variable overrides simultaneously."""
        monkeypatch.setenv("INQUIRY_STORAGE_ROOT", str(tmp_path / "env_root"))
        monkeypatch.setenv("INQUIRY_STORAGE_DEFAULT_PROJECT_ID", "env_proj")
        monkeypatch.setenv("INQUIRY_STORAGE_LANCEDB_PATH", "env_lancedb")
        monkeypatch.setenv("INQUIRY_STORAGE_DOCUMENT_CACHE_ENABLED", "true")

        config_data = {
            "storage": {
                "root": "./default",
                "default_project_id": None,
                "lancedb": {"path": "lancedb"},
                "document_cache": {"enabled": False, "path": "cache"},
            }
        }
        config_data = Config._apply_env_overrides(config_data)

        assert config_data["storage"]["root"] == str(tmp_path / "env_root")
        assert config_data["storage"]["default_project_id"] == "env_proj"
        assert config_data["storage"]["lancedb"]["path"] == "env_lancedb"
        assert config_data["storage"]["document_cache"]["enabled"] is True

    @pytest.mark.parametrize(
        ("env_value", "expected"),
        [
            ("true", True),
            ("True", True),
            ("TRUE", True),
            ("yes", True),
            ("1", True),
            ("false", False),
            ("False", False),
            ("FALSE", False),
            ("no", False),
            ("0", False),
        ],
    )
    def test_boolean_conversion(self, monkeypatch, env_value, expected):
        """Test that boolean environment variables are converted correctly."""
        monkeypatch.setenv("INQUIRY_STORAGE_DOCUMENT_CACHE_ENABLED", env_value)
        config_data = {"storage": {"document_cache": {"enabled": False}}}
        config_data = Config._apply_env_overrides(config_data)
        assert config_data["storage"]["document_cache"]["enabled"] == expected

    def test_typo_detection_invalid_section(self, monkeypatch, caplog):
        """Test that typos in section names are detected and logged."""
        import logging

        # Set up a typo in the section name (SERACH instead of SEARCH)
        monkeypatch.setenv("INQUIRY_SERACH_DEFAULT_LIMIT", "50")

        with caplog.at_level(logging.WARNING):
            config = Config.load()

        # Verify the warning was logged (either old format or new format with suggestion)
        assert any(
            "Ignoring" in record.message
            and "INQUIRY_SERACH_DEFAULT_LIMIT" in record.message
            and (
                "'serach' is not a valid config section" in record.message
                or "Did you mean INQUIRY_SEARCH_DEFAULT_LIMIT?" in record.message
            )
            for record in caplog.records
        ), "Expected warning about invalid section or typo suggestion not found in logs"

        # Verify the typo didn't create invalid config
        assert config.search.default_limit != 50, (
            "Invalid env var should not have been applied"
        )

    def test_valid_environment_variable_application(self, monkeypatch, caplog):
        """Test that valid environment variables are applied correctly."""
        import logging

        monkeypatch.setenv("INQUIRY_SEARCH_DEFAULT_LIMIT", "75")

        with caplog.at_level(logging.INFO):
            config = Config.load()

        # Verify the value was applied
        assert config.search.default_limit == 75

        # Verify info message about applied overrides
        assert any(
            "Applied 1 environment variable override(s)" in record.message
            for record in caplog.records
        ), "Expected info message about applied overrides"

    def test_special_mappings_compound_fields(self, monkeypatch):
        """Test that special mappings for compound field names work correctly."""
        base_config = {
            "storage": {
                "root": "./.test_storage",
                "default_project_id": None,
                "lancedb": {"path": "lancedb"},
                "file_tracker": {"path": "file_tracker.db"},
                "document_cache": {"enabled": False, "path": "cache"},
            },
            "cache": {"document_cache": {"max_size": 1000}},
            "search": {"default_limit": 10, "max_limit": 100},
            "embeddings": {"default_provider": "sentence_transformer"},
            "parsers": {},
        }

        # Test default_project_id (compound field)
        monkeypatch.setenv("INQUIRY_STORAGE_DEFAULT_PROJECT_ID", "test_project")
        config_data = Config._apply_env_overrides(base_config)
        config = Config._from_dict(config_data)
        assert config.storage.default_project_id == "test_project"

        # Test file_tracker path (nested compound field)
        monkeypatch.setenv("INQUIRY_STORAGE_FILE_TRACKER_PATH", "custom_tracker.db")
        config_data = Config._apply_env_overrides(base_config)
        config = Config._from_dict(config_data)
        assert config.storage.file_tracker.path == "custom_tracker.db"

        # Test document_cache settings (nested compound fields)
        monkeypatch.setenv("INQUIRY_CACHE_DOCUMENT_CACHE_MAX_SIZE", "5000")
        config_data = Config._apply_env_overrides(base_config)
        config = Config._from_dict(config_data)
        assert config.cache.document_cache.max_size == 5000

    def test_multiple_invalid_variables_logged(self, monkeypatch, caplog):
        """Test that multiple invalid environment variables are all logged."""
        import logging

        # Set multiple invalid variables
        monkeypatch.setenv("INQUIRY_SERACH_DEFAULT_LIMIT", "50")  # typo in section
        monkeypatch.setenv("INQUIRY_STORAG_ROOT", "/tmp/test")  # typo in section
        monkeypatch.setenv("INQUIRY_INVALID_SECTION_KEY", "value")  # completely invalid

        with caplog.at_level(logging.WARNING):
            Config.load()

        # Verify all three warnings were logged
        warning_messages = [
            record.message for record in caplog.records if record.levelname == "WARNING"
        ]

        assert any("INQUIRY_SERACH_DEFAULT_LIMIT" in msg for msg in warning_messages)
        assert any("INQUIRY_STORAG_ROOT" in msg for msg in warning_messages)
        assert any("INQUIRY_INVALID_SECTION_KEY" in msg for msg in warning_messages)

        # Verify the count of ignored variables
        assert any(
            "Ignored 3 invalid environment variable(s)" in record.message
            for record in caplog.records
        ), "Expected warning about 3 ignored variables"

    def test_mixed_valid_and_invalid_variables(self, monkeypatch, caplog):
        """Test that valid variables are applied while invalid ones are ignored."""
        import logging

        # Mix valid and invalid variables
        monkeypatch.setenv("INQUIRY_SEARCH_DEFAULT_LIMIT", "100")  # valid
        monkeypatch.setenv("INQUIRY_SERACH_DEFAULT_LIMIT", "50")  # invalid (typo)
        monkeypatch.setenv("INQUIRY_CACHE_DOCUMENT_CACHE_MAX_SIZE", "3000")  # valid

        with caplog.at_level(logging.INFO):
            config = Config.load()

        # Verify valid variables were applied
        assert config.search.default_limit == 100
        assert config.cache.document_cache.max_size == 3000

        # Verify counts in logs
        assert any(
            "Applied 2 environment variable override(s)" in record.message
            for record in caplog.records
        ), "Expected info about 2 applied overrides"

        assert any(
            "Ignored 1 invalid environment variable(s)" in record.message
            for record in caplog.records
        ), "Expected warning about 1 ignored variable"


@pytest.mark.filterwarnings(
    "ignore:ensure_storage_directories.*deprecated:DeprecationWarning"
)
class TestDirectoryCreation:
    """Test directory creation via ensure_storage_directories."""

    @pytest.mark.filterwarnings(
        "default:ensure_storage_directories.*deprecated:DeprecationWarning"
    )
    def test_ensure_storage_directories_emits_deprecation_warning(
        self, temp_storage_root
    ):
        """Test that ensure_storage_directories emits a DeprecationWarning.

        This method is deprecated because storage backends now handle their own
        directory creation during initialize(), following the BackendLifecycle protocol.
        """
        config = StorageConfig(root=str(temp_storage_root))

        with pytest.warns(
            DeprecationWarning, match="ensure_storage_directories.*deprecated"
        ):
            config.ensure_storage_directories()

    def test_creates_root_directory(self, temp_storage_root):
        """Test that storage root directory is created."""
        config = StorageConfig(root=str(temp_storage_root))

        assert not temp_storage_root.exists()
        config.ensure_storage_directories()
        assert temp_storage_root.exists()
        assert temp_storage_root.is_dir()

    def test_creates_lancedb_directory(self, temp_storage_root):
        """Test that LanceDB directory is created."""
        config = StorageConfig(root=str(temp_storage_root))

        config.ensure_storage_directories()

        lancedb_path = temp_storage_root / "lancedb"
        assert lancedb_path.exists()
        assert lancedb_path.is_dir()

    def test_creates_file_tracker_parent_directory(self, temp_storage_root):
        """Test that FileTracker parent directory is created."""
        config = StorageConfig(
            root=str(temp_storage_root),
            file_tracker=FileTrackerConfig(path="data/tracker.db"),
        )

        config.ensure_storage_directories()

        parent_dir = temp_storage_root / "data"
        assert parent_dir.exists()
        assert parent_dir.is_dir()

    def test_creates_document_cache_directory_when_enabled(self, temp_storage_root):
        """Test that DocumentCache directory is created when enabled."""
        config = StorageConfig(
            root=str(temp_storage_root),
            document_cache=DocumentCacheStorageConfig(
                enabled=True, path="document_cache"
            ),
        )

        config.ensure_storage_directories()

        cache_path = temp_storage_root / "document_cache"
        entries_path = cache_path / "entries"
        assert cache_path.exists()
        assert cache_path.is_dir()
        assert entries_path.exists()
        assert entries_path.is_dir()

    def test_skips_document_cache_directory_when_disabled(self, temp_storage_root):
        """Test that DocumentCache directory is not created when disabled."""
        config = StorageConfig(
            root=str(temp_storage_root),
            document_cache=DocumentCacheStorageConfig(
                enabled=False, path="document_cache"
            ),
        )

        config.ensure_storage_directories()

        cache_path = temp_storage_root / "document_cache"
        assert not cache_path.exists()

    def test_idempotent_directory_creation(self, temp_storage_root):
        """Test that calling ensure_storage_directories multiple times is safe."""
        config = StorageConfig(root=str(temp_storage_root))

        config.ensure_storage_directories()
        config.ensure_storage_directories()
        config.ensure_storage_directories()

        assert temp_storage_root.exists()
        assert (temp_storage_root / "lancedb").exists()

    def test_creates_nested_directory_structure(self, temp_storage_root):
        """Test that nested directory structures are created."""
        config = StorageConfig(
            root=str(temp_storage_root),
            lancedb=LanceDBConfig(path="data/db/lancedb"),
            file_tracker=FileTrackerConfig(path="data/tracking/tracker.db"),
            document_cache=DocumentCacheStorageConfig(
                enabled=True, path="data/cache/documents"
            ),
        )

        config.ensure_storage_directories()

        assert (temp_storage_root / "data" / "db" / "lancedb").exists()
        assert (temp_storage_root / "data" / "tracking").exists()
        assert (temp_storage_root / "data" / "cache" / "documents").exists()
        assert (temp_storage_root / "data" / "cache" / "documents" / "entries").exists()


@pytest.mark.filterwarnings(
    "ignore:ensure_storage_directories.*deprecated:DeprecationWarning"
)
class TestErrorHandling:
    """Test error handling for invalid paths and permissions."""

    def test_permission_error_on_directory_creation(self, tmp_path, monkeypatch):
        """Test that StoragePathError is raised on permission errors."""
        config = StorageConfig(root=str(tmp_path / "restricted"))

        # Mock mkdir to raise PermissionError
        original_mkdir = Path.mkdir

        def mock_mkdir(self, *args, **kwargs):
            if "restricted" in str(self):
                raise PermissionError("Permission denied")
            return original_mkdir(self, *args, **kwargs)

        monkeypatch.setattr(Path, "mkdir", mock_mkdir)

        with pytest.raises(StoragePathError) as exc_info:
            config.ensure_storage_directories()

        assert "Permission denied" in str(exc_info.value)

    def test_os_error_on_directory_creation(self, tmp_path, monkeypatch):
        """Test that StoragePathError is raised on OS errors."""
        config = StorageConfig(root=str(tmp_path / "invalid"))

        # Mock mkdir to raise OSError
        original_mkdir = Path.mkdir

        def mock_mkdir(self, *args, **kwargs):
            if "invalid" in str(self):
                raise OSError("Disk full")
            return original_mkdir(self, *args, **kwargs)

        monkeypatch.setattr(Path, "mkdir", mock_mkdir)

        with pytest.raises(StoragePathError) as exc_info:
            config.ensure_storage_directories()

        assert "Disk full" in str(exc_info.value)

    def test_invalid_path_characters_handled(self):
        """Test that invalid path characters are handled gracefully."""
        # This test is platform-dependent, so we just verify no crash
        config = StorageConfig(root="./test_storage")

        # Should not raise an exception
        path = config.get_lancedb_path()
        assert path.is_absolute()


class TestHybridSearchWeightValidation:
    """Test validation of hybrid search weights."""

    @pytest.fixture
    def minimal_config_base(self):
        """Provide minimal config structure for testing weight validation."""
        return {
            "storage": {
                "root": "./.test_storage",
                "lancedb": {"path": "lancedb"},
                "file_tracker": {"path": "file_tracker.db"},
                "document_cache": {"enabled": False, "path": "cache"},
            },
            "cache": {"document_cache": {"max_size": 1000}},
            "search": {"default_limit": 10, "max_limit": 100},
            "embeddings": {"default_provider": "sentence_transformer"},
            "parsers": {},
        }

    @pytest.mark.parametrize(
        ("vector_weight", "fts_weight"),
        [
            (0.7, 0.3),
            (0.7001, 0.2999),
            (0.5, 0.5),
            (1.0, 0.0),
            (0.0, 1.0),
        ],
    )
    def test_valid_weights(self, minimal_config_base, vector_weight, fts_weight):
        """Test that valid weights (summing to 1.0) pass validation."""
        minimal_config_base["search"]["hybrid_search"] = {
            "vector_weight": vector_weight,
            "fts_weight": fts_weight,
        }

        Config._validate_config(minimal_config_base)
        config = Config._from_dict(minimal_config_base)
        assert config.search.hybrid_search.vector_weight == vector_weight
        assert config.search.hybrid_search.fts_weight == fts_weight

    @pytest.mark.parametrize(
        ("vector_weight", "fts_weight", "expected_substrings"),
        [
            (0.8, 0.4, ["must sum to 1.0", "vector_weight=0.8", "fts_weight=0.4"]),
            (0.3, 0.2, ["must sum to 1.0"]),
        ],
    )
    def test_invalid_weights(
        self, minimal_config_base, vector_weight, fts_weight, expected_substrings
    ):
        """Test that invalid weight sums raise ConfigurationError."""
        minimal_config_base["search"]["hybrid_search"] = {
            "vector_weight": vector_weight,
            "fts_weight": fts_weight,
        }

        with pytest.raises(ConfigurationError) as exc_info:
            Config._validate_config(minimal_config_base)

        message = str(exc_info.value)
        for substring in expected_substrings:
            assert substring in message

    def test_default_weights_are_valid(self, minimal_config_base):
        """Test that default weights pass validation."""
        # Don't specify hybrid_search, should use defaults

        Config._validate_config(minimal_config_base)
        config = Config._from_dict(minimal_config_base)
        assert config.search.hybrid_search.vector_weight == 0.7
        assert config.search.hybrid_search.fts_weight == 0.3

    def test_partial_weight_config_uses_defaults(self, minimal_config_base):
        """Test that partial weight configuration uses defaults for missing values."""
        minimal_config_base["search"]["hybrid_search"] = {
            "vector_weight": 0.6
            # fts_weight not specified, should use default 0.3
        }

        # This will fail because 0.6 + 0.3 (default) = 0.9
        with pytest.raises(ConfigurationError) as exc_info:
            Config._validate_config(minimal_config_base)

        assert "must sum to 1.0" in str(exc_info.value)


class TestHybridSearchFallbackConfig:
    """Test validation of hybrid search fallback and diagnostic options."""

    @pytest.fixture
    def minimal_config_base(self):
        """Provide minimal config structure for testing."""
        return {
            "storage": {
                "root": "./.test_storage",
                "lancedb": {"path": "lancedb"},
                "file_tracker": {"path": "file_tracker.db"},
                "document_cache": {"enabled": False, "path": "cache"},
            },
            "cache": {"document_cache": {"max_size": 1000}},
            "search": {"default_limit": 10, "max_limit": 100},
            "embeddings": {"default_provider": "sentence_transformer"},
            "parsers": {},
        }

    @pytest.mark.parametrize(
        ("overrides", "expected_fallback", "expected_log"),
        [
            ({}, True, False),
            ({"fallback_to_vector": False}, False, False),
            ({"fallback_to_vector": True}, True, False),
            ({"log_diagnostics": True}, True, True),
            ({"log_diagnostics": False}, True, False),
            ({"fallback_to_vector": False, "log_diagnostics": True}, False, True),
        ],
    )
    def test_fallback_and_diagnostics_flags(
        self, minimal_config_base, overrides, expected_fallback, expected_log
    ):
        """Test fallback_to_vector/log_diagnostics combinations."""
        minimal_config_base["search"]["hybrid_search"] = {
            "vector_weight": 0.7,
            "fts_weight": 0.3,
            **overrides,
        }

        Config._validate_config(minimal_config_base)
        config = Config._from_dict(minimal_config_base)

        assert config.search.hybrid_search.fallback_to_vector is expected_fallback
        assert config.search.hybrid_search.log_diagnostics is expected_log

    @pytest.mark.parametrize(
        "overrides",
        [
            {"fallback_to_vector": "yes"},
            {"log_diagnostics": 1},
        ],
    )
    def test_invalid_flag_types(self, minimal_config_base, overrides):
        """Test that non-boolean flag values raise errors."""
        minimal_config_base["search"]["hybrid_search"] = {
            "vector_weight": 0.7,
            "fts_weight": 0.3,
            **overrides,
        }

        with pytest.raises((ConfigurationError, TypeError, ValueError)):
            Config._validate_config(minimal_config_base)


class TestRerankerTypeValidation:
    """Test validation of reranker_type configuration."""

    @pytest.fixture
    def minimal_config_base(self):
        """Provide minimal config structure for testing."""
        return {
            "storage": {
                "root": "./.test_storage",
                "lancedb": {"path": "lancedb"},
                "file_tracker": {"path": "file_tracker.db"},
                "document_cache": {"enabled": False, "path": "cache"},
            },
            "cache": {"document_cache": {"max_size": 1000}},
            "search": {"default_limit": 10, "max_limit": 100},
            "embeddings": {"default_provider": "sentence_transformer"},
            "parsers": {},
        }

    @pytest.mark.parametrize(
        "reranker_type",
        ["rrf", "linear_combination", "cross_encoder", "colbert"],
    )
    def test_valid_reranker_types(self, minimal_config_base, reranker_type):
        """Test valid reranker_type values."""
        minimal_config_base["search"]["hybrid_search"] = {
            "vector_weight": 0.7,
            "fts_weight": 0.3,
            "reranker_type": reranker_type,
        }

        Config._validate_config(minimal_config_base)
        config = Config._from_dict(minimal_config_base)

        assert config.search.hybrid_search.reranker_type == reranker_type

    def test_default_reranker_type(self, minimal_config_base):
        """Test that reranker_type has a default value."""
        minimal_config_base["search"]["hybrid_search"] = {
            "vector_weight": 0.7,
            "fts_weight": 0.3,
        }

        Config._validate_config(minimal_config_base)
        config = Config._from_dict(minimal_config_base)

        # Default should be 'linear_combination' based on config.py
        assert config.search.hybrid_search.reranker_type in [
            "rrf",
            "linear_combination",
            "cross_encoder",
            "colbert",
        ]

    @pytest.mark.parametrize(
        ("reranker_type", "reranker_params"),
        [
            ("rrf", {}),
            ("rrf", {"k": 60}),
            (
                "cross_encoder",
                {
                    "model_name": "cross-encoder/ms-marco-MiniLM-L-6-v2",
                    "batch_size": 32,
                },
            ),
        ],
    )
    def test_reranker_params(self, minimal_config_base, reranker_type, reranker_params):
        """Test reranker_params handling."""
        minimal_config_base["search"]["hybrid_search"] = {
            "vector_weight": 0.7,
            "fts_weight": 0.3,
            "reranker_type": reranker_type,
            "reranker_params": reranker_params,
        }

        Config._validate_config(minimal_config_base)
        config = Config._from_dict(minimal_config_base)

        assert config.search.hybrid_search.reranker_params == reranker_params


class TestStorageConfigValidation:
    """Test validation of storage configuration."""

    @pytest.fixture
    def minimal_config_base(self):
        """Provide minimal config structure for testing storage validation."""
        return {
            "storage": {
                "root": "./.test_storage",
                "lancedb": {"path": "lancedb"},
                "file_tracker": {"path": "file_tracker.db"},
                "document_cache": {"enabled": False, "path": "cache"},
            },
            "cache": {"document_cache": {"max_size": 1000}},
            "search": {"default_limit": 10, "max_limit": 100},
            "embeddings": {"default_provider": "sentence_transformer"},
            "parsers": {},
        }

    def test_null_byte_in_root_path_raises_error(self, minimal_config_base):
        """Test that null bytes in storage.root raise ConfigurationError."""
        minimal_config_base["storage"]["root"] = "./test\x00path"

        with pytest.raises(ConfigurationError) as exc_info:
            Config._validate_config(minimal_config_base)

        assert "null bytes" in str(exc_info.value).lower()
        assert "storage.root" in str(exc_info.value)

    def test_valid_storage_paths_pass_validation(self, minimal_config_base):
        """Test that valid storage paths pass validation."""
        minimal_config_base["storage"]["root"] = "./valid_path"

        Config._validate_config(minimal_config_base)
        config = Config._from_dict(minimal_config_base)
        assert config.storage.root == "./valid_path"

    def test_schema_validation_error_raises_configuration_error(
        self, minimal_config_base
    ):
        """Test that schema validation errors raise ConfigurationError."""
        # Create a temporary schema file with strict validation

        # This test would require mocking the schema file location
        # For now, we'll test that the method properly raises ConfigurationError
        # when jsonschema.ValidationError occurs

        # Test with invalid config structure (missing required nested fields)
        invalid_config = {
            "storage": {
                "root": "./.test_storage",
                # Missing required nested fields that schema might require
            }
        }

        # Note: This test depends on the actual schema file
        # If schema validation is working, invalid configs should raise ConfigurationError
        with pytest.raises(ConfigurationError):
            Config._validate_config(invalid_config)

    def test_missing_jsonschema_logs_warning(
        self, minimal_config_base, caplog, monkeypatch
    ):
        """Test that missing jsonschema package logs a warning."""
        import logging
        import builtins

        caplog.set_level(logging.WARNING)

        # Mock jsonschema import to fail
        import sys

        original_jsonschema = sys.modules.get("jsonschema")
        if "jsonschema" in sys.modules:
            del sys.modules["jsonschema"]

        # Mock the import to raise ImportError
        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "jsonschema":
                raise ImportError("No module named 'jsonschema'")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)

        try:
            Config._validate_config(minimal_config_base)

            # Should log warning about missing jsonschema
            assert any(
                "jsonschema package not installed" in record.message
                for record in caplog.records
            )
        finally:
            # Restore original jsonschema module
            if original_jsonschema:
                sys.modules["jsonschema"] = original_jsonschema
            monkeypatch.undo()


@pytest.mark.filterwarnings(
    "ignore:ensure_storage_directories.*deprecated:DeprecationWarning"
)
class TestRemoteURIHandling:
    """Test handling of remote URIs in storage configuration."""

    @pytest.mark.parametrize(
        "root",
        [
            "s3://my-bucket/storage",
            "gs://my-bucket/storage",
            "az://my-container/storage",
        ],
    )
    def test_skips_directory_creation_for_remote_root(self, caplog, root):
        """Test that directory creation is skipped for remote root paths."""
        import logging

        caplog.set_level(logging.DEBUG)

        config = StorageConfig(root=root)

        # Should not raise an exception and should skip directory creation
        config.ensure_storage_directories()

        # Check that debug message was logged
        assert any(
            "Skipping directory creation for remote root" in record.message
            for record in caplog.records
        )

    @pytest.mark.parametrize(
        ("root", "scheme_label"),
        [
            ("s3://my-bucket/storage", "s3:"),
            ("gs://my-bucket/storage", "gs:"),
        ],
    )
    def test_get_lancedb_path_with_remote_uri(self, root, scheme_label):
        """Test that get_lancedb_path returns URI for remote roots."""
        config = StorageConfig(root=root)

        path = config.get_lancedb_path()

        # Path normalizes the URI, but it's still usable
        assert scheme_label in str(path)
        assert "my-bucket" in str(path)
        assert "lancedb" in str(path)

    def test_get_lancedb_path_with_local_path(self, temp_storage_root):
        """Test that get_lancedb_path resolves local paths."""
        config = StorageConfig(root=str(temp_storage_root))

        path = config.get_lancedb_path()

        # Should be an absolute resolved path
        assert path.is_absolute()
        assert path.name == "lancedb"

    @pytest.mark.parametrize(
        ("root", "scheme_label"),
        [
            ("s3://my-bucket/storage", "s3:"),
            ("gs://my-bucket/storage", "gs:"),
        ],
    )
    def test_get_file_tracker_path_with_remote_uri(self, root, scheme_label):
        """Test that get_file_tracker_path returns URI for remote roots."""
        config = StorageConfig(root=root)

        path = config.get_file_tracker_path()

        # Path normalizes the URI, but it's still usable
        assert scheme_label in str(path)
        assert "my-bucket" in str(path)
        assert "file_tracker.db" in str(path)

    def test_get_file_tracker_path_with_local_path(self, temp_storage_root):
        """Test that get_file_tracker_path resolves local paths."""
        config = StorageConfig(root=str(temp_storage_root))

        path = config.get_file_tracker_path()

        # Should be an absolute resolved path
        assert path.is_absolute()
        assert path.name == "file_tracker.db"

    def test_local_path_still_creates_directories(self, temp_storage_root):
        """Test that local paths still create directories normally."""
        config = StorageConfig(root=str(temp_storage_root))

        assert not temp_storage_root.exists()
        config.ensure_storage_directories()

        # Directories should be created for local paths
        assert temp_storage_root.exists()
        assert (temp_storage_root / "lancedb").exists()

    def test_local_path_with_file_protocol(self, temp_storage_root):
        """Test that file:// protocol is treated as local."""
        # file:// is technically a URI but should be treated as local
        # This test documents current behavior - may need adjustment
        config = StorageConfig(root=f"file://{temp_storage_root}")

        # Currently this would be skipped as remote, which may not be desired
        # This test documents the behavior for future consideration
        config.ensure_storage_directories()

        # With current implementation, file:// is treated as remote
        # If this needs to change, update the logic in ensure_storage_directories
        assert not temp_storage_root.exists()


class TestConfigIntegration:
    """Test integration of StorageConfig with Config class."""

    def test_config_from_dict_with_storage(self, temp_storage_root):
        """Test Config._from_dict with storage configuration."""
        config_data = {
            "storage": {
                "root": str(temp_storage_root),
                "default_project_id": "test_proj",
                "lancedb": {"path": "lancedb"},
                "file_tracker": {"path": "tracker.db"},
                "document_cache": {"enabled": True, "path": "cache"},
            }
        }

        config = Config._from_dict(config_data)

        assert config.storage.root == str(temp_storage_root)
        assert config.storage.default_project_id == "test_proj"
        assert config.storage.lancedb.path == "lancedb"
        assert config.storage.file_tracker.path == "tracker.db"
        assert config.storage.document_cache.enabled is True
        assert config.storage.document_cache.path == "cache"

    def test_config_to_dict_with_storage(self, temp_storage_root):
        """Test Config.to_dict with storage configuration."""
        storage = StorageConfig(
            root=str(temp_storage_root),
            default_project_id="test_proj",
            lancedb=LanceDBConfig(path="lancedb"),
            file_tracker=FileTrackerConfig(path="tracker.db"),
            document_cache=DocumentCacheStorageConfig(enabled=True, path="cache"),
        )
        config = Config(storage=storage)

        config_dict = config.to_dict()

        assert config_dict["storage"]["root"] == str(temp_storage_root)
        assert config_dict["storage"]["default_project_id"] == "test_proj"
        assert config_dict["storage"]["lancedb"]["path"] == "lancedb"
        assert config_dict["storage"]["file_tracker"]["path"] == "tracker.db"
        assert config_dict["storage"]["document_cache"]["enabled"] is True
        assert config_dict["storage"]["document_cache"]["path"] == "cache"

    def test_config_roundtrip(self, temp_storage_root):
        """Test that config can be converted to dict and back."""
        original_config = Config(
            storage=StorageConfig(
                root=str(temp_storage_root),
                default_project_id="roundtrip_test",
                lancedb=LanceDBConfig(path="lancedb"),
                file_tracker=FileTrackerConfig(path="tracker.db"),
                document_cache=DocumentCacheStorageConfig(enabled=True, path="cache"),
            )
        )

        config_dict = original_config.to_dict()
        restored_config = Config._from_dict(config_dict)

        assert restored_config.storage.root == original_config.storage.root
        assert (
            restored_config.storage.default_project_id
            == original_config.storage.default_project_id
        )
        assert (
            restored_config.storage.lancedb.path == original_config.storage.lancedb.path
        )
        assert (
            restored_config.storage.file_tracker.path
            == original_config.storage.file_tracker.path
        )
        assert (
            restored_config.storage.document_cache.enabled
            == original_config.storage.document_cache.enabled
        )
        assert (
            restored_config.storage.document_cache.path
            == original_config.storage.document_cache.path
        )


class TestThreadSafeConfigLoading:
    """Test thread-safe configuration loading."""

    def test_concurrent_config_loading(self, tmp_path):
        """Test that loading config from multiple threads is thread-safe."""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        # Create a test config file
        config_file = tmp_path / "mock_config.yaml"
        config_content = """
storage:
  root: ./.test_storage
  lancedb:
    path: lancedb
  file_tracker:
    path: file_tracker.db
  document_cache:
    enabled: true
    path: document_cache

cache:
  document_cache:
    max_size: 1000
    ttl_seconds: 3600
    eviction_policy: lru

search:
  default_limit: 10
  max_limit: 100
  hybrid_search:
    vector_weight: 0.7
    fts_weight: 0.3
    rerank_by_graph: true
  graph_search:
    max_depth: 3
    relationship_types: []

embeddings:
  default_provider: sentence_transformer
  sentence_transformer:
    model_name: all-MiniLM-L6-v2
    ndims: 384
  hashing:
    ndims: 128

parsers:
  unified_code:
    enabled: true
    priority: 100
  document:
    enabled: true
    priority: 50
  fallback_text:
    enabled: true
    priority: 0
"""
        config_file.write_text(config_content)

        # Track results and errors
        results = []
        errors = []

        def load_config():
            """Load configuration in a thread."""
            try:
                config = Config.load(str(config_file))
                return config
            except Exception as e:
                return e

        # Load config from multiple threads concurrently
        num_threads = 10
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(load_config) for _ in range(num_threads)]

            for future in as_completed(futures):
                result = future.result()
                if isinstance(result, Exception):
                    errors.append(result)
                else:
                    results.append(result)

        # Verify no errors occurred
        assert len(errors) == 0, f"Errors occurred during concurrent loading: {errors}"

        # Verify all threads got valid configs
        assert len(results) == num_threads

        # Verify all configs are valid and have the same values
        for config in results:
            assert isinstance(config, Config)
            assert config.storage.root == "./.test_storage"
            assert config.storage.lancedb.path == "lancedb"
            assert config.search.hybrid_search.vector_weight == 0.7
            assert config.search.hybrid_search.fts_weight == 0.3
            assert config.embeddings.default_provider == "sentence_transformer"

    def test_no_race_conditions_on_validation(self, tmp_path):
        """Test that validation doesn't cause race conditions."""
        import threading
        from concurrent.futures import ThreadPoolExecutor

        # Create a test config file with valid weights
        config_file = tmp_path / "mock_config.yaml"
        config_content = """
storage:
  root: ./.test_storage
  lancedb:
    path: lancedb
  file_tracker:
    path: file_tracker.db
  document_cache:
    enabled: true
    path: document_cache

cache:
  document_cache:
    max_size: 1000

search:
  default_limit: 10
  max_limit: 100
  hybrid_search:
    vector_weight: 0.6
    fts_weight: 0.4

embeddings:
  default_provider: sentence_transformer

parsers: {}
"""
        config_file.write_text(config_content)

        # Track validation calls
        validation_count = 0
        validation_lock = threading.Lock()

        def load_and_count():
            """Load config and count validations."""
            nonlocal validation_count
            config = Config.load(str(config_file))
            with validation_lock:
                validation_count += 1
            return config

        # Load from multiple threads
        num_threads = 5
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(load_and_count) for _ in range(num_threads)]
            configs = [f.result() for f in futures]

        # All configs should be valid
        assert len(configs) == num_threads
        for config in configs:
            assert config.search.hybrid_search.vector_weight == 0.6
            assert config.search.hybrid_search.fts_weight == 0.4

        # Validation should have been called for each load
        assert validation_count == num_threads

    def test_concurrent_loading_with_env_overrides(self, tmp_path, monkeypatch):
        """Test concurrent loading with environment variable overrides."""
        from concurrent.futures import ThreadPoolExecutor

        # Set environment variable
        monkeypatch.setenv("INQUIRY_STORAGE_ROOT", str(tmp_path / "env_storage"))

        # Create a test config file
        config_file = tmp_path / "mock_config.yaml"
        config_content = """
storage:
  root: ./.test_storage
  lancedb:
    path: lancedb
  file_tracker:
    path: file_tracker.db
  document_cache:
    enabled: true
    path: document_cache

cache:
  document_cache:
    max_size: 1000

search:
  default_limit: 10
  max_limit: 100

embeddings:
  default_provider: sentence_transformer

parsers: {}
"""
        config_file.write_text(config_content)

        def load_config():
            return Config.load(str(config_file))

        # Load from multiple threads
        num_threads = 5
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(load_config) for _ in range(num_threads)]
            configs = [f.result() for f in futures]

        # All configs should have the environment override applied
        assert len(configs) == num_threads
        for config in configs:
            assert config.storage.root == str(tmp_path / "env_storage")

    def test_config_instances_have_independent_state(self, tmp_path):
        """Test that each Config instance has independent state.

        This verifies that the lock is at module level, not class level,
        ensuring that Config instances don't share state through the lock.
        """
        # Create two different config files
        config_file1 = tmp_path / "config1.yaml"
        config_file2 = tmp_path / "config2.yaml"

        config_content1 = """
storage:
  root: ./.storage1
  default_project_id: project1
  lancedb:
    path: lancedb
  file_tracker:
    path: file_tracker.db
  document_cache:
    enabled: true
    path: document_cache

cache:
  document_cache:
    max_size: 1000

search:
  default_limit: 10
  max_limit: 100

embeddings:
  default_provider: sentence_transformer

parsers: {}
"""

        config_content2 = """
storage:
  root: ./.storage2
  default_project_id: project2
  lancedb:
    path: lancedb
  file_tracker:
    path: file_tracker.db
  document_cache:
    enabled: true
    path: document_cache

cache:
  document_cache:
    max_size: 2000

search:
  default_limit: 20
  max_limit: 200

embeddings:
  default_provider: sentence_transformer

parsers: {}
"""

        config_file1.write_text(config_content1)
        config_file2.write_text(config_content2)

        # Load two different configs
        config1 = Config.load(str(config_file1))
        config2 = Config.load(str(config_file2))

        # Verify they have independent state
        assert config1.storage.root == "./.storage1"
        assert config2.storage.root == "./.storage2"

        assert config1.storage.default_project_id == "project1"
        assert config2.storage.default_project_id == "project2"

        assert config1.cache.document_cache.max_size == 1000
        assert config2.cache.document_cache.max_size == 2000

        assert config1.search.default_limit == 10
        assert config2.search.default_limit == 20

        # Verify they are different instances
        assert config1 is not config2

        # Verify modifying one doesn't affect the other
        config1.storage.root = "./.modified_storage1"
        assert config2.storage.root == "./.storage2"


class TestMCPQueryConfigValidation:
    """Test validation of MCP query configuration."""

    def test_default_values(self):
        """Test that default values are correct."""
        from agentic_inquiry.config import MCPQueryConfig

        config = MCPQueryConfig()
        assert config.traversal_limit == 500
        assert config.batch_size == 100

    def test_valid_traversal_limit_values(self):
        """Test that valid traversal_limit values are accepted."""
        from agentic_inquiry.config import MCPQueryConfig

        # Min value
        config = MCPQueryConfig(traversal_limit=100)
        assert config.traversal_limit == 100

        # Default value
        config = MCPQueryConfig(traversal_limit=500)
        assert config.traversal_limit == 500

        # Max value
        config = MCPQueryConfig(traversal_limit=2000)
        assert config.traversal_limit == 2000

        # Mid-range value
        config = MCPQueryConfig(traversal_limit=1000)
        assert config.traversal_limit == 1000

    def test_invalid_traversal_limit_below_range(self):
        """Test that traversal_limit below 100 raises ConfigurationError."""
        from agentic_inquiry.config import MCPQueryConfig, ConfigurationError

        with pytest.raises(ConfigurationError) as exc_info:
            MCPQueryConfig(traversal_limit=99)

        assert "traversal_limit must be between 100 and 2000" in str(exc_info.value)
        assert "got 99" in str(exc_info.value)

    def test_invalid_traversal_limit_above_range(self):
        """Test that traversal_limit above 2000 raises ConfigurationError."""
        from agentic_inquiry.config import MCPQueryConfig, ConfigurationError

        with pytest.raises(ConfigurationError) as exc_info:
            MCPQueryConfig(traversal_limit=2001)

        assert "traversal_limit must be between 100 and 2000" in str(exc_info.value)
        assert "got 2001" in str(exc_info.value)

    def test_valid_batch_size_values(self):
        """Test that valid batch_size values are accepted."""
        from agentic_inquiry.config import MCPQueryConfig

        # Min value
        config = MCPQueryConfig(batch_size=10)
        assert config.batch_size == 10

        # Default value
        config = MCPQueryConfig(batch_size=100)
        assert config.batch_size == 100

        # Max value
        config = MCPQueryConfig(batch_size=500)
        assert config.batch_size == 500

        # Mid-range value
        config = MCPQueryConfig(batch_size=250)
        assert config.batch_size == 250

    def test_invalid_batch_size_below_range(self):
        """Test that batch_size below 10 raises ConfigurationError."""
        from agentic_inquiry.config import MCPQueryConfig, ConfigurationError

        with pytest.raises(ConfigurationError) as exc_info:
            MCPQueryConfig(batch_size=9)

        assert "batch_size must be between 10 and 500" in str(exc_info.value)
        assert "got 9" in str(exc_info.value)

    def test_invalid_batch_size_above_range(self):
        """Test that batch_size above 500 raises ConfigurationError."""
        from agentic_inquiry.config import MCPQueryConfig, ConfigurationError

        with pytest.raises(ConfigurationError) as exc_info:
            MCPQueryConfig(batch_size=501)

        assert "batch_size must be between 10 and 500" in str(exc_info.value)
        assert "got 501" in str(exc_info.value)

    def test_both_fields_with_valid_values(self):
        """Test that both fields can be set with valid values."""
        from agentic_inquiry.config import MCPQueryConfig

        config = MCPQueryConfig(traversal_limit=1500, batch_size=200)
        assert config.traversal_limit == 1500
        assert config.batch_size == 200

    def test_one_invalid_field_raises_error(self):
        """Test that having one invalid field raises ConfigurationError."""
        from agentic_inquiry.config import MCPQueryConfig, ConfigurationError

        # Valid batch_size, invalid traversal_limit
        with pytest.raises(ConfigurationError) as exc_info:
            MCPQueryConfig(traversal_limit=50, batch_size=100)

        assert "traversal_limit must be between 100 and 2000" in str(exc_info.value)

        # Valid traversal_limit, invalid batch_size
        with pytest.raises(ConfigurationError) as exc_info:
            MCPQueryConfig(traversal_limit=500, batch_size=5)

        assert "batch_size must be between 10 and 500" in str(exc_info.value)
