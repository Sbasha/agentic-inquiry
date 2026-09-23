"""Dispatch of ``ai mcp`` before the MCP server starts."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


def test_mcp_dispatches_with_the_storage_namespace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: dict[str, list[str]] = {}

    def fake_main() -> None:
        seen["argv"] = list(sys.argv)

    monkeypatch.setattr("agentic_inquiry.mcp.cli.main", fake_main)
    project = (tmp_path / "proj").resolve()
    project.mkdir()
    monkeypatch.chdir(project)
    monkeypatch.setattr(
        "agentic_inquiry.cli.__main__._storage_project_id",
        lambda _root: "storage-ns",
    )
    from agentic_inquiry.cli.__main__ import main

    monkeypatch.setattr(sys, "argv", ["ai", "mcp"])
    main()
    argv = seen["argv"]
    assert argv[argv.index("--project-id") + 1] == "storage-ns"
    assert argv[argv.index("--project-root") + 1] == str(project)
    assert argv[argv.index("--transport") + 1] == "stdio"

    monkeypatch.setattr(sys, "argv", ["ai", "mcp", "--project-id", "X"])
    main()
    argv = seen["argv"]
    assert argv[argv.index("--project-id") + 1] == "X"
    assert "storage-ns" not in argv

    monkeypatch.setattr(
        "agentic_inquiry.cli.__main__._storage_project_id", lambda _root: None
    )
    monkeypatch.setattr(sys, "argv", ["ai", "mcp"])
    main()
    argv = seen["argv"]
    assert "--project-id" not in argv
    assert "--project-root" not in argv
