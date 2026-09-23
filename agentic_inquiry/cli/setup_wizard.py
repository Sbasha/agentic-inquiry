"""Interactive setup wizard for Agentic Inquiry.

This module provides the main entry point for the setup wizard, routing to
appropriate backend-specific handlers based on command-line arguments.

Usage:
    ai setup                  # Storage, then lifecycle enable when a client is installed
    ai setup local [name]     # LanceDB (local), then the same enable step on a terminal
    ai setup --dev            # Create test environment (storage only)
    ai setup --client claude-code
    ai setup --no-enable

Environment Naming:
    - Default: 'ai' (production)
    - With --dev: 'ai-test' or 'ai-test-<name>'
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

from agentic_inquiry.cli.setup.base import (
    prompt_choice,
    prompt_confirm,
    print_error,
    print_info,
    print_success,
)
from agentic_inquiry.cli.setup.local_setup import LocalSetup
from agentic_inquiry.integration.contract import CLIENTS


def create_parser() -> argparse.ArgumentParser:
    """Create argument parser for setup command.

    Returns:
        Configured ArgumentParser
    """
    parser = argparse.ArgumentParser(
        description="Configure Agentic Inquiry storage backend",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  ai setup                    Storage, then enable installed clients
  ai setup local              LanceDB (local, default)
  ai setup --client claude-code
  ai setup --no-enable        Storage only
""",
    )

    parser.add_argument(
        "backend",
        nargs="?",
        choices=["local"],
        help="Backend type: local (LanceDB)",
    )

    parser.add_argument(
        "name",
        nargs="?",
        help="Environment name (default: 'ai' or 'ai-test' with --dev)",
    )

    parser.add_argument(
        "--dev",
        action="store_true",
        help="Create a test/development environment",
    )

    parser.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="Workspace root path (default: current directory)",
    )

    parser.add_argument(
        "--client",
        action="append",
        choices=list(CLIENTS),
        default=None,
        help="Enable this client without a prompt. Repeat for more than one.",
    )

    parser.add_argument(
        "--no-enable",
        action="store_true",
        help="Create the local environment and leave lifecycle hooks off",
    )

    return parser


def installed_afp_clients(workspace: Path) -> list[str]:
    """Clients whose AFP plugin directory is present in this project."""
    root = workspace / ".agents" / "plugins" / "agentic-inquiry"
    return [client for client in CLIENTS if (root / client).is_dir()]


def _print_next_steps(config_path: Path) -> None:
    """The same three steps Agent Vault prints after a local environment exists."""
    print("\nNext steps:")
    print("  1. Index your codebase: ai index .")
    print("  2. Start the server: ai serve")
    print("  3. Search: ai search 'your query'")
    print(f"\nConfiguration: {config_path}")


def guide_lifecycle(
    workspace: Path,
    *,
    clients: Optional[list[str]] = None,
    skip: bool = False,
    interactive: bool = False,
    config_path: Optional[Path] = None,
) -> bool:
    """Enable the AFP lifecycle for this project after the store exists.

    An explicit ``clients`` list enables those clients with no prompt. With no
    list, a terminal offers the clients the AFP pack installed here. A hook
    never does this; the person confirms it.

    Args:
        workspace: Project root that holds the local environment
        clients: Clients to enable. None discovers them.
        skip: Leave lifecycle off
        interactive: Ask before enabling discovered clients
        config_path: Environment config to name in the closing message

    Returns:
        True when setup can finish, including a deliberate skip
    """
    shown = config_path or (
        workspace / ".agentic-inquiry" / "envs" / "ai" / "config.yaml"
    )
    if skip:
        _print_next_steps(shown)
        return True

    chosen = list(clients) if clients is not None else installed_afp_clients(workspace)
    explicit = clients is not None
    if not chosen and interactive:
        choice = prompt_choice(
            "No AFP client is installed in this project. Enable one anyway, or skip?",
            [*CLIENTS, "Skip"],
        )
        if choice == "Skip":
            print_info(
                "Lifecycle stays off. Run ai integration enable --client <client> "
                "--owner afp --project-root <project> when you want hooks to record work."
            )
            _print_next_steps(shown)
            return True
        chosen = [choice]
    elif not chosen:
        print_info(
            "Lifecycle stays off. Run ai integration enable --client <client> "
            "--owner afp --project-root <project> when you want hooks to record work."
        )
        _print_next_steps(shown)
        return True
    elif not explicit:
        if not interactive:
            names = " ".join(f"--client {client}" for client in chosen)
            print_info(
                f"Lifecycle stays off. Re-run with {names} to enable it without a prompt."
            )
            _print_next_steps(shown)
            return True
        names = ", ".join(chosen)
        if not prompt_confirm(
            f"Enable lifecycle hooks for {names} in this project?",
            default=True,
        ):
            print_info("Lifecycle stays off.")
            _print_next_steps(shown)
            return True

    from agentic_inquiry.integration.state import StateError
    from agentic_inquiry.integration.verbs import enable

    gitignore: list[str] = []
    for client in chosen:
        try:
            result = enable(str(workspace.resolve()), client=client, owner="afp")
        except StateError as exc:
            print_error(f"{exc.code}: {exc.message}")
            return False
        gitignore = list(result["gitignore"])
        print_success(f"Lifecycle enabled for {client}.")
    if gitignore:
        print_info("Gitignore hint:")
        for line in gitignore:
            print(f"  {line}")
        print_info(
            "Commit .agentic-inquiry/project.toml. integration.json stays on this machine."
        )
    _print_next_steps(shown)
    print_info(
        "Start a new client session. The installed hooks now record this project."
    )
    return True


