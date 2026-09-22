"""Environment resolution for Agentic Inquiry.

This module provides environment detection following a clear discovery order:
1. INQUIRY_CONFIG env var (explicit override)
2. INQUIRY_ENV env var (named environment like 'ai', 'ai-test', 'ai-prod')
3. Active environment from global registry (~/.agentic-inquiry/)
4. Default fallback

Directory Convention:
- ~/.agentic-inquiry/              : Global - environments, registry, events, logs
- .agentic-inquiry/ (project-local): Testing - test data, local overrides

Naming Convention:
- 'ai' : Default environment
- 'ai-test' : Test environment (never auto-start)
- 'ai-<custom>' : Custom named environments (auto-start based on config)
"""

from __future__ import annotations

import json
import logging
import os
import platform
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, MutableMapping, Optional

if TYPE_CHECKING:
    from agentic_inquiry.config import Config

logger = logging.getLogger(__name__)

# Directory names
GLOBAL_DIR_NAME = ".agentic-inquiry"  # ~/.agentic-inquiry/ for environments, registry, logs
LOCAL_DIR_NAME = ".agentic-inquiry"  # .agentic-inquiry/ (project-local) for test data
ENVS_DIR_NAME = "envs"
REGISTRY_FILE_NAME = "env-registry.json"

# Legacy name - kept for backward compat in tests that import it
DATA_DIR_NAME = GLOBAL_DIR_NAME


@dataclass
class ResolvedEnvironment:
    """Result of environment resolution.

    Attributes:
        name: Environment name (e.g., 'ai', 'ai-test', 'gcp-prod')
        config_path: Path to the config file (may be None if using defaults)
        source: How the environment was resolved ('env_var', 'registry', 'onboarded', 'default')
        is_test: Whether this is a test environment
    """

    name: str
    config_path: Optional[Path]
    source: str
    is_test: bool


def get_global_dir() -> Path:
    """Get the global ai data directory (~/.agentic-inquiry/).

    This directory stores environments, registry, events, and logs.
    Can be overridden with INQUIRY_HOME env var.

    Returns:
        Path to ~/.agentic-inquiry/ directory
    """
    if ai_home := os.environ.get("INQUIRY_HOME"):
        return Path(ai_home)
    return Path.home() / GLOBAL_DIR_NAME


def get_local_dir(workspace: Optional[Path] = None) -> Path:
    """Get the project-local ai data directory (.agentic-inquiry/).

    This directory stores test data and project-local overrides.

    Args:
        workspace: Workspace root path. Defaults to current directory.

    Returns:
        Path to .agentic-inquiry/ directory within the workspace
    """
    if workspace is None:
        workspace = Path.cwd()
    return workspace / LOCAL_DIR_NAME


def get_data_dir(workspace: Optional[Path] = None) -> Path:
    """Get the ai data directory.

    When workspace is provided (e.g., in tests), returns workspace/.agentic-inquiry/
    for isolation. Otherwise returns the global ~/.agentic-inquiry/ directory.

    Args:
        workspace: If provided, returns workspace/.agentic-inquiry/ (for test isolation).
                   If None, returns ~/.agentic-inquiry/ (global).

    Returns:
        Path to the ai data directory
    """
    if workspace is not None:
        return workspace / GLOBAL_DIR_NAME
    return get_global_dir()


def get_env_config_path(env_name: str, workspace: Optional[Path] = None) -> Path:
    """Get the config file path for a named environment.

    Args:
        env_name: Environment name (e.g., 'ai', 'ai-test')
        workspace: Workspace root path

    Returns:
        Path to the environment's config.yaml
    """
    data_dir = get_data_dir(workspace)
    return data_dir / ENVS_DIR_NAME / env_name / "config.yaml"


