"""Integration tests for maintenance configuration persistence.

Tests that maintenance configuration:
- Persists across sessions (AC-4.1)
- Respects cleanup_retention_minutes setting (AC-4.3)
- Validates configuration values correctly
"""

import os
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import yaml

pytestmark = pytest.mark.integration

from agentic_inquiry.config import Config, MaintenanceConfig, ConfigurationError
from agentic_inquiry.mcp.services.maintenance_manager import MaintenanceManager


@pytest.fixture
def temp_config_file(tmp_path):
    """Create a temporary config file."""
    config_file = tmp_path / "agentic-inquiry.yaml"
    yield config_file
    # Cleanup
    if config_file.exists():
        config_file.unlink()


@pytest.fixture
def sample_config_data():
    """Sample configuration data with maintenance settings."""
    # Load default config first to get all required sections
    config = Config.load()
    config_dict = config.to_dict()

    # Modify maintenance settings for testing
    config_dict["maintenance"] = {
        "enabled": True,
        "trigger": "project.closed",
        "cleanup_retention_minutes": 120,
    }

    return config_dict


class TestConfigPersistence:
    """Tests for configuration persistence (AC-4.1)."""

    def test_config_persistence_across_sessions(
        self, temp_config_file, sample_config_data
    ):
        """Test maintenance config persists across sessions (AC-4.1)."""
        # Write config to file
        with open(temp_config_file, "w") as f:
            yaml.dump(sample_config_data, f)

        # Load config in "session 1"
        config1 = Config.load(str(temp_config_file))

        # Verify maintenance config loaded
        assert config1.maintenance.enabled is True
        assert config1.maintenance.trigger == "project.closed"
        assert config1.maintenance.cleanup_retention_minutes == 120

        # Simulate session restart - load config again in "session 2"
        config2 = Config.load(str(temp_config_file))

        # Config should be identical (persisted)
        assert config2.maintenance.enabled == config1.maintenance.enabled
        assert config2.maintenance.trigger == config1.maintenance.trigger
        assert (
            config2.maintenance.cleanup_retention_minutes
            == config1.maintenance.cleanup_retention_minutes
        )

    def test_config_updates_persist(self, temp_config_file, sample_config_data):
        """Test configuration updates persist to disk."""
        # Write initial config
        with open(temp_config_file, "w") as f:
            yaml.dump(sample_config_data, f)

        # Load config
        config = Config.load(str(temp_config_file))
        assert config.maintenance.cleanup_retention_minutes == 120

        # Update config data
        sample_config_data["maintenance"]["cleanup_retention_minutes"] = 240

        # Write updated config
        with open(temp_config_file, "w") as f:
            yaml.dump(sample_config_data, f)

        # Reload config
        config_reloaded = Config.load(str(temp_config_file))

        # Updated value should persist
        assert config_reloaded.maintenance.cleanup_retention_minutes == 240

    def test_missing_maintenance_config_uses_defaults(self, temp_config_file):
        """Test missing maintenance section uses default values."""
        # Load base config and remove maintenance section
        base_config = Config.load()
        config_data = base_config.to_dict()
        config_data.pop("maintenance", None)  # Remove maintenance section

        with open(temp_config_file, "w") as f:
            yaml.dump(config_data, f)

        # Load config
        config = Config.load(str(temp_config_file))

        # Should use MaintenanceConfig defaults
        assert config.maintenance.enabled is True
        assert config.maintenance.trigger == "project.closed"
        assert config.maintenance.cleanup_retention_minutes == 60

    def test_partial_maintenance_config_merges_with_defaults(self, temp_config_file):
        """Test partial maintenance config merges with defaults."""
        # Load base config and modify partial maintenance settings
        base_config = Config.load()
        config_data = base_config.to_dict()
        config_data["maintenance"] = {
            "cleanup_retention_minutes": 240
            # enabled and trigger not specified - should use defaults
        }

        with open(temp_config_file, "w") as f:
            yaml.dump(config_data, f)

        # Load config
        config = Config.load(str(temp_config_file))

        # Should merge with defaults
        assert config.maintenance.cleanup_retention_minutes == 240  # Specified
        assert config.maintenance.enabled is True  # Default
        assert config.maintenance.trigger == "project.closed"  # Default