def _ensure_local(
    *,
    env_name: Optional[str],
    is_dev: bool,
    workspace: Path,
    continue_when_present: bool,
) -> tuple[bool, Optional[Path]]:
    """Create the LanceDB environment, or keep one that is already there."""
    setup = LocalSetup(env_name=env_name, is_dev=is_dev, workspace=workspace)
    if setup.config_path.exists():
        if not continue_when_present:
            return setup.run(), None
        print_info(
            f"Environment '{setup.env_name}' is already configured at {setup.config_path}"
        )
        return True, setup.config_path
    if not setup.run(announce=False):
        return False, None
    return True, setup.config_path


def run_interactive_setup(
    is_dev: bool = False,
    workspace: Optional[Path] = None,
) -> tuple[bool, Optional[Path]]:
    """Run interactive setup when no backend type is specified.

    Args:
        is_dev: Whether to create a test environment
        workspace: Workspace root path

    Returns:
        Whether the store is ready, and its config path
    """
    print("========================================")
    print("  Agentic Inquiry Environment Setup")
    print("========================================")

    print_info("Select the storage backend for your environment.")
    print_info("")
    print_info("LanceDB (Local) - Best for development")
    print_info("  - No external dependencies")
    print_info("  - Fast, embedded vector database")
    print_info("  - SQLite for metadata")
    print_info("")
    prompt_choice("\nSelect storage backend:", ["LanceDB (Local)"])

    root = workspace or Path.cwd()
    return _ensure_local(
        env_name=None,
        is_dev=is_dev,
        workspace=root,
        continue_when_present=True,
    )


def run_setup(args: Optional[list[str]] = None) -> bool:
    """Run the setup wizard with the given arguments.

    Args:
        args: Command-line arguments (defaults to sys.argv[1:])

    Returns:
        True if setup completed successfully
    """
    parser = create_parser()
    parsed = parser.parse_args(args)

    workspace = parsed.workspace or Path.cwd()
    try:
        workspace = workspace.resolve()
    except OSError as exc:
        print_error(f"Workspace is not a directory: {exc}")
        return False
    is_dev = parsed.dev

    if (
        not parsed.backend
        and parsed.client is None
        and not parsed.no_enable
        and not is_dev
    ):
        ready, config_path = run_interactive_setup(is_dev=is_dev, workspace=workspace)
        if not ready or config_path is None:
            return False
    elif parsed.backend in {None, "local"}:
        continue_when_present = bool(parsed.client) or sys.stdin.isatty()
        ready, config_path = _ensure_local(
            env_name=parsed.name,
            is_dev=is_dev,
            workspace=workspace,
            continue_when_present=continue_when_present,
        )
        if not ready or config_path is None:
            return False
    else:
        print_error(f"Unknown backend: {parsed.backend}")
        return False

    if is_dev:
        return guide_lifecycle(workspace, skip=True, config_path=config_path)
    return guide_lifecycle(
        workspace,
        clients=parsed.client,
        skip=parsed.no_enable,
        interactive=sys.stdin.isatty()
        and parsed.client is None
        and not parsed.no_enable,
        config_path=config_path,
    )


# Legacy entry point for backward compatibility
def run_setup_legacy() -> None:
    """Legacy entry point - runs interactive setup.

    This function maintains backward compatibility with the old setup wizard
    that only supported interactive mode.
    """
    success = run_setup()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    success = run_setup()
    sys.exit(0 if success else 1)
