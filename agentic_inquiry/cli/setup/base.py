"""Base setup class for Agentic Inquiry setup wizard.

Provides common operations for all setup handlers including:
- Environment directory creation
- Configuration file writing
- Environment registry management
- Async helper for running validators from sync setup code
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Coroutine, Optional, TypeVar

import yaml

from agentic_inquiry.cli.env_resolver import (
    ENVS_DIR_NAME,
    REGISTRY_FILE_NAME,
    get_data_dir,
    is_test_environment,
)

logger = logging.getLogger(__name__)

T = TypeVar('T')


def run_async(coro: Coroutine[Any, Any, T]) -> T:
    """Run async code from sync context, handling nested event loops.

    This helper allows running async validators from sync setup code,
    handling the case where we're already in an async context (like pytest-asyncio).

    Args:
        coro: Coroutine to run

    Returns:
        Result of the coroutine
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    try:
        import nest_asyncio
        nest_asyncio.apply()
        return asyncio.run(coro)
    except ImportError:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(asyncio.run, coro)
            return future.result()


class SetupError(Exception):
    """Raised when setup fails."""

    pass


class BaseSetup(ABC):
    """Base class for setup handlers.

    Provides common operations for all backend-specific setup handlers:
    - Environment directory creation
    - Configuration file writing
    - Environment registry management
    - User prompting utilities

    Attributes:
        env_name: Name of the environment being created
        is_dev: Whether this is a development/test environment
        workspace: Root workspace path (defaults to cwd)
        backend_type: Type of backend ("lancedb")

    Example:
        >>> class MySetup(BaseSetup):
        ...     backend_type = "lancedb"
        ...     def run(self) -> bool:
        ...         self.create_env_directory()
        ...         self.write_config({"storage": {...}})
        ...         self.register_environment()
        ...         return True
    """

    backend_type: str = "unknown"

    def __init__(
        self,
        env_name: Optional[str] = None,
        is_dev: bool = False,
        workspace: Optional[Path] = None,
    ) -> None:
        """Initialize base setup.

        Args:
            env_name: Environment name. If None, will prompt user.
            is_dev: If True, creates a test environment (ai-test-*)
            workspace: Workspace root path. Defaults to cwd.
        """
        self.workspace = workspace or Path.cwd()
        self.is_dev = is_dev
        self._env_name = env_name
        self._env_dir: Optional[Path] = None
        self._config_path: Optional[Path] = None

    @property
    def env_name(self) -> str:
        """Get the environment name, prompting if needed."""
        if self._env_name is None:
            self._env_name = self._determine_env_name()
        return self._env_name

    @env_name.setter
    def env_name(self, value: str) -> None:
        """Set the environment name."""
        self._env_name = value

    @property
    def env_dir(self) -> Path:
        """Get the environment directory path."""
        if self._env_dir is None:
            data_dir = get_data_dir(self.workspace)
            self._env_dir = data_dir / ENVS_DIR_NAME / self.env_name
        return self._env_dir

    @property
    def config_path(self) -> Path:
        """Get the config file path."""
        if self._config_path is None:
            self._config_path = self.env_dir / "config.yaml"
        return self._config_path

    def _determine_env_name(self) -> str:
        """Determine environment name based on flags and prompts.

        Returns:
            Environment name (e.g., "ai", "ai-test", "my-env")
        """
        if self.is_dev:
            # Default dev environment name
            default_name = "ai-test"
        else:
            # Default production environment name
            default_name = "ai"

        # Prompt user for name
        name = prompt_input(
            "Environment name", default=default_name
        )

        # Ensure dev environments follow naming convention
        if self.is_dev and not is_test_environment(name):
            name = f"ai-test-{name}" if name != "ai-test" else name

        return name

    @abstractmethod
    def run(self) -> bool:
        """Run the setup wizard.

        Returns:
            True if setup completed successfully, False otherwise

        Raises:
            SetupError: If setup fails critically
        """
        pass

    def create_env_directory(self) -> Path:
        """Create the environment directory structure.

        Creates:
        - ~/.agentic-inquiry/
        - ~/.agentic-inquiry/envs/
        - ~/.agentic-inquiry/envs/<env_name>/

        Returns:
            Path to the created environment directory

        Raises:
            SetupError: If directory creation fails
        """
        try:
            self.env_dir.mkdir(parents=True, exist_ok=True)
            logger.info("Created environment directory: %s", self.env_dir)
            return self.env_dir
        except OSError as e:
            raise SetupError(f"Failed to create environment directory: {e}") from e

    def write_config(self, config: dict[str, Any]) -> Path:
        """Write configuration to the environment's config.yaml.

        Args:
            config: Configuration dictionary to write

        Returns:
            Path to the written config file

        Raises:
            SetupError: If config writing fails
        """
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, "w") as f:
                yaml.dump(config, f, default_flow_style=False, sort_keys=False)
            logger.info("Configuration written to: %s", self.config_path)
            return self.config_path
        except Exception as e:
            raise SetupError(f"Failed to write configuration: {e}") from e

    def register_environment(self, metadata: Optional[dict[str, Any]] = None) -> None:
        """Register the environment in env-registry.json.

        Args:
            metadata: Optional additional metadata to store

        Raises:
            SetupError: If registration fails
        """
        try:
            data_dir = get_data_dir(self.workspace)
            data_dir.mkdir(parents=True, exist_ok=True)
            registry_path = data_dir / REGISTRY_FILE_NAME

            # Load existing registry or create new
            if registry_path.exists():
                with open(registry_path) as f:
                    registry = json.load(f)
            else:
                registry = {"environments": [], "active_environment": None}

            # Check if environment already exists
            env_exists = any(
                env.get("name") == self.env_name
                for env in registry.get("environments", [])
            )

            if env_exists:
                # Update existing entry
                for env in registry["environments"]:
                    if env.get("name") == self.env_name:
                        env["backend_type"] = self.backend_type
                        env["config_path"] = str(self.config_path)
                        if metadata:
                            env["metadata"] = metadata
                        break
            else:
                # Add new entry
                entry = {
                    "name": self.env_name,
                    "backend_type": self.backend_type,
                    "config_path": str(self.config_path),
                }
                if metadata:
                    entry["metadata"] = metadata
                registry.setdefault("environments", []).append(entry)

            # Write registry
            with open(registry_path, "w") as f:
                json.dump(registry, f, indent=2)

            logger.info("Registered environment: %s", self.env_name)

        except Exception as e:
            raise SetupError(f"Failed to register environment: {e}") from e

    def set_active(self) -> None:
        """Set this environment as the active environment.

        Raises:
            SetupError: If setting active fails
        """
        try:
            registry_path = get_data_dir(self.workspace) / REGISTRY_FILE_NAME

            if not registry_path.exists():
                raise SetupError("Environment registry not found. Register environment first.")

            with open(registry_path) as f:
                registry = json.load(f)

            registry["active_environment"] = self.env_name

            with open(registry_path, "w") as f:
                json.dump(registry, f, indent=2)

            logger.info("Set active environment: %s", self.env_name)

        except SetupError:
            raise
        except Exception as e:
            raise SetupError(f"Failed to set active environment: {e}") from e

    def cleanup_partial(self) -> None:
        """Clean up partially created environment on failure.

        Removes the environment directory if it was created during this setup.
        """
        if self._env_dir and self._env_dir.exists():
            try:
                import shutil

                shutil.rmtree(self._env_dir)
                logger.info("Cleaned up partial environment: %s", self._env_dir)
            except Exception as e:
                logger.warning("Failed to clean up partial environment: %s", e)


