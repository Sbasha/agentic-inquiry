"""Tests for command discovery module."""

from __future__ import annotations

import pytest
from pathlib import Path

from agentic_inquiry.cli.discover import (
    CommandInfo,
    discover_commands,
    format_commands_table,
    format_commands_list,
    get_command_info,
    parse_frontmatter,
    find_commands_directory,
)


class TestParseFrontmatter:
    """Tests for parse_frontmatter function."""

    def test_valid_frontmatter(self, tmp_path):
        """Parses valid YAML frontmatter."""
        md_file = tmp_path / "test.md"
        md_file.write_text("""---
description: Test command
argument-hint: "<query>"
allowed-tools: ["Read", "Write"]
---

# Test Command

Content here.
""")

        result = parse_frontmatter(md_file)
        assert result["description"] == "Test command"
        assert result["argument-hint"] == "<query>"
        assert result["allowed-tools"] == ["Read", "Write"]

    def test_no_frontmatter(self, tmp_path):
        """Returns empty dict when no frontmatter."""
        md_file = tmp_path / "test.md"
        md_file.write_text("# No frontmatter\n\nJust content.")

        result = parse_frontmatter(md_file)
        assert result == {}

    def test_quoted_values(self, tmp_path):
        """Handles quoted values correctly."""
        md_file = tmp_path / "test.md"
        md_file.write_text("""---
description: "A quoted description"
name: 'single quotes'
---
""")

        result = parse_frontmatter(md_file)
        assert result["description"] == "A quoted description"
        assert result["name"] == "single quotes"

    def test_missing_file(self, tmp_path):
        """Returns empty dict for missing file."""
        result = parse_frontmatter(tmp_path / "nonexistent.md")
        assert result == {}


class TestFindCommandsDirectory:
    """Tests for find_commands_directory function."""

    def test_finds_local_extensions(self, tmp_path, monkeypatch):
        """Finds commands in local extensions."""
        # Create local extension structure
        commands_dir = tmp_path / "extensions" / "claude" / "ai" / "commands"
        commands_dir.mkdir(parents=True)
        (commands_dir / "search.md").write_text("---\ndescription: Search\n---")

        # Change to tmp_path so local paths are found
        monkeypatch.chdir(tmp_path)

        # Patch LOCAL_EXTENSION_PATHS
        from agentic_inquiry.cli import discover

        original_paths = discover.LOCAL_EXTENSION_PATHS
        discover.LOCAL_EXTENSION_PATHS = [Path("extensions/claude/ai")]

        try:
            result = find_commands_directory()
            assert result is not None
            assert result.exists()
        finally:
            discover.LOCAL_EXTENSION_PATHS = original_paths


class TestDiscoverInquiryCommands:
    """Tests for discover_commands function."""

    def test_discovers_commands(self, tmp_path, monkeypatch):
        """Discovers commands from directory."""
        # Create commands
        commands_dir = tmp_path / "extensions" / "claude" / "ai" / "commands"
        commands_dir.mkdir(parents=True)

        (commands_dir / "search.md").write_text("""---
description: Semantic search
argument-hint: "<query>"
---
""")
        (commands_dir / "index.md").write_text("""---
description: Index codebase
argument-hint: "[path]"
---
""")
        (commands_dir / "_private.md").write_text("---\ndescription: Private\n---")

        monkeypatch.chdir(tmp_path)

        from agentic_inquiry.cli import discover

        original_local_paths = discover.LOCAL_EXTENSION_PATHS
        original_cache_paths = discover.PLUGIN_CACHE_PATHS
        # Clear cache paths so only local paths are checked
        discover.PLUGIN_CACHE_PATHS = []
        discover.LOCAL_EXTENSION_PATHS = [Path("extensions/claude/ai")]

        try:
            commands = discover_commands()

            # Should find 2 commands (not _private)
            assert len(commands) == 2

            names = [c.name for c in commands]
            assert "search" in names
            assert "index" in names
            assert "_private" not in names

            # Check command info
            search_cmd = next(c for c in commands if c.name == "search")
            assert search_cmd.full_name == "ai:search"
            assert search_cmd.description == "Semantic search"
            assert search_cmd.argument_hint == "<query>"
        finally:
            discover.LOCAL_EXTENSION_PATHS = original_local_paths
            discover.PLUGIN_CACHE_PATHS = original_cache_paths


