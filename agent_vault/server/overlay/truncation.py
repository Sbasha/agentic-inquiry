"""Diff truncation utility for local-change overlay (WS3).

``truncate_diff`` caps the size of a :class:`LocalDiff` payload before it is
annotated server-side and included in a search response.  Truncation is
deterministic: files are sorted alphabetically and trimmed from the end.

Limits
------
- **max_per_file**: maximum number of ``changed_lines`` entries kept per file.
- **max_total**: maximum total ``changed_lines`` entries across all files.

When the total cap is reached the remaining files are dropped entirely.
``LocalDiff.truncated`` is set to ``True`` and ``LocalDiff.omitted_count``
records how many files were omitted.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_vault.server.routes.search import LocalDiff, LocalDiffFile

logger = logging.getLogger("agv.server.overlay.truncation")


def truncate_diff(
    local_diff: "LocalDiff",
    max_per_file: int = 100,
    max_total: int = 500,
) -> "LocalDiff":
    """Return a size-limited copy of *local_diff*.

    Processing order:
    1. Sort files alphabetically by ``path``.
    2. For each file, keep at most *max_per_file* entries in ``changed_lines``.
    3. Accumulate a running total of ``changed_lines`` across files.
    4. Once the running total would exceed *max_total*, stop including files.
    5. Set ``truncated=True`` and ``omitted_count`` on the returned diff when
       any files are omitted.

    Args:
        local_diff: The :class:`LocalDiff` payload to truncate.
        max_per_file: Maximum ``changed_lines`` entries per file (default 100).
        max_total: Maximum total ``changed_lines`` entries across all files (default 500).

    Returns:
        A new :class:`LocalDiff` with size-limited content.  The original is
        not mutated.
    """
    # Lazy import to avoid circular dependency at module load time
    from agent_vault.server.routes.search import LocalDiff, LocalDiffFile  # noqa: F401

    if not local_diff.modified_files:
        return local_diff

    # Sort files alphabetically for deterministic, reproducible truncation
    sorted_files = sorted(local_diff.modified_files, key=lambda f: f.path)

    kept_files: list[LocalDiffFile] = []
    total_lines: int = 0

    for file_entry in sorted_files:
        if total_lines >= max_total:
            # Total cap already reached — skip all remaining files
            break

        # Cap per-file changed_lines
        capped_lines: list[int] = file_entry.changed_lines[:max_per_file]

        # Check how many more we can fit in the total budget
        budget_remaining = max_total - total_lines
        if len(capped_lines) > budget_remaining:
            capped_lines = capped_lines[:budget_remaining]

        total_lines += len(capped_lines)

        kept_files.append(
            LocalDiffFile(
                path=file_entry.path,
                changed_lines=capped_lines,
                status=file_entry.status,
            )
        )

    omitted_count = len(sorted_files) - len(kept_files)
    already_truncated = local_diff.truncated or omitted_count > 0
    total_omitted = (local_diff.omitted_count or 0) + omitted_count

    if omitted_count:
        logger.debug(
            "truncate_diff: omitted %d/%d files (max_per_file=%d, max_total=%d)",
            omitted_count,
            len(sorted_files),
            max_per_file,
            max_total,
        )

    return LocalDiff(
        branch=local_diff.branch,
        modified_files=kept_files,
        truncated=already_truncated,
        omitted_count=total_omitted,
    )