class TestCleanupRetentionMinutes:
    """Tests for cleanup_retention_minutes setting (AC-4.3)."""

    @pytest.mark.asyncio
    async def test_cleanup_retention_minutes_respected(self):
        """Test cleanup_retention_minutes is passed to maintenance (AC-4.3)."""
        # Create mock db_manager
        mock_db_manager = MagicMock()
        mock_db_manager.run_maintenance = AsyncMock(
            return_value={"summary": {"fragments_reduced": 5}}
        )

        # Create manager
        manager = MaintenanceManager()

        # Run maintenance with specific retention
        await manager._run_maintenance_task(
            project_id="test_project", db_manager=mock_db_manager, retention_minutes=180
        )

        # Verify run_maintenance was called with correct retention
        mock_db_manager.run_maintenance.assert_called_once()
        call_args = mock_db_manager.run_maintenance.call_args
        assert "cleanup_older_than" in call_args[1]
        assert call_args[1]["cleanup_older_than"] == timedelta(minutes=180)

    def test_cleanup_retention_minutes_validation_min(self, temp_config_file):
        """Test cleanup_retention_minutes validates minimum value (5 minutes)."""
        # Load base config and set invalid retention (too low)
        base_config = Config.load()
        config_data = base_config.to_dict()
        config_data["maintenance"] = {
            "cleanup_retention_minutes": 2  # Below minimum of 5
        }

        with open(temp_config_file, "w") as f:
            yaml.dump(config_data, f)

        # Loading should raise ConfigurationError
        # The schema validator checks range, match the numeric check error
        with pytest.raises(ConfigurationError, match="2.*less than.*minimum"):
            Config.load(str(temp_config_file))

    def test_cleanup_retention_minutes_validation_max(self, temp_config_file):
        """Test cleanup_retention_minutes validates maximum value (1440 minutes)."""
        # Load base config and set invalid retention (too high)
        base_config = Config.load()
        config_data = base_config.to_dict()
        config_data["maintenance"] = {
            "cleanup_retention_minutes": 2000  # Above maximum of 1440
        }

        with open(temp_config_file, "w") as f:
            yaml.dump(config_data, f)

        # Loading should raise ConfigurationError
        # The schema validator checks range, match the numeric check error
        with pytest.raises(ConfigurationError, match="2000.*greater than.*maximum"):
            Config.load(str(temp_config_file))

    def test_cleanup_retention_minutes_valid_range(self, temp_config_file):
        """Test valid cleanup_retention_minutes values."""
        base_config = Config.load()

        # Test minimum valid value (5)
        config_data = base_config.to_dict()
        config_data["maintenance"] = {"cleanup_retention_minutes": 5}
        with open(temp_config_file, "w") as f:
            yaml.dump(config_data, f)
        config = Config.load(str(temp_config_file))
        assert config.maintenance.cleanup_retention_minutes == 5

        # Test maximum valid value (1440)
        config_data = base_config.to_dict()
        config_data["maintenance"] = {"cleanup_retention_minutes": 1440}
        with open(temp_config_file, "w") as f:
            yaml.dump(config_data, f)
        config = Config.load(str(temp_config_file))
        assert config.maintenance.cleanup_retention_minutes == 1440

        # Test mid-range value
        config_data = base_config.to_dict()
        config_data["maintenance"] = {"cleanup_retention_minutes": 720}
        with open(temp_config_file, "w") as f:
            yaml.dump(config_data, f)
        config = Config.load(str(temp_config_file))
        assert config.maintenance.cleanup_retention_minutes == 720


class TestMaintenanceTriggerValidation:
    """Tests for trigger configuration validation."""

    def test_trigger_validation_valid_values(self, temp_config_file):
        """Test valid trigger values are accepted."""
        valid_triggers = ["project.closed", "indexing.completed", "disabled"]
        base_config = Config.load()

        for trigger in valid_triggers:
            config_data = base_config.to_dict()
            config_data["maintenance"] = {"trigger": trigger}

            with open(temp_config_file, "w") as f:
                yaml.dump(config_data, f)

            # Should load without error
            config = Config.load(str(temp_config_file))
            assert config.maintenance.trigger == trigger

    def test_trigger_validation_invalid_value(self, temp_config_file):
        """Test invalid trigger value raises ConfigurationError."""
        # Load base config and set invalid trigger
        base_config = Config.load()
        config_data = base_config.to_dict()
        config_data["maintenance"] = {"trigger": "invalid.trigger"}

        with open(temp_config_file, "w") as f:
            yaml.dump(config_data, f)

        # Loading should raise ConfigurationError
        # Schema validator checks enum, match the enum error
        with pytest.raises(ConfigurationError, match="invalid.trigger.*is not one of"):
            Config.load(str(temp_config_file))


class TestMaintenanceEnabledFlag:
    """Tests for enabled flag behavior."""

    @pytest.mark.asyncio
    async def test_enabled_false_prevents_trigger(self, temp_config_file):
        """Test enabled=false prevents maintenance trigger."""
        # Load base config and disable maintenance
        base_config = Config.load()
        config_data = base_config.to_dict()
        config_data["maintenance"] = {"enabled": False, "trigger": "project.closed"}

        with open(temp_config_file, "w") as f:
            yaml.dump(config_data, f)

        # Load config
        config = Config.load(str(temp_config_file))

        # Verify enabled is False
        assert config.maintenance.enabled is False

        # Create mock storage and event system
        mock_db_manager = MagicMock()
        mock_db_manager.run_maintenance = AsyncMock()

        mock_storage = MagicMock()
        mock_provider = MagicMock()
        mock_provider._db_manager = mock_db_manager
        mock_storage._graph_provider = mock_provider

        manager = MaintenanceManager(storage=mock_storage)

        # Mock Config.load to return our disabled config
        with patch("agentic_inquiry.config.Config.load", return_value=config):
            # Trigger event
            event_data = {"project_id": "test_project"}
            await manager._on_project_closed(event_data)

            # Wait briefly
            import asyncio

            await asyncio.sleep(0.1)

            # Maintenance should NOT run
            mock_db_manager.run_maintenance.assert_not_called()