def prompt_choice(question: str, options: list[str]) -> str:
    """Prompt user for a choice from a list.

    Args:
        question: Question to display
        options: List of options to choose from

    Returns:
        Selected option string
    """
    print(f"\n{question}")
    for i, opt in enumerate(options, 1):
        print(f"  {i}) {opt}")

    while True:
        try:
            choice = input(f"Enter choice [1-{len(options)}]: ").strip()
            if choice.isdigit() and 1 <= int(choice) <= len(options):
                return options[int(choice) - 1]
            print("Invalid choice. Please try again.")
        except KeyboardInterrupt:
            print("\nSetup cancelled.")
            sys.exit(0)


def prompt_input(question: str, default: Optional[str] = None, required: bool = False) -> str:
    """Prompt user for text input.

    Args:
        question: Question to display
        default: Default value if user presses enter
        required: If True, empty input is not allowed

    Returns:
        User input or default value
    """
    prompt = f"{question} [{default}]: " if default else f"{question}: "
    while True:
        try:
            value = input(prompt).strip()
            if value:
                return value
            if default:
                return default
            if not required:
                return ""
            print("This field is required. Please enter a value.")
        except KeyboardInterrupt:
            print("\nSetup cancelled.")
            sys.exit(0)


def prompt_confirm(question: str, default: bool = True) -> bool:
    """Prompt user for yes/no confirmation.

    Args:
        question: Question to display
        default: Default value if user presses enter

    Returns:
        True for yes, False for no
    """
    default_str = "Y/n" if default else "y/N"
    prompt = f"{question} [{default_str}]: "

    try:
        value = input(prompt).strip().lower()
        if not value:
            return default
        return value in ("y", "yes", "true", "1")
    except KeyboardInterrupt:
        print("\nSetup cancelled.")
        sys.exit(0)


def print_success(message: str) -> None:
    """Print a success message."""
    print(f"\n[OK] {message}")


def print_error(message: str) -> None:
    """Print an error message."""
    print(f"\n[ERROR] {message}", file=sys.stderr)


def print_warning(message: str) -> None:
    """Print a warning message."""
    print(f"\n[WARN] {message}")


def print_info(message: str) -> None:
    """Print an info message."""
    print(f"  {message}")