class TestFormatCommandsTable:
    """Tests for format_commands_table function."""

    def test_formats_table(self):
        """Formats commands as markdown table."""
        commands = [
            CommandInfo(
                name="search",
                full_name="ai:search",
                description="Search code",
                argument_hint="<query>",
                file_path=Path("search.md"),
            ),
            CommandInfo(
                name="index",
                full_name="ai:index",
                description="Index codebase",
                argument_hint="",
                file_path=Path("index.md"),
            ),
        ]

        result = format_commands_table(commands)

        assert "| Command | Description |" in result
        assert "`ai:search`" in result
        assert "<query>" in result
        assert "Search code" in result

    def test_empty_commands(self):
        """Handles empty command list."""
        result = format_commands_table([])
        assert "No commands found" in result


class TestFormatCommandsList:
    """Tests for format_commands_list function."""

    def test_formats_list(self):
        """Formats commands as simple list."""
        commands = [
            CommandInfo(
                name="search",
                full_name="ai:search",
                description="Search code",
                argument_hint="<query>",
                file_path=Path("search.md"),
            ),
        ]

        result = format_commands_list(commands)
        assert "ai:search" in result
        assert "<query>" in result
        assert "Search code" in result

    def test_verbose_mode(self):
        """Verbose mode shows more details."""
        commands = [
            CommandInfo(
                name="search",
                full_name="ai:search",
                description="Search code",
                argument_hint="<query>",
                file_path=Path("/path/to/search.md"),
            ),
        ]

        result = format_commands_list(commands, verbose=True)
        assert "Arguments:" in result
        assert "Description:" in result
        assert "File:" in result


class TestGetCommandInfo:
    """Tests for get_command_info function."""

    def test_finds_command(self, tmp_path, monkeypatch):
        """Finds specific command by name."""
        commands_dir = tmp_path / "extensions" / "claude" / "ai" / "commands"
        commands_dir.mkdir(parents=True)
        (commands_dir / "search.md").write_text("---\ndescription: Search\n---")

        monkeypatch.chdir(tmp_path)

        from agentic_inquiry.cli import discover

        original_local_paths = discover.LOCAL_EXTENSION_PATHS
        original_cache_paths = discover.PLUGIN_CACHE_PATHS
        discover.PLUGIN_CACHE_PATHS = []
        discover.LOCAL_EXTENSION_PATHS = [Path("extensions/claude/ai")]

        try:
            # Various name formats (colon format is canonical)
            assert get_command_info("search") is not None
            assert get_command_info("ai:search") is not None
            assert get_command_info("/ai:search") is not None
            # Legacy hyphen format still works
            assert get_command_info("/ai-search") is not None
            assert get_command_info("ai-search") is not None
            assert get_command_info("SEARCH") is not None  # Case insensitive
        finally:
            discover.LOCAL_EXTENSION_PATHS = original_local_paths
            discover.PLUGIN_CACHE_PATHS = original_cache_paths

    def test_not_found(self, tmp_path, monkeypatch):
        """Returns None for unknown command."""
        commands_dir = tmp_path / "extensions" / "claude" / "ai" / "commands"
        commands_dir.mkdir(parents=True)

        monkeypatch.chdir(tmp_path)

        from agentic_inquiry.cli import discover

        original_local_paths = discover.LOCAL_EXTENSION_PATHS
        original_cache_paths = discover.PLUGIN_CACHE_PATHS
        discover.PLUGIN_CACHE_PATHS = []
        discover.LOCAL_EXTENSION_PATHS = [Path("extensions/claude/ai")]

        try:
            assert get_command_info("nonexistent") is None
        finally:
            discover.LOCAL_EXTENSION_PATHS = original_local_paths
            discover.PLUGIN_CACHE_PATHS = original_cache_paths
