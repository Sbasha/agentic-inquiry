"""Dynamic command discovery for Agentic Inquiry.

This module provides utilities to discover available ai commands
by scanning the plugin cache instead of hardcoding command lists.

Plugin cache structure:
~/.claude/plugins/cache/agentic_inquiry/ai/
├── <version>/
│   ├── commands/
│   │   ├── index.md
│   │   ├── search.md
│   │   └── ...
│   ├── skills/
│   └── agents/
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Standard plugin cache locations
PLUGIN_CACHE_PATHS = [
    Path.home() / ".claude" / "plugins" / "cache" / "agentic-inquiry" / "ai",
    Path.home() / ".claude" / "plugins" / "installed" / "agentic-inquiry" / "ai",
]

# Local extension paths (for development)
LOCAL_EXTENSION_PATHS = [
    Path("extensions/claude/ai"),
    Path("extensions/ai"),
]


@dataclass
class CommandInfo:
    """Information about a discovered command.

    Attributes:
        name: Command name (e.g., 'search', 'index')
        full_name: Full command with prefix (e.g., 'ai:search')
        description: Brief description of what the command does
        argument_hint: Hint about expected arguments
        file_path: Path to the command definition file
    """
    name: str
    full_name: str
    description: str
    argument_hint: str
    file_path: Path


def parse_frontmatter(file_path: Path) -> dict[str, Any]:
    """Parse YAML frontmatter from a markdown file.

    Args:
        file_path: Path to the markdown file

    Returns:
        Dict of frontmatter key-value pairs
    """
    try:
        content = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        logger.warning("Could not read %s: %s", file_path, e)
        return {}

    # Match YAML frontmatter between --- delimiters
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
    if not match:
        return {}

    frontmatter_text = match.group(1)
    result = {}

    # Simple YAML parsing for common frontmatter fields
    for line in frontmatter_text.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()

            # Remove quotes if present
            if value.startswith('"') and value.endswith('"'):
                value = value[1:-1]
            elif value.startswith("'") and value.endswith("'"):
                value = value[1:-1]

            # Handle arrays
            if value.startswith("[") and value.endswith("]"):
                value = [v.strip().strip('"\'') for v in value[1:-1].split(",")]

            result[key] = value

    return result


def find_commands_directory() -> Optional[Path]:
    """Find the commands directory in plugin cache or local extensions.

    Searches in order:
    1. Plugin cache (newest version first)
    2. Local extension paths (for development)

    Returns:
        Path to commands directory or None if not found
    """
    # Check plugin cache first
    for cache_path in PLUGIN_CACHE_PATHS:
        if cache_path.exists():
            # Find newest version
            versions = sorted(
                [d for d in cache_path.iterdir() if d.is_dir()],
                key=lambda p: p.name,
                reverse=True
            )
            for version_dir in versions:
                commands_dir = version_dir / "commands"
                if commands_dir.exists():
                    logger.debug("Found commands in plugin cache: %s", commands_dir)
                    return commands_dir

    # Check local extension paths
    for ext_path in LOCAL_EXTENSION_PATHS:
        commands_dir = ext_path / "commands"
        if commands_dir.exists():
            logger.debug("Found commands in local extensions: %s", commands_dir)
            return commands_dir

    return None


def discover_commands() -> list[CommandInfo]:
    """Discover available ai commands from plugin cache or local extensions.

    Returns:
        List of CommandInfo objects for each discovered command
    """
    commands_dir = find_commands_directory()
    if not commands_dir:
        logger.warning("Could not find commands directory")
        return []

    commands = []

    for cmd_file in sorted(commands_dir.glob("*.md")):
        if cmd_file.name.startswith("_"):
            continue  # Skip private/internal files

        metadata = parse_frontmatter(cmd_file)
        name = cmd_file.stem

        commands.append(CommandInfo(
            name=name,
            full_name=f"ai:{name}",
            description=metadata.get("description", ""),
            argument_hint=metadata.get("argument-hint", ""),
            file_path=cmd_file,
        ))

    logger.debug("Discovered %d commands", len(commands))
    return commands


def format_commands_table(commands: list[CommandInfo]) -> str:
    """Format commands as a markdown table.

    Args:
        commands: List of CommandInfo objects

    Returns:
        Markdown table string
    """
    if not commands:
        return "No commands found."

    lines = [
        "| Command | Description |",
        "|---------|-------------|",
    ]

    for cmd in commands:
        arg_hint = f" {cmd.argument_hint}" if cmd.argument_hint else ""
        lines.append(f"| `{cmd.full_name}`{arg_hint} | {cmd.description} |")

    return "\n".join(lines)


def format_commands_list(commands: list[CommandInfo], verbose: bool = False) -> str:
    """Format commands as a simple list.

    Args:
        commands: List of CommandInfo objects
        verbose: Include argument hints and file paths

    Returns:
        Formatted list string
    """
    if not commands:
        return "No commands found."

    lines = []

    for cmd in commands:
        if verbose:
            lines.append(f"{cmd.full_name}")
            if cmd.argument_hint:
                lines.append(f"  Arguments: {cmd.argument_hint}")
            lines.append(f"  Description: {cmd.description}")
            lines.append(f"  File: {cmd.file_path}")
            lines.append("")
        else:
            arg_hint = f" {cmd.argument_hint}" if cmd.argument_hint else ""
            desc = f" - {cmd.description}" if cmd.description else ""
            lines.append(f"  {cmd.full_name}{arg_hint}{desc}")

    return "\n".join(lines)


def get_command_info(command_name: str) -> Optional[CommandInfo]:
    """Get info for a specific command by name.

    Args:
        command_name: Command name (with or without ai: prefix)

    Returns:
        CommandInfo or None if not found
    """
    # Normalize name
    name = command_name.lower()
    for prefix in ("/ai:", "/ai-", "ai:", "ai-"):
        if name.startswith(prefix):
            name = name[len(prefix):]
            break

    commands = discover_commands()
    for cmd in commands:
        if cmd.name == name:
            return cmd

    return None


# CLI entry point for testing
def main() -> int:
    """CLI entry point for command discovery."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Discover available ai commands"
    )
    parser.add_argument(
        "--format", "-f",
        choices=["table", "list", "json"],
        default="list",
        help="Output format"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed information"
    )

    args = parser.parse_args()

    commands = discover_commands()

    if args.format == "table":
        print(format_commands_table(commands))
    elif args.format == "json":
        import json
        data = [
            {
                "name": cmd.name,
                "full_name": cmd.full_name,
                "description": cmd.description,
                "argument_hint": cmd.argument_hint,
            }
            for cmd in commands
        ]
        print(json.dumps(data, indent=2))
    else:
        print("Available ai Commands:\n")
        print(format_commands_list(commands, verbose=args.verbose))

    return 0


__all__ = [
    "CommandInfo",
    "discover_commands",
    "format_commands_table",
    "format_commands_list",
    "get_command_info",
    "parse_frontmatter",
    "find_commands_directory",
]


if __name__ == "__main__":
    exit(main())
