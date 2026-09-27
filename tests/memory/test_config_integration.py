"""Integration tests for configuration system with memory."""

import pytest

pytestmark = pytest.mark.integration

import os
import tempfile
from pathlib import Path

import yaml

from agentic_inquiry.config import Config
from agentic_inquiry.memory import MemorySystem


class TestConfigLoading:
    """Test configuration loading from YAML."""

    def test_load_default_memory_config(self):
        """Test loading default memory configuration."""
        config = Config.load()

        # Verify memory config exists
        assert config.memory is not None

        # Verify working memory config
        assert config.memory.working_memory.capacity == 20
        assert config.memory.working_memory.eviction_policy == "lru"

        # Verify episodic memory config
        assert config.memory.episodic_memory.capacity == 1000
        assert config.memory.episodic_memory.table_name == "memory_episodic_medium"

        # Verify semantic memory config
        assert config.memory.semantic_memory.capacity == 500
        assert config.memory.semantic_memory.table_name == "memory_semantic_high"

        # Verify consolidation config
        assert config.memory.consolidation.enabled is True
        assert config.memory.consolidation.interval_seconds == 300
        assert config.memory.consolidation.episodic_threshold == 0.8
        assert config.memory.consolidation.semantic_threshold == 0.9

        # Verify retrieval config
        assert config.memory.retrieval.default_strategy == "adaptive"
        assert config.memory.retrieval.cache_enabled is True
        assert config.memory.retrieval.cache_ttl_seconds == 300

        # Verify ranking weights
        weights = config.memory.retrieval.ranking_weights
        assert weights["relevance"] == 0.5
        assert weights["recency"] == 0.3
        assert weights["importance"] == 0.2
        assert sum(weights.values()) == pytest.approx(1.0)

    def test_load_custom_config_file(self):
        """Test loading custom configuration file."""
        # Load default config as base
        import yaml as yaml_lib

        default_config_path = (
            Path(__file__).parent.parent.parent / "config" / "default.yaml"
        )
        with open(default_config_path, "r") as f:
            custom_config = yaml_lib.safe_load(f)

        # Override specific values for testing
        custom_config["memory"]["working_memory"]["capacity"] = 50
        custom_config["memory"]["episodic_memory"]["capacity"] = 2000
        custom_config["memory"]["semantic_memory"]["capacity"] = 1000
        custom_config["memory"]["consolidation"]["enabled"] = False
        custom_config["memory"]["consolidation"]["interval_seconds"] = 600
        custom_config["memory"]["consolidation"]["episodic_threshold"] = 0.7
        custom_config["memory"]["consolidation"]["semantic_threshold"] = 0.85
        custom_config["memory"]["retrieval"]["default_strategy"] = "recency"
        custom_config["memory"]["retrieval"]["cache_enabled"] = False
        custom_config["memory"]["retrieval"]["cache_ttl_seconds"] = 600
        custom_config["memory"]["retrieval"]["cache_size"] = 500
        custom_config["memory"]["retrieval"]["ranking_weights"] = {
            "relevance": 0.4,
            "recency": 0.4,
            "importance": 0.2,
        }
        custom_config["memory"]["summary"]["auto_threshold"] = 200

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(custom_config, f)
            config_path = f.name

        try:
            config = Config.load(config_path)

            # Verify custom values
            assert config.memory.working_memory.capacity == 50
            assert config.memory.episodic_memory.capacity == 2000
            assert config.memory.consolidation.enabled is False
            assert config.memory.retrieval.default_strategy == "recency"
            assert config.memory.retrieval.cache_enabled is False
        finally:
            os.unlink(config_path)


class TestEnvironmentVariableOverrides:
    """Test environment variable overrides."""

    def test_memory_capacity_override(self, monkeypatch):
        """Test overriding memory capacity via environment variables."""
        # Set environment variables
        monkeypatch.setenv("INQUIRY_MEMORY_WORKING_MEMORY_CAPACITY", "100")
        monkeypatch.setenv("INQUIRY_MEMORY_EPISODIC_MEMORY_CAPACITY", "5000")
        monkeypatch.setenv("INQUIRY_MEMORY_SEMANTIC_MEMORY_CAPACITY", "2500")

        config = Config.load()

        # Verify overrides
        assert config.memory.working_memory.capacity == 100
        assert config.memory.episodic_memory.capacity == 5000
        assert config.memory.semantic_memory.capacity == 2500

    def test_consolidation_override(self, monkeypatch):
        """Test overriding consolidation settings via environment variables."""
        monkeypatch.setenv("INQUIRY_MEMORY_CONSOLIDATION_ENABLED", "false")
        monkeypatch.setenv("INQUIRY_MEMORY_CONSOLIDATION_INTERVAL_SECONDS", "600")
        monkeypatch.setenv("INQUIRY_MEMORY_CONSOLIDATION_EPISODIC_THRESHOLD", "0.75")

        config = Config.load()

        # Verify overrides
        assert config.memory.consolidation.enabled is False
        assert config.memory.consolidation.interval_seconds == 600
        assert config.memory.consolidation.episodic_threshold == 0.75

    def test_retrieval_override(self, monkeypatch):
        """Test overriding retrieval settings via environment variables."""
        monkeypatch.setenv("INQUIRY_MEMORY_RETRIEVAL_DEFAULT_STRATEGY", "importance")
        monkeypatch.setenv("INQUIRY_MEMORY_RETRIEVAL_CACHE_ENABLED", "false")
        monkeypatch.setenv("INQUIRY_MEMORY_RETRIEVAL_CACHE_TTL_SECONDS", "600")

        config = Config.load()

        # Verify overrides
        assert config.memory.retrieval.default_strategy == "importance"
        assert config.memory.retrieval.cache_enabled is False
        assert config.memory.retrieval.cache_ttl_seconds == 600