def is_test_environment(env_name: str) -> bool:
    """Check if environment is a test environment by naming convention.

    Test environments never auto-start proxies to ensure test isolation.

    Args:
        env_name: Environment name to check

    Returns:
        True if this is a test environment
    """
    # Test environments by naming convention
    if env_name.startswith("ai-test"):
        return True
    if env_name == "test":
        return True
    if "test" in env_name.lower() and "prod" not in env_name.lower():
        return True
    return False




def load_env_registry(workspace: Optional[Path] = None) -> dict:
    """Load the environment registry.

    Args:
        workspace: Workspace root path

    Returns:
        Registry data or empty dict if not found
    """
    registry_path = get_data_dir(workspace) / REGISTRY_FILE_NAME
    if not registry_path.exists():
        return {}

    try:
        with open(registry_path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load environment registry: %s", e)
        return {}


def get_active_environment_from_registry(
    workspace: Optional[Path] = None,
) -> Optional[str]:
    """Get the active environment name from the registry.

    Args:
        workspace: Workspace root path

    Returns:
        Active environment name or None
    """
    registry = load_env_registry(workspace)
    return registry.get("active_environment")


def resolve_environment(workspace: Optional[Path] = None) -> ResolvedEnvironment:
    """Resolve active ai environment by discovery order.

    Discovery order:
    1. INQUIRY_CONFIG env var (explicit config path override)
    2. INQUIRY_ENV env var (named environment)
    3. Active environment from registry (if workspace is onboarded)
    4. Default 'ai' environment (if onboarded and ai config exists)
    5. Default fallback (package defaults)

    Args:
        workspace: Workspace root path. Defaults to current directory.

    Returns:
        ResolvedEnvironment with name, config_path, and flags
    """
    if workspace is None:
        workspace = Path.cwd()

    # 1. Explicit override via INQUIRY_CONFIG env var
    if config_path_str := os.environ.get("INQUIRY_CONFIG"):
        config_path = Path(config_path_str)
        # Extract env name from path if possible
        env_name = "custom"
        if config_path.parent.name != "":
            env_name = config_path.parent.name

        return ResolvedEnvironment(
            name=env_name,
            config_path=config_path if config_path.exists() else None,
            source="env_var",
            is_test=is_test_environment(env_name),
        )

    # 2. Named environment via INQUIRY_ENV env var
    if env_name := os.environ.get("INQUIRY_ENV"):
        # Check workspace-local first, then global ~/.agentic-inquiry/
        config_path = get_env_config_path(env_name, workspace)
        if not config_path.exists():
            config_path = get_env_config_path(env_name, workspace=None)
        return ResolvedEnvironment(
            name=env_name,
            config_path=config_path if config_path.exists() else None,
            source="env_var",
            is_test=is_test_environment(env_name),
        )

    # 3. Check registry (workspace-local .agentic-inquiry/ first, then global ~/.agentic-inquiry/)
    for ws in [workspace, None]:
        data_dir = get_data_dir(ws)
        if not data_dir.exists():
            continue

        # 3a. Check active environment from registry
        if active_env := get_active_environment_from_registry(ws):
            # Check both local and global for config
            config_path = get_env_config_path(active_env, ws)
            if not config_path.exists() and ws is not None:
                config_path = get_env_config_path(active_env, workspace=None)
            if config_path.exists():
                return ResolvedEnvironment(
                    name=active_env,
                    config_path=config_path,
                    source="registry",
                    is_test=is_test_environment(active_env),
                )

        # 3b. Default to 'ai' environment if onboarded
        ai_config = get_env_config_path("ai", ws)
        if not ai_config.exists() and ws is not None:
            ai_config = get_env_config_path("ai", workspace=None)
        if ai_config.exists():
            return ResolvedEnvironment(
                name="ai",
                config_path=ai_config,
                source="onboarded",
                is_test=False,
            )

    # 4. Fall back to default (no specific config)
    return ResolvedEnvironment(
        name="default",
        config_path=None,
        source="default",
        is_test=False,
    )


def list_environments(workspace: Optional[Path] = None) -> list[dict]:
    """List all available environments.

    Args:
        workspace: Workspace root path

    Returns:
        List of environment info dicts
    """
    envs = []
    data_dir = get_data_dir(workspace)
    envs_dir = data_dir / ENVS_DIR_NAME

    if not envs_dir.exists():
        return envs

    # Get active env for marking
    active_env = get_active_environment_from_registry(workspace)

    for env_dir in sorted(envs_dir.iterdir()):
        if env_dir.is_dir():
            config_path = env_dir / "config.yaml"
            envs.append(
                {
                    "name": env_dir.name,
                    "config_exists": config_path.exists(),
                    "is_active": env_dir.name == active_env,
                    "is_test": is_test_environment(env_dir.name),
                }
            )

    return envs


def parse_dotenv_lines(text: str) -> dict[str, str]:
    """Parse KEY=VALUE lines. Comments, blanks, and malformed lines are skipped."""
    parsed: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key or not key.isidentifier():
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        parsed[key] = value
    return parsed


def load_environment_dotenv(
    env_dir: Path,
    environ: Optional[MutableMapping[str, str]] = None,
) -> None:
    """Load ``env_dir/.env`` into ``environ`` without overwriting existing keys.

    Missing file is a no-op. The resolved path must stay inside ``env_dir``.
    Values are never logged.
    """
    if environ is None:
        environ = os.environ

    from agentic_inquiry.mcp.utils.validation import PathValidationError, validate_file_path

    try:
        env_file = validate_file_path(
            ".env", allowed_base=Path(env_dir), must_exist=False
        )
    except PathValidationError:
        logger.warning("Refusing to load environment dotenv outside %s", env_dir)
        return

    if not env_file.is_file():
        return

    try:
        text = env_file.read_text(encoding="utf-8")
    except OSError:
        logger.warning("Could not read environment dotenv under %s", env_dir)
        return

    applied = 0
    for key, value in parse_dotenv_lines(text).items():
        if key in environ:
            continue
        environ[key] = value
        applied += 1
    if applied:
        logger.debug("Loaded %d variable(s) from environment dotenv", applied)


def warn_embedding_device_hatch(env_dir: Path) -> None:
    """Print one Darwin hint when the CPU embedding hatch is unset.

    Must run before the embedder is constructed so the operator sees the
    hatch path if Metal/MPS aborts the process. No-op on other platforms
    and when ``INQUIRY_EMBEDDING_DEVICE`` is already set.
    """
    if platform.system() != "Darwin":
        return
    if os.environ.get("INQUIRY_EMBEDDING_DEVICE"):
        return
    env_file = Path(env_dir) / ".env"
    print(
        f"If embeddings abort on Metal/MPS, uncomment INQUIRY_EMBEDDING_DEVICE=cpu in {env_file}",
        file=sys.stderr,
    )


def load_config_for_environment(
    config_path: Optional[str] = None,
    workspace: Optional[Path] = None,
) -> "Config":
    """Load configuration based on resolved environment.

    This function handles the complexity of loading configs:
    1. If explicit config_path provided, use it directly
    2. Otherwise, resolve the environment and load appropriate config
    3. For overlay configs (in envs/ directory), merge with defaults

    Args:
        config_path: Optional explicit config path (overrides environment resolution)
        workspace: Workspace root path for environment resolution

    Returns:
        Loaded Config instance

    Example:
        >>> # Uses resolved environment (gcp-prod, ai, etc.)
        >>> config = load_config_for_environment()
        >>>
        >>> # Override with specific config file
        >>> config = load_config_for_environment("config/test.yaml")
    """
    from agentic_inquiry.config import Config

    # Explicit config path takes precedence
    if config_path:
        if "/envs/" in config_path:
            load_environment_dotenv(Path(config_path).parent)
            return Config.load_with_overlay(config_path)
        return Config.load(config_path)

    # Resolve environment
    env = resolve_environment(workspace)

    if env.config_path is not None:
        load_environment_dotenv(Path(env.config_path).parent)

    # No environment-specific config - use defaults
    if not env.config_path:
        return Config.load()

    # Environment overlay configs (in envs/ directory) need merging
    config_path_str = str(env.config_path)
    if "/envs/" in config_path_str:
        return Config.load_with_overlay(config_path_str)

    # Standard config file
    return Config.load(config_path_str)


def save_env_registry(registry: dict, workspace: Optional[Path] = None) -> None:
    """Save the environment registry to disk.

    Args:
        registry: Registry data to save
        workspace: Workspace root path

    Raises:
        OSError: If registry cannot be written
    """
    data_dir = get_data_dir(workspace)
    data_dir.mkdir(parents=True, exist_ok=True)

    registry_path = data_dir / REGISTRY_FILE_NAME
    with open(registry_path, "w") as f:
        json.dump(registry, f, indent=2)

    logger.debug("Saved environment registry to %s", registry_path)


def add_environment_to_registry(
    name: str,
    backend_type: str,
    config_path: str,
    workspace: Optional[Path] = None,
    metadata: Optional[dict] = None,
    set_active: bool = False,
) -> None:
    """Add or update an environment in the registry.

    Args:
        name: Environment name (e.g., 'ai', 'ai-test')
        backend_type: Backend type ('lancedb')
        config_path: Path to the environment's config.yaml
        workspace: Workspace root path
        metadata: Optional additional metadata
        set_active: If True, set this environment as active

    Example:
        >>> add_environment_to_registry(
        ...     name="gcp-prod",
        ...     backend_type="lancedb",
        ...     config_path="~/.agentic-inquiry/envs/gcp-prod/config.yaml",
        ...     metadata={"project": "my-project"},
        ...     set_active=True,
        ... )
    """
    registry = load_env_registry(workspace)

    # Ensure environments list exists
    if "environments" not in registry:
        registry["environments"] = []

    # Check if environment already exists
    env_index = None
    for i, env in enumerate(registry["environments"]):
        if env.get("name") == name:
            env_index = i
            break

    # Build environment entry
    entry = {
        "name": name,
        "backend_type": backend_type,
        "config_path": config_path,
    }
    if metadata:
        entry["metadata"] = metadata

    # Update or add entry
    if env_index is not None:
        registry["environments"][env_index] = entry
        logger.debug("Updated environment '%s' in registry", name)
    else:
        registry["environments"].append(entry)
        logger.debug("Added environment '%s' to registry", name)

    # Set active if requested
    if set_active:
        registry["active_environment"] = name

    save_env_registry(registry, workspace)


def remove_environment_from_registry(
    name: str,
    workspace: Optional[Path] = None,
) -> bool:
    """Remove an environment from the registry.

    Args:
        name: Environment name to remove
        workspace: Workspace root path

    Returns:
        True if environment was removed, False if not found
    """
    registry = load_env_registry(workspace)

    if "environments" not in registry:
        return False

    # Find and remove
    original_count = len(registry["environments"])
    registry["environments"] = [
        env for env in registry["environments"] if env.get("name") != name
    ]

    if len(registry["environments"]) == original_count:
        return False

    # Clear active if this was the active environment
    if registry.get("active_environment") == name:
        registry["active_environment"] = None

    save_env_registry(registry, workspace)
    logger.info("Removed environment '%s' from registry", name)
    return True


def set_active_environment(name: str, workspace: Optional[Path] = None) -> bool:
    """Set the active environment.

    Args:
        name: Environment name to set as active
        workspace: Workspace root path

    Returns:
        True if environment was set as active, False if not found in registry
    """
    registry = load_env_registry(workspace)

    # Verify environment exists
    env_exists = any(
        env.get("name") == name for env in registry.get("environments", [])
    )

    if not env_exists:
        logger.warning("Environment '%s' not found in registry", name)
        return False

    registry["active_environment"] = name
    save_env_registry(registry, workspace)
    logger.info("Set active environment to '%s'", name)
    return True


def get_backend_type_for_environment(
    env_name: Optional[str] = None,
    workspace: Optional[Path] = None,
) -> str:
    """Get the effective backend type for a named environment.

    Checks the env-registry first, then falls back to reading config.yaml.
    This handles both old-format (profile: gcp) and new-format (backend_type: ...)
    registry entries.

    Args:
        env_name: Environment name (uses active env if None)
        workspace: Workspace root path

    Returns:
        Backend type string (e.g., "lancedb", "postgresql", "cloudsql", "alloydb")
    """
    registry = load_env_registry(workspace)

    if env_name is None:
        env_name = registry.get("active_environment")
        if not env_name:
            return "lancedb"

    # Look up in registry
    for env in registry.get("environments", []):
        if env.get("name") != env_name:
            continue

        # New format: backend_type field
        if bt := env.get("backend_type"):
            return bt

        # New format: metadata.backend field
        if meta := env.get("metadata"):
            if bt := meta.get("backend"):
                return bt

        # Old format: profile field -> infer backend type
        profile = env.get("profile", "")
        if profile == "local":
            return "lancedb"

    # Fall back to reading config
    try:
        config = load_config_for_environment(workspace=workspace)
        backends = getattr(getattr(config, "storage", None), "backends", None)
        if backends:
            for _name, backend in backends.items():
                bt = backend.get("type", "")
                if bt:
                    return bt
    except Exception:
        pass

    return "lancedb"


def normalize_registry(workspace: Optional[Path] = None) -> int:
    """Normalize env-registry.json entries to consistent format.

    Upgrades old-format entries (profile-based) to new format (backend_type-based).
    Also ensures metadata fields like embedding_strategy are populated from
    capabilities where possible.

    Args:
        workspace: Workspace root path

    Returns:
        Number of entries that were updated
    """
    from agentic_inquiry.storage.capabilities import get_capabilities_for_backend

    registry = load_env_registry(workspace)
    updated = 0

    for env in registry.get("environments", []):
        changed = False

        # Upgrade old "profile" format to "backend_type"
        if "backend_type" not in env:
            profile = env.get("profile", "")
            if profile == "local":
                env["backend_type"] = "lancedb"
                changed = True
            elif profile:
                env["backend_type"] = profile
                changed = True

        # Ensure metadata exists with capabilities info
        bt = env.get("backend_type", "lancedb")
        caps = get_capabilities_for_backend(bt)

        if "metadata" not in env:
            env["metadata"] = {}
            changed = True

        meta = env["metadata"]

        if "backend" not in meta and bt:
            meta["backend"] = bt
            changed = True

        if "embedding_strategy" not in meta:
            meta["embedding_strategy"] = caps.embedding_strategy.value
            changed = True

        if caps.uses_server_side_embedding and "embedding_model" not in meta:
            meta["embedding_model"] = caps.embedding_model
            meta["embedding_dimensions"] = caps.embedding_dimensions
            changed = True

        if changed:
            updated += 1

    if updated:
        save_env_registry(registry, workspace)
        logger.info("Normalized %d registry entries", updated)

    return updated


__all__ = [
    "ResolvedEnvironment",
    "resolve_environment",
    "is_test_environment",
    "get_global_dir",
    "get_local_dir",
    "get_data_dir",
    "get_env_config_path",
    "load_env_registry",
    "save_env_registry",
    "get_active_environment_from_registry",
    "get_backend_type_for_environment",
    "add_environment_to_registry",
    "remove_environment_from_registry",
    "set_active_environment",
    "normalize_registry",
    "list_environments",
    "load_config_for_environment",
    "load_environment_dotenv",
    "warn_embedding_device_hatch",
    "parse_dotenv_lines",
    "GLOBAL_DIR_NAME",
    "LOCAL_DIR_NAME",
    "DATA_DIR_NAME",
    "ENVS_DIR_NAME",
    "REGISTRY_FILE_NAME",
]
