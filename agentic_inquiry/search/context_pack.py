"""Render ranked search results as a context pack an agent can read directly.

Each result is a header, ``path:line_start-line_end`` plus the enclosing scope
(or symbol), followed by the chunk's text. Rendering stops at a character
budget on a line boundary, so the output is exactly what fits, and says how
many results it left out.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional


def _relative(path: str, root: Optional[Path]) -> str:
    if root is not None:
        try:
            return Path(os.path.realpath(path)).relative_to(os.path.realpath(root)).as_posix()
        except ValueError:
            pass
    return path


def _line(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return number if number > 0 else 0


def scope_of(row: Mapping[str, Any]) -> str:
    """The chunk's scope, from a parser-shaped ``metadata`` dict or a stored row's JSON ``metadata.data``."""
    metadata = row.get("metadata")
    if not isinstance(metadata, Mapping):
        return ""
    if "scope" in metadata:
        return str(metadata.get("scope") or "")
    try:
        data = json.loads(metadata.get("data") or "{}")
    except (TypeError, ValueError):
        return ""
    return str(data.get("scope") or "") if isinstance(data, dict) else ""


def header(row: Mapping[str, Any], root: Optional[Path] = None) -> str:
    """``path:start-end  scope`` for one result row; ``path`` alone when lines are unknown."""
    path = _relative(str(row.get("file_path", "")), root)
    start, end = _line(row.get("line_start")), _line(row.get("line_end"))
    location = f"{path}:{start}-{max(start, end)}" if start else path
    label = scope_of(row) or row.get("element_name") or ""
    return f"{location}  {label}" if label else location


def render_context_pack(rows: Iterable[Mapping[str, Any]], max_chars: int, root: Optional[Path] = None) -> str:
    """Headers and text for ``rows`` in order, cut at ``max_chars`` on a line boundary."""
    rows = list(rows)
    if not rows:
        return "No results."
    lines: list[str] = []
    used = 0
    shown = 0
    for row in rows:
        block = [header(row, root), *str(row.get("content") or "").split("\n"), ""]
        fitted = False
        for line in block:
            cost = len(line) + 1
            if used + cost > max_chars:
                break
            lines.append(line)
            used += cost
            fitted = True
        if not fitted or used + 1 > max_chars:
            shown += int(fitted)
            break
        shown += 1
    omitted = len(rows) - shown
    text = "\n".join(lines).rstrip("\n")
    if omitted > 0:
        text += f"\n[{omitted} more results omitted; raise max_chars]"
    return text