class TestConfigValidation:
    """Test configuration validation."""

    def test_invalid_ranking_weights_sum(self):
        """Test that ranking weights that don't sum to 1.0 raise ConfigurationError."""
        # Load default config as base
        import yaml as yaml_lib
        from agentic_inquiry.exceptions import ConfigurationError

        default_config_path = (
            Path(__file__).parent.parent.parent / "config" / "default.yaml"
        )
        with open(default_config_path, "r") as f:
            invalid_config = yaml_lib.safe_load(f)

        # Override with invalid ranking weights (sum > 1.0)
        invalid_config["memory"]["retrieval"]["ranking_weights"] = {
            "relevance": 0.5,
            "recency": 0.5,
            "importance": 0.5,  # Sum = 1.5, should raise error
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(invalid_config, f)
            config_path = f.name

        try:
            # Should raise ConfigurationError for invalid weights
            with pytest.raises(ConfigurationError, match="must sum to 1.0"):
                Config.load(config_path)
        finally:
            os.unlink(config_path)

    def test_invalid_threshold_values(self):
        """Test that threshold values must be between 0.0 and 1.0."""
        # Load default config as base
        import yaml as yaml_lib
        from agentic_inquiry.exceptions import ConfigurationError

        default_config_path = (
            Path(__file__).parent.parent.parent / "config" / "default.yaml"
        )
        with open(default_config_path, "r") as f:
            invalid_config = yaml_lib.safe_load(f)

        # Override with invalid threshold (> 1.0)
        invalid_config["memory"]["consolidation"]["episodic_threshold"] = 1.5

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(invalid_config, f)
            config_path = f.name

        try:
            # Should raise ConfigurationError due to schema validation
            with pytest.raises(
                ConfigurationError, match="1.5 is greater than the maximum"
            ):
                Config.load(config_path)
        finally:
            os.unlink(config_path)


class TestDefaultValues:
    """Test default configuration values."""

    def test_memory_defaults(self):
        """Test that memory config has sensible defaults."""
        config = Config.load()

        # Working memory defaults
        assert config.memory.working_memory.capacity > 0
        assert config.memory.working_memory.eviction_policy in ["lru", "lfu"]

        # Episodic memory defaults
        assert config.memory.episodic_memory.capacity > 0
        assert config.memory.episodic_memory.table_name

        # Semantic memory defaults
        assert config.memory.semantic_memory.capacity > 0
        assert config.memory.semantic_memory.table_name

        # Consolidation defaults
        assert isinstance(config.memory.consolidation.enabled, bool)
        assert config.memory.consolidation.interval_seconds > 0
        assert 0.0 <= config.memory.consolidation.episodic_threshold <= 1.0
        assert 0.0 <= config.memory.consolidation.semantic_threshold <= 1.0

        # Retrieval defaults
        assert config.memory.retrieval.default_strategy in [
            "relevance",
            "recency",
            "importance",
            "adaptive",
        ]
        assert isinstance(config.memory.retrieval.cache_enabled, bool)
        assert config.memory.retrieval.cache_ttl_seconds > 0

    def test_backward_compatibility(self):
        """Test that legacy config still works."""
        config = Config.load()

        # Legacy sentence_transformer config should exist
        assert config.embeddings.sentence_transformer is not None
        assert config.embeddings.sentence_transformer.model_name
        assert config.embeddings.sentence_transformer.ndims > 0

        # Legacy hashing config should exist
        assert config.embeddings.hashing is not None
        assert config.embeddings.hashing.ndims > 0


class TestConfigIntegrationWithMemorySystem:
    """Test configuration integration with MemorySystem."""

    @pytest.mark.asyncio
    async def test_memory_system_uses_config(self):
        """Test that MemorySystem correctly uses configuration."""
        config = Config.load()

        # Create memory system (don't initialize to avoid DB setup)
        from agentic_inquiry.embeddings import EmbeddingService

        embedding_service = EmbeddingService(config)

        memory_system = MemorySystem(config=config, embedding_service=embedding_service)

        # Verify config is used
        assert memory_system.config == config
        assert (
            memory_system.working_memory.capacity
            == config.memory.working_memory.capacity
        )

    @pytest.mark.asyncio
    async def test_custom_config_affects_behavior(self):
        """Test that custom config affects memory system behavior."""
        # Load default config as base
        import yaml as yaml_lib

        default_config_path = (
            Path(__file__).parent.parent.parent / "config" / "default.yaml"
        )
        with open(default_config_path, "r") as f:
            custom_config = yaml_lib.safe_load(f)

        # Override with small capacity for testing
        custom_config["memory"]["working_memory"]["capacity"] = 5

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(custom_config, f)
            config_path = f.name

        try:
            config = Config.load(config_path)

            # Verify config has the custom value
            assert config.memory.working_memory.capacity == 5

            from agentic_inquiry.embeddings import EmbeddingService

            embedding_service = EmbeddingService(config)

            memory_system = MemorySystem(
                config=config, embedding_service=embedding_service
            )

            # Verify custom capacity is actually used by the memory system
            assert memory_system.working_memory.capacity == 5
        finally:
            os.unlink(config_path)
