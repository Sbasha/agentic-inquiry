"""
Fast-path file detection for priority indexing.

This module provides functionality to identify and prioritize files that should
be indexed first during the indexing process. Fast-path files include:
- README and documentation files
- Configuration files (pyproject.toml, setup.py, etc.)
- Main entry points (main.py, app.py, etc.)
- API definitions and core modules
"""

from pathlib import Path
from typing import List, Tuple

# Files to index first (in priority order)
# Format: (pattern, priority_level)
# Lower priority number = higher priority (indexed first)
FAST_PATH_PATTERNS: List[Tuple[str, int]] = [
    # Priority 1: Entry points and documentation
    ("README.md", 1),
    ("README.rst", 1),
    ("README.txt", 1),
    ("readme.md", 1),
    # Priority 2: Configuration
    ("pyproject.toml", 2),
    ("setup.py", 2),
    ("package.json", 2),
    ("Cargo.toml", 2),
    ("go.mod", 2),
    # Priority 3: Main entry points
    ("main.py", 3),
    ("app.py", 3),
    ("index.py", 3),
    ("__main__.py", 3),
    ("cli.py", 3),
    # Priority 4: API definitions
    ("api/*", 4),
    ("routes/*", 4),
    ("endpoints/*", 4),
    # Priority 5: Core modules
    ("core/*", 5),
    ("src/main.*", 5),
    ("lib/*", 5),
]

# Fast-path exact filename matches (lowercase)
_FAST_PATH_NAMES = frozenset(
    {
        "readme.md",
        "readme.rst",
        "readme.txt",
        "pyproject.toml",
        "setup.py",
        "package.json",
        "cargo.toml",
        "go.mod",
        "main.py",
        "app.py",
        "index.py",
        "__main__.py",
        "cli.py",
    }
)

# Fast-path directory names (lowercase)
_FAST_PATH_DIRS = frozenset({"api", "routes", "endpoints", "core", "src", "lib"})


def is_fast_path_file(file_path: Path, project_root: Path) -> bool:
    """
    Check if file is a fast-path priority file.

    Args:
        file_path: Path to file
        project_root: Project root directory

    Returns:
        True if file should be indexed first
    """
    try:
        relative = file_path.relative_to(project_root)
    except ValueError:
        # File is not under project root
        return False

    name = relative.name.lower()

    # Check exact matches
    if name in _FAST_PATH_NAMES:
        return True

    # Check directory patterns
    parts = relative.parts
    if len(parts) >= 2:
        first_dir = parts[0].lower()
        if first_dir in _FAST_PATH_DIRS:
            return True

    return False


def get_file_priority(file_path: Path, project_root: Path) -> int:
    """
    Get priority level for a file (lower = higher priority).

    Args:
        file_path: Path to file
        project_root: Project root directory

    Returns:
        1-5 for fast-path files, 100 for normal files
    """
    try:
        relative = file_path.relative_to(project_root)
    except ValueError:
        # File is not under project root
        return 100

    name = relative.name.lower()

    # Priority 1: README
    if name.startswith("readme"):
        return 1

    # Priority 2: Config
    if name in {"pyproject.toml", "setup.py", "package.json", "cargo.toml", "go.mod"}:
        return 2

    # Priority 3: Entry points
    if name in {"main.py", "app.py", "index.py", "__main__.py", "cli.py"}:
        return 3

    # Priority 4-5: Directory-based
    parts = relative.parts
    if len(parts) >= 2:
        first_dir = parts[0].lower()
        if first_dir in {"api", "routes", "endpoints"}:
            return 4
        if first_dir in {"core", "src", "lib"}:
            return 5

    return 100  # Normal priority


def prioritize_files(files: List[Path], project_root: Path) -> List[Path]:
    """
    Sort files by priority (fast-path files first).

    Args:
        files: List of file paths
        project_root: Project root

    Returns:
        Sorted list with fast-path files first
    """
    return sorted(files, key=lambda f: get_file_priority(f, project_root))


def get_fast_path_files(files: List[Path], project_root: Path) -> List[Path]:
    """
    Get only the fast-path files from a list.

    Returns files with priority < 100.

    Args:
        files: List of file paths
        project_root: Project root directory

    Returns:
        List of fast-path files only
    """
    return [f for f in files if get_file_priority(f, project_root) < 100]