class TestEnvironmentVariableOverrides:
    """Tests for environment variable overrides of maintenance config."""

    def test_env_override_retention_minutes(self, temp_config_file, sample_config_data):
        """Test INQUIRY_MAINTENANCE_RETENTION_MINUTES environment variable."""
        # Write base config
        with open(temp_config_file, "w") as f:
            yaml.dump(sample_config_data, f)

        # Set environment variable
        with patch.dict(os.environ, {"INQUIRY_MAINTENANCE_RETENTION_MINUTES": "300"}):
            config = Config.load(str(temp_config_file))

            # Should use env var value
            assert config.maintenance.cleanup_retention_minutes == 300

    def test_env_override_trigger(self, temp_config_file, sample_config_data):
        """Test INQUIRY_MAINTENANCE_TRIGGER environment variable."""
        # Write base config
        with open(temp_config_file, "w") as f:
            yaml.dump(sample_config_data, f)

        # Set environment variable
        with patch.dict(
            os.environ, {"INQUIRY_MAINTENANCE_TRIGGER": "indexing.completed"}
        ):
            config = Config.load(str(temp_config_file))

            # Should use env var value
            assert config.maintenance.trigger == "indexing.completed"

    def test_env_override_enabled(self, temp_config_file, sample_config_data):
        """Test INQUIRY_MAINTENANCE_ENABLED environment variable."""
        # Write base config
        with open(temp_config_file, "w") as f:
            yaml.dump(sample_config_data, f)

        # Set environment variable
        with patch.dict(os.environ, {"INQUIRY_MAINTENANCE_ENABLED": "false"}):
            config = Config.load(str(temp_config_file))

            # Should use env var value
            assert config.maintenance.enabled is False


class TestConfigToDict:
    """Tests for config serialization."""

    def test_maintenance_config_in_to_dict(self, temp_config_file, sample_config_data):
        """Test maintenance config is included in to_dict() output."""
        # Write config
        with open(temp_config_file, "w") as f:
            yaml.dump(sample_config_data, f)

        # Load and convert to dict
        config = Config.load(str(temp_config_file))
        config_dict = config.to_dict()

        # Verify maintenance section is present
        assert "maintenance" in config_dict
        assert config_dict["maintenance"]["enabled"] is True
        assert config_dict["maintenance"]["trigger"] == "project.closed"
        assert config_dict["maintenance"]["cleanup_retention_minutes"] == 120

    def test_maintenance_config_roundtrip(self, temp_config_file):
        """Test config can be saved and loaded (roundtrip)."""
        # Load base config and modify maintenance settings
        base_config = Config.load()
        original_config_data = base_config.to_dict()
        original_config_data["maintenance"] = {
            "enabled": True,
            "trigger": "indexing.completed",
            "cleanup_retention_minutes": 480,
        }

        # Write original
        with open(temp_config_file, "w") as f:
            yaml.dump(original_config_data, f)

        # Load
        config = Config.load(str(temp_config_file))

        # Convert to dict
        config_dict = config.to_dict()

        # Write dict back to file
        roundtrip_file = temp_config_file.parent / "roundtrip.yaml"
        with open(roundtrip_file, "w") as f:
            yaml.dump(config_dict, f)

        # Load again
        roundtrip_config = Config.load(str(roundtrip_file))

        # Should match original
        assert roundtrip_config.maintenance.enabled == config.maintenance.enabled
        assert roundtrip_config.maintenance.trigger == config.maintenance.trigger
        assert (
            roundtrip_config.maintenance.cleanup_retention_minutes
            == config.maintenance.cleanup_retention_minutes
        )


class TestMaintenanceConfigDefaults:
    """Tests for MaintenanceConfig default values."""

    def test_maintenance_config_defaults(self):
        """Test MaintenanceConfig uses correct defaults."""
        config = MaintenanceConfig()

        assert config.enabled is True
        assert config.trigger == "project.closed"
        assert config.cleanup_retention_minutes == 60

    def test_maintenance_config_post_init_validation(self):
        """Test MaintenanceConfig.__post_init__ validates values."""
        # Valid config should not raise
        MaintenanceConfig(
            enabled=True, trigger="project.closed", cleanup_retention_minutes=100
        )
        # Should succeed (no exception)

        # Invalid trigger should raise
        with pytest.raises(ConfigurationError, match="maintenance trigger"):
            MaintenanceConfig(
                enabled=True, trigger="invalid", cleanup_retention_minutes=60
            )

        # Invalid retention (too low) should raise
        with pytest.raises(ConfigurationError, match="cleanup_retention_minutes"):
            MaintenanceConfig(
                enabled=True, trigger="project.closed", cleanup_retention_minutes=3
            )

        # Invalid retention (too high) should raise
        with pytest.raises(ConfigurationError, match="cleanup_retention_minutes"):
            MaintenanceConfig(
                enabled=True, trigger="project.closed", cleanup_retention_minutes=2000
            )
