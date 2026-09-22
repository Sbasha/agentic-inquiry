"""Path resolution utilities for agent_vault."""

from pathlib import Path
from typing import Union


def resolve_path(path: Union[str, Path], base: Union[str, Path, None] = None) -> Path:
    """Resolve a path, handling relative and absolute paths consistently.

    Args:
        path: The path to resolve
        base: Optional base directory for relative paths (defaults to cwd)

    Returns:
        Resolved absolute Path object
    """
    p = Path(path)
    if p.is_absolute():
        return p.resolve()
    if base is not None:
        return (Path(base) / p).resolve()
    return p.resolve()


def ensure_parent_exists(path: Union[str, Path]) -> Path:
    """Ensure the parent directory of a path exists.

    Args:
        path: The path whose parent directory should be created

    Returns:
        The path as a Path object
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p
