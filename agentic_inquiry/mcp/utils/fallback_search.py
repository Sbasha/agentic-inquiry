"""Fallback search utilities for when the semantic index is unavailable.

This module provides fallback search mechanisms that work without the semantic
index, ensuring users always get some results even during initial indexing.

Chain of fallbacks:
1. ripgrep_search() - Fast text search using ripgrep (if available)
2. python_glob_search() - Pure Python fallback (always available)
3. ast_grep_search() - Structural code search using AST patterns (optional)

Usage:
    results = await execute_fallback_search(query, project_root)

Security measures are included to prevent command injection and directory
traversal attacks.

Metrics tracked:
- search.fallback.triggered: Total fallback searches
- search.fallback.success: Searches returning > 0 results
- search.fallback.empty: Searches returning 0 results
- search.fallback.errors.FileNotFoundError: Tool not installed
- search.fallback.errors.TimeoutError: Search timeouts
- search.fallback.engine.ripgrep: Ripgrep searches
- search.fallback.engine.python_glob: Pure-Python searches
- search.fallback.engine.ast_grep: AST-grep searches
"""
import asyncio
import json
import logging
import re
import shutil
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from agentic_inquiry.metrics import get_metrics_tracker

logger = logging.getLogger(__name__)

# Thread pool for blocking file I/O operations
_file_io_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="fallback_io")

# Limits to prevent hanging on large repositories
MAX_FILE_READ_BYTES = 1_000_000  # 1MB limit per file
MAX_FILES_SCANNED = 1_000  # Prevent hanging on large repos


@dataclass
class FallbackResult:
    """Result from fallback search.

    Attributes:
        file_path: Absolute path to the file containing the match.
        line_number: Line number of the match (1-indexed).
        content: The matched line content.
        score: Relevance score (default 1.0 for all results).
        match_type: Type of match ("text" for ripgrep, "structural" for ast-grep).
        language: Programming language (if detected).
        context_before: Lines before the match (if context requested).
        context_after: Lines after the match (if context requested).
        metadata: Additional metadata from the search tool.
    """
    file_path: str
    line_number: int
    content: str
    score: float = 1.0
    match_type: str = "text"
    language: Optional[str] = None
    context_before: Optional[str] = None
    context_after: Optional[str] = None
    metadata: dict[str, str | int | float | bool] = field(default_factory=dict)


def validate_result_path(file_path: str, project_root: Path) -> bool:
    """Ensure path is within project root (no traversal).

    This function validates that a file path returned from ripgrep
    is actually within the project root to prevent directory traversal
    attacks through malicious filenames or symlinks.

    Args:
        file_path: Path to validate (can be relative or absolute).
        project_root: Root directory that path must be within.

    Returns:
        True if path is within project root, False otherwise.

    Example:
        >>> validate_result_path("/project/src/foo.py", Path("/project"))
        True
        >>> validate_result_path("/etc/passwd", Path("/project"))
        False
    """
    try:
        resolved = Path(file_path).resolve()
        return resolved.is_relative_to(project_root.resolve())
    except (ValueError, RuntimeError):
        return False


async def ripgrep_search(
    query: str,
    project_root: Path,
    limit: int = 20,
    timeout: float = 10.0,
    file_patterns: Optional[List[str]] = None
) -> List[FallbackResult]:
    """Search using ripgrep with JSON output.

    Provides a fallback search mechanism for when the semantic index
    is sparse or unavailable. Uses ripgrep for fast text search with
    context support.

    Args:
        query: Literal text to search for, matched case-insensitively.
        project_root: Root directory to search.
        limit: Maximum number of results to return.
        timeout: Maximum seconds to wait for ripgrep.
        file_patterns: Optional file patterns to include (e.g., ["*.py", "*.md"]).

    Returns:
        List of FallbackResult containing matches.

    Raises:
        FileNotFoundError: If ripgrep (rg) is not installed.
        asyncio.TimeoutError: If search times out.

    Example:
        >>> results = await ripgrep_search("def foo", Path("/project"), limit=10)
        >>> for r in results:
        ...     print(f"{r.file_path}:{r.line_number}: {r.content}")

    Security:
        - Query follows '--', so it is never parsed as a flag.
        - Result paths are validated to prevent directory traversal.
        - Timeout protection prevents resource exhaustion.
    """
    # Check if ripgrep is installed
    if shutil.which("rg") is None:
        raise FileNotFoundError(
            "ripgrep (rg) not found. Install with: brew install ripgrep"
        )

    # Resolve project root to absolute path
    project_root = project_root.resolve()

    # Build ripgrep command
    # Use '--' to signal end of flags and prevent injection
    cmd = [
        "rg",
        "--json",                       # JSON output for parsing
        "--max-count", str(limit * 2),  # Get extra for filtering
        "--context", "2",               # Include 2 lines of context
        "--fixed-strings",              # Queries are free text, not regex
        "--ignore-case",                # Same matching as the Python fallback
        "--"                            # End of flags
    ]

    # Add query and project root
    cmd.append(query)
    cmd.append(str(project_root))

    # Add file patterns if specified
    if file_patterns:
        # Insert glob patterns before the query argument
        # Find the index of '--' and insert before it
        dash_index = cmd.index("--")
        for pattern in file_patterns:
            cmd.insert(dash_index, pattern)
            cmd.insert(dash_index, "--glob")
            dash_index += 2  # Adjust index for inserted items

    logger.debug("Executing ripgrep command: %s", cmd)

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=timeout
        )
    except FileNotFoundError:
        raise FileNotFoundError(
            "ripgrep (rg) not found. Install with: brew install ripgrep"
        )

    # Log any stderr output for debugging
    if stderr:
        stderr_text = stderr.decode("utf-8", errors="replace")
        if stderr_text.strip():
            logger.debug("ripgrep stderr: %s", stderr_text)

    # Parse JSON output
    results: List[FallbackResult] = []
    context_before: List[str] = []
    context_after: List[str] = []
    current_match: Optional[FallbackResult] = None

    for line in stdout.decode("utf-8", errors="replace").splitlines():
        if not line.strip():
            continue

        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("Failed to parse ripgrep JSON line: %s", line[:100])
            continue

        msg_type = data.get("type")

        if msg_type == "context":
            # Context line (before or after match)
            context_data = data.get("data", {})
            line_text = context_data.get("lines", {}).get("text", "").rstrip("\n")

            if current_match is None:
                # Context before next match
                context_before.append(line_text)
            else:
                # Context after previous match
                context_after.append(line_text)

        elif msg_type == "match":
            # If we have a previous match, finalize its context_after
            if current_match is not None:
                if context_after:
                    current_match.context_after = "\n".join(context_after)
                results.append(current_match)
                context_after = []

            # Parse match data
            match_data = data.get("data", {})
            file_path = match_data.get("path", {}).get("text", "")
            line_number = match_data.get("line_number", 0)
            content = match_data.get("lines", {}).get("text", "").rstrip("\n")

            # Validate path is within project root
            if not validate_result_path(file_path, project_root):
                logger.warning(
                    "Skipping result outside project root: %s", file_path
                )
                context_before = []
                current_match = None
                continue

            # Create result
            current_match = FallbackResult(
                file_path=file_path,
                line_number=line_number,
                content=content,
                score=1.0,
                context_before="\n".join(context_before) if context_before else None,
                context_after=None  # Will be filled when next match or end
            )
            context_before = []

        elif msg_type == "end":
            # End of results for a file
            if current_match is not None:
                if context_after:
                    current_match.context_after = "\n".join(context_after)
                results.append(current_match)
                current_match = None
                context_after = []
            context_before = []

    # Handle any remaining match
    if current_match is not None:
        if context_after:
            current_match.context_after = "\n".join(context_after)
        results.append(current_match)

    # Limit results and return
    return results[:limit]


def _is_binary_file(file_path: Path) -> bool:
    """Check if file appears to be binary (contains null bytes).

    Args:
        file_path: Path to the file to check.

    Returns:
        True if file appears to be binary, False otherwise.
    """
    try:
        with open(file_path, "rb") as f:
            chunk = f.read(1024)
            return b"\x00" in chunk
    except Exception:
        return True  # Assume binary if can't read


def _sync_python_glob_search(
    query: str,
    project_root: Path,
    limit: int = 20,
    file_patterns: Optional[List[str]] = None,
) -> List[dict]:
    """Synchronous implementation of pure-Python search.

    IMPORTANT: This is blocking I/O, MUST run in executor, not event loop.

    Args:
        query: Search query string.
        project_root: Root directory to search in.
        limit: Maximum number of results to return.
        file_patterns: List of glob patterns to match files against.

    Returns:
        List of dicts with file_path, line_number, content keys.
    """
    if file_patterns is None:
        file_patterns = ["**/*.py", "**/*.md", "**/*.yaml", "**/*.json", "**/*.txt"]

    results: List[dict] = []
    files_scanned = 0

    # Build regex for structural queries
    structural_pattern: Optional[re.Pattern[str]] = None
    query_lower = query.lower()
    if "class" in query_lower:
        structural_pattern = re.compile(r"^\s*class\s+\w+", re.MULTILINE)
    elif "def" in query_lower or "function" in query_lower:
        structural_pattern = re.compile(r"^\s*(async\s+)?def\s+\w+", re.MULTILINE)

    # Simple text pattern for fallback
    text_pattern = re.compile(re.escape(query), re.IGNORECASE)

    for glob_pattern in file_patterns:
        if len(results) >= limit or files_scanned >= MAX_FILES_SCANNED:
            break

        try:
            for file_path in project_root.glob(glob_pattern):
                if files_scanned >= MAX_FILES_SCANNED:
                    break
                if not file_path.is_file():
                    continue
                if _is_binary_file(file_path):
                    continue

                files_scanned += 1

                try:
                    with open(file_path, "r", errors="ignore") as f:
                        content = f.read(MAX_FILE_READ_BYTES)

                    # Use structural pattern if available, else text
                    pattern = structural_pattern or text_pattern

                    for match in pattern.finditer(content):
                        # Calculate line number
                        line_num = content[: match.start()].count("\n") + 1
                        lines = content.split("\n")
                        line_content = (
                            lines[line_num - 1] if 0 < line_num <= len(lines) else ""
                        )

                        results.append(
                            {
                                "file_path": str(file_path.relative_to(project_root)),
                                "line_number": line_num,
                                "content": line_content.strip()[:200],
                            }
                        )

                        if len(results) >= limit:
                            break

                except Exception as e:
                    logger.debug("Error reading file %s: %s", file_path, e)
                    continue

                if len(results) >= limit:
                    break

        except Exception as e:
            logger.debug("Error with glob pattern %s: %s", glob_pattern, e)
            continue

    return results


async def python_glob_search(
    query: str,
    project_root: Path,
    limit: int = 20,
    timeout: float = 5.0,
    file_patterns: Optional[List[str]] = None,
) -> List[FallbackResult]:
    """Pure-Python fallback search - always available.

    Uses pathlib.glob() and string matching. Slower than ripgrep but has
    zero external dependencies.

    CRITICAL: Uses ThreadPoolExecutor to avoid blocking event loop.

    Args:
        query: Search query string.
        project_root: Root directory to search in.
        limit: Maximum number of results to return.
        timeout: Maximum time to wait for search (seconds).
        file_patterns: List of glob patterns to match files against.

    Returns:
        List of FallbackResult objects.
    """
    loop = asyncio.get_running_loop()

    try:
        raw_results = await asyncio.wait_for(
            loop.run_in_executor(
                _file_io_executor,
                _sync_python_glob_search,
                query,
                project_root,
                limit,
                file_patterns,
            ),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        logger.warning("Python glob search timed out after %s seconds", timeout)
        return []

    # Convert to FallbackResult with decreasing scores
    return [
        FallbackResult(
            file_path=r["file_path"],
            line_number=r["line_number"],
            content=r["content"],
            score=1.0 / (i + 1),  # Decreasing score based on order
            match_type="text",
        )
        for i, r in enumerate(raw_results)
    ]


async def execute_fallback_search(
    query: str,
    project_root: Path,
    limit: int = 20,
    prefer_ripgrep: bool = True,
) -> dict:
    """Execute fallback search with chain: ripgrep -> python_glob -> error.

    This function provides a resilient search that always returns results
    or a helpful error message.

    Args:
        query: Search query string.
        project_root: Root directory to search in.
        limit: Maximum number of results to return.
        prefer_ripgrep: If True, try ripgrep first before python_glob.

    Returns:
        Dict with keys:
        - results: List of FallbackResult objects
        - source: "ripgrep" | "python_glob"
        - source_note: Human-readable description of the source
        - fallback_error: Error message if applicable
        - guidance: Troubleshooting guidance if applicable
    """
    metrics = get_metrics_tracker()

    # Track that fallback was triggered
    metrics.increment("search.fallback.triggered")

    # Try ripgrep first if preferred
    if prefer_ripgrep:
        try:
            results = await ripgrep_search(query, project_root, limit)
            metrics.increment("search.fallback.engine.ripgrep")

            if results:
                metrics.increment("search.fallback.success")
            else:
                metrics.increment("search.fallback.empty")

            return {
                "results": results,
                "source": "ripgrep",
                "source_note": "Results from static text search (ripgrep)",
            }
        except FileNotFoundError:
            metrics.increment("search.fallback.errors.FileNotFoundError")
            logger.debug("ripgrep not available, falling back to python_glob")
            # Fall through to python_glob
        except asyncio.TimeoutError:
            metrics.increment("search.fallback.errors.TimeoutError")
            metrics.increment("search.fallback.empty")
            return {
                "results": [],
                "source": "ripgrep",
                "fallback_error": "Search timed out",
                "guidance": "Try a more specific query",
            }
        except Exception as e:
            logger.warning("ripgrep search failed: %s", e)
            # Fall through to python_glob

    # Always available fallback
    try:
        results = await python_glob_search(query, project_root, limit)
        metrics.increment("search.fallback.engine.python_glob")

        if results:
            metrics.increment("search.fallback.success")
        else:
            metrics.increment("search.fallback.empty")

        return {
            "results": results,
            "source": "python_glob",
            "source_note": "Results from basic file search (semantic index still building)",
        }
    except asyncio.TimeoutError:
        metrics.increment("search.fallback.errors.TimeoutError")
        metrics.increment("search.fallback.empty")
        return {
            "results": [],
            "source": "python_glob",
            "fallback_error": "Search timed out",
            "guidance": "Try a more specific query or reduce the search scope",
        }
    except Exception as e:
        logger.error("python_glob search failed: %s", e)
        metrics.increment("search.fallback.empty")
        return {
            "results": [],
            "source": "python_glob",
            "fallback_error": f"Search failed: {e}",
            "guidance": "Check file permissions and try again",
        }


def is_structural_query(query: str) -> bool:
    """Detect if query is asking for structural code elements.

    Args:
        query: Search query string.

    Returns:
        True if query appears to be looking for code structure.
    """
    query_lower = query.lower()
    structural_keywords = [
        "class",
        "def",
        "function",
        "method",
        "import",
        "from",
        "interface",
        "struct",
        "enum",
        "type",
    ]
    return any(keyword in query_lower for keyword in structural_keywords)


def should_use_fallback(
    index_status: str,
    results_empty: bool,
) -> bool:
    """Determine if fallback search should be used.

    Args:
        index_status: Current index status ("ready", "indexing", "sparse", "empty").
        results_empty: Whether the primary search returned empty results.

    Returns:
        True if fallback search should be used.
    """
    # Always use fallback if no results and index isn't ready
    if results_empty and index_status in ("indexing", "embedding", "sparse", "empty"):
        return True

    # Don't use fallback if index is ready (even with empty results)
    return False


# ============================================================================
# AST-Grep Structural Search
# ============================================================================


class AstGrepNotFoundError(FileNotFoundError):
    """Raised when ast-grep is not installed.

    This exception provides guidance on how to install ast-grep.
    """

    def __init__(self) -> None:
        super().__init__(
            "ast-grep (sg) not found. Install with: cargo install ast-grep --locked "
            "or brew install ast-grep (macOS) "
            "or see https://ast-grep.github.io/guide/quick-start.html"
        )


# Python patterns for common structural queries
PYTHON_PATTERNS: dict[str, str] = {
    "class": "class $NAME: $$$BODY",
    "classes": "class $NAME: $$$BODY",
    "function": "def $NAME($$$ARGS): $$$BODY",
    "functions": "def $NAME($$$ARGS): $$$BODY",
    "def": "def $NAME($$$ARGS): $$$BODY",
    "method": "def $NAME($$$ARGS): $$$BODY",
    "methods": "def $NAME($$$ARGS): $$$BODY",
    "async function": "async def $NAME($$$ARGS): $$$BODY",
    "async functions": "async def $NAME($$$ARGS): $$$BODY",
    "async def": "async def $NAME($$$ARGS): $$$BODY",
    "async": "async def $NAME($$$ARGS): $$$BODY",
    "import": "import $MODULE",
    "imports": "import $MODULE",
    "from import": "from $MODULE import $NAME",
    "from imports": "from $MODULE import $NAME",
    "decorator": "@$DECORATOR",
    "decorators": "@$DECORATOR",
    "with": "with $EXPR as $NAME: $$$BODY",
    "try": "try: $$$BODY",
    "except": "except $EXCEPTION: $$$BODY",
    "for loop": "for $VAR in $ITER: $$$BODY",
    "while loop": "while $COND: $$$BODY",
    "if": "if $COND: $$$BODY",
    "lambda": "lambda $$$ARGS: $BODY",
    "list comprehension": "[$EXPR for $VAR in $ITER]",
    "dict comprehension": "{$KEY: $VAL for $VAR in $ITER}",
    "yield": "yield $EXPR",
    "return": "return $EXPR",
    "raise": "raise $EXCEPTION",
    "assert": "assert $EXPR",
    "dataclass": "@dataclass\nclass $NAME: $$$BODY",
}

# JavaScript/TypeScript patterns
JS_TS_PATTERNS: dict[str, str] = {
    "class": "class $NAME { $$$BODY }",
    "classes": "class $NAME { $$$BODY }",
    "function": "function $NAME($$$ARGS) { $$$BODY }",
    "functions": "function $NAME($$$ARGS) { $$$BODY }",
    "arrow": "const $NAME = ($$$ARGS) => $$$BODY",
    "arrow function": "const $NAME = ($$$ARGS) => $$$BODY",
    "arrow functions": "const $NAME = ($$$ARGS) => $$$BODY",
    "import": "import $NAME from '$MODULE'",
    "imports": "import $NAME from '$MODULE'",
    "export": "export $DECL",
    "exports": "export $DECL",
    "export default": "export default $EXPR",
    "async function": "async function $NAME($$$ARGS) { $$$BODY }",
    "async functions": "async function $NAME($$$ARGS) { $$$BODY }",
    "interface": "interface $NAME { $$$BODY }",
    "type": "type $NAME = $TYPE",
    "const": "const $NAME = $VALUE",
    "let": "let $NAME = $VALUE",
    "for loop": "for ($INIT; $COND; $UPDATE) { $$$BODY }",
    "for of": "for (const $VAR of $ITER) { $$$BODY }",
    "if": "if ($COND) { $$$BODY }",
    "try": "try { $$$BODY }",
    "catch": "catch ($ERR) { $$$BODY }",
    "await": "await $EXPR",
    "jsx element": "<$TAG $$$PROPS>$$$CHILDREN</$TAG>",
    "jsx component": "<$COMPONENT $$$PROPS />",
}

# Language to patterns mapping
LANGUAGE_PATTERNS: dict[str, dict[str, str]] = {
    "python": PYTHON_PATTERNS,
    "javascript": JS_TS_PATTERNS,
    "typescript": JS_TS_PATTERNS,
    "jsx": JS_TS_PATTERNS,
    "tsx": JS_TS_PATTERNS,
}

# Keywords that indicate structural queries (more comprehensive than is_structural_query)
STRUCTURAL_KEYWORDS: frozenset[str] = frozenset([
    "class", "classes",
    "function", "functions", "def",
    "method", "methods",
    "import", "imports",
    "decorator", "decorators",
    "async",
    "interface", "interfaces",
    "type", "types",
    "export", "exports",
    "const", "let", "var",
    "arrow",
    "lambda",
    "for loop", "while loop",
    "try", "catch", "except",
    "with", "yield", "return", "raise",
])


def is_structural_query_extended(query: str) -> bool:
    """Extended structural query detection with more patterns.

    This function provides more comprehensive detection than is_structural_query()
    and is used specifically for ast-grep pattern selection.

    Args:
        query: The search query to analyze.

    Returns:
        True if the query appears to be asking for structural elements.

    Examples:
        >>> is_structural_query_extended("find all classes")
        True
        >>> is_structural_query_extended("show me async functions")
        True
        >>> is_structural_query_extended("list arrow functions")
        True
        >>> is_structural_query_extended("authentication error")
        False
    """
    query_lower = query.lower()

    # Check for multi-word patterns first (more specific)
    multi_word_patterns = [
        "async function", "async functions", "async def",
        "arrow function", "arrow functions",
        "for loop", "while loop",
        "list comprehension", "dict comprehension",
        "from import", "from imports",
        "export default",
    ]
    for pattern in multi_word_patterns:
        if pattern in query_lower:
            return True

    # Check for single keywords
    words = set(query_lower.split())
    return bool(words & STRUCTURAL_KEYWORDS)


def map_query_to_ast_pattern(query: str, language: str = "python") -> Optional[str]:
    """Map a natural language query to an ast-grep pattern.

    This function converts common natural language queries about code
    structure into ast-grep patterns that can be used for structural search.

    Args:
        query: Natural language query (e.g., "find all classes").
        language: Target programming language (python, javascript, typescript).

    Returns:
        An ast-grep pattern string if a mapping is found, None otherwise.

    Examples:
        >>> map_query_to_ast_pattern("find all classes", "python")
        'class $NAME: $$$BODY'
        >>> map_query_to_ast_pattern("find functions", "python")
        'def $NAME($$$ARGS): $$$BODY'
        >>> map_query_to_ast_pattern("show imports", "python")
        'import $MODULE'
        >>> map_query_to_ast_pattern("unknown query", "python")
        None
    """
    query_lower = query.lower()

    # Get patterns for the specified language
    patterns = LANGUAGE_PATTERNS.get(language.lower())
    if not patterns:
        logger.warning("No patterns available for language: %s", language)
        return None

    # Check multi-word patterns first (more specific)
    multi_word_matches = [
        ("async function", patterns.get("async function")),
        ("async functions", patterns.get("async functions")),
        ("async def", patterns.get("async def")),
        ("arrow function", patterns.get("arrow function")),
        ("arrow functions", patterns.get("arrow functions")),
        ("from import", patterns.get("from import")),
        ("from imports", patterns.get("from imports")),
        ("for loop", patterns.get("for loop")),
        ("while loop", patterns.get("while loop")),
        ("for of", patterns.get("for of")),
        ("list comprehension", patterns.get("list comprehension")),
        ("dict comprehension", patterns.get("dict comprehension")),
        ("export default", patterns.get("export default")),
        ("jsx element", patterns.get("jsx element")),
        ("jsx component", patterns.get("jsx component")),
    ]

    for keyword, pattern in multi_word_matches:
        if keyword in query_lower and pattern:
            return pattern

    # Check single-word patterns
    for keyword, pattern in patterns.items():
        if keyword in query_lower:
            return pattern

    return None


def _find_ast_grep_executable() -> Optional[str]:
    """Find the ast-grep executable.

    Returns:
        Path to the ast-grep executable, or None if not found.
    """
    # Try common names
    for name in ["sg", "ast-grep"]:
        path = shutil.which(name)
        if path:
            return path
    return None


async def ast_grep_search(
    query: str,
    project_root: Path,
    language: str = "python",
    limit: int = 20,
    timeout: float = 10.0
) -> List[FallbackResult]:
    """Search for structural patterns using ast-grep.

    This function performs structural code search using ast-grep, which
    understands the abstract syntax tree (AST) of code. It can find
    structural patterns like classes, functions, imports, etc.

    Args:
        query: Natural language query OR ast-grep pattern.
        project_root: Root directory to search.
        language: Language to search (python, javascript, typescript, etc.).
        limit: Maximum number of results to return.
        timeout: Maximum seconds to wait for ast-grep.

    Returns:
        List of FallbackResult objects containing matches.

    Raises:
        AstGrepNotFoundError: If ast-grep is not installed.
        asyncio.TimeoutError: If the search exceeds the timeout.

    Examples:
        >>> results = await ast_grep_search(
        ...     "find all classes",
        ...     Path("/my/project"),
        ...     language="python"
        ... )
        >>> results = await ast_grep_search(
        ...     "class $NAME: $$$BODY",  # Direct pattern
        ...     Path("/my/project"),
        ...     language="python"
        ... )

    Security:
        - Result paths are validated to prevent directory traversal.
        - Timeout protection prevents resource exhaustion.
    """
    # Find ast-grep executable
    sg_path = _find_ast_grep_executable()
    if not sg_path:
        raise AstGrepNotFoundError()

    # Resolve project root to absolute path
    project_root = project_root.resolve()

    # Determine the pattern to use
    # If query contains ast-grep pattern syntax ($ for metavariables), use it directly
    pattern: str
    if "$" in query:
        pattern = query
    else:
        mapped_pattern = map_query_to_ast_pattern(query, language)
        if not mapped_pattern:
            logger.debug(
                "Could not map query to ast-grep pattern: %s (language=%s)",
                query, language
            )
            return []
        pattern = mapped_pattern

    # Build command
    cmd = [
        sg_path,
        "--json",
        "--pattern", pattern,
        "--lang", language,
        str(project_root)
    ]

    logger.debug("Running ast-grep: %s", " ".join(cmd))

    try:
        # Run ast-grep
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(project_root)
        )

        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=timeout
        )

        if process.returncode != 0:
            stderr_text = stderr.decode("utf-8", errors="replace")
            if stderr_text:
                logger.warning("ast-grep stderr: %s", stderr_text)
            # Return empty results on non-zero exit (no matches or error)
            return []

        # Parse JSON output
        output = stdout.decode("utf-8", errors="replace")
        if not output.strip():
            return []

        results: List[FallbackResult] = []

        # ast-grep outputs one JSON object per line (JSONL format)
        for line in output.strip().split("\n"):
            if not line.strip():
                continue

            try:
                match = json.loads(line)

                # Extract match data
                file_path = match.get("file", "")

                # Validate path is within project root
                if not validate_result_path(file_path, project_root):
                    logger.warning(
                        "Skipping result outside project root: %s", file_path
                    )
                    continue

                text = match.get("text", "")

                # Get range information
                range_info = match.get("range", {})
                start = range_info.get("start", {})
                line_number = start.get("line", 0)
                # ast-grep uses 0-indexed lines, convert to 1-indexed
                if isinstance(line_number, int):
                    line_number += 1

                # Build metadata
                metadata: dict[str, str | int | float | bool] = {
                    "pattern": pattern,
                }

                # Add rule_id if present
                rule_id = match.get("ruleId", "")
                if rule_id:
                    metadata["rule_id"] = rule_id

                # Add column information if available
                if "column" in start:
                    metadata["column"] = start["column"]

                # Add end position if available
                end = range_info.get("end", {})
                if "line" in end:
                    metadata["end_line"] = end["line"] + 1  # Convert to 1-indexed
                if "column" in end:
                    metadata["end_column"] = end["column"]

                results.append(FallbackResult(
                    file_path=file_path,
                    line_number=line_number,
                    content=text,
                    score=1.0,
                    match_type="structural",
                    language=language,
                    metadata=metadata
                ))

                if len(results) >= limit:
                    break

            except json.JSONDecodeError as e:
                logger.warning("Failed to parse ast-grep JSON output: %s", e)
                continue

        logger.debug("ast-grep found %d matches", len(results))
        return results

    except asyncio.TimeoutError:
        logger.warning("ast-grep search timed out after %s seconds", timeout)
        raise


async def structural_search(
    query: str,
    project_root: Path,
    language: str = "python",
    limit: int = 20,
    timeout: float = 10.0,
) -> dict:
    """Execute structural search with fallback chain: ast-grep -> python_glob.

    This function attempts ast-grep first for precise structural matching,
    then falls back to Python glob search with regex patterns.

    Args:
        query: Search query (natural language or ast-grep pattern).
        project_root: Root directory to search.
        language: Target language for structural search.
        limit: Maximum number of results.
        timeout: Maximum seconds for the search.

    Returns:
        Dict with keys:
        - results: List of FallbackResult objects
        - source: "ast_grep" | "python_glob"
        - source_note: Human-readable description
        - fallback_error: Error message if applicable
    """
    metrics = get_metrics_tracker()

    # Track that fallback was triggered (structural search is also a fallback)
    metrics.increment("search.fallback.triggered")

    # Try ast-grep first for structural queries
    if is_structural_query_extended(query):
        try:
            results = await ast_grep_search(
                query=query,
                project_root=project_root,
                language=language,
                limit=limit,
                timeout=timeout
            )
            metrics.increment("search.fallback.engine.ast_grep")

            if results:
                metrics.increment("search.fallback.success")
                return {
                    "results": results,
                    "source": "ast_grep",
                    "source_note": "Results from AST-based structural search (ast-grep)",
                }
            else:
                # No results from ast-grep, fall through to python_glob
                metrics.increment("search.fallback.empty")
        except AstGrepNotFoundError:
            metrics.increment("search.fallback.errors.FileNotFoundError")
            logger.info("ast-grep not available, falling back to python_glob")
        except asyncio.TimeoutError:
            metrics.increment("search.fallback.errors.TimeoutError")
            metrics.increment("search.fallback.empty")
            return {
                "results": [],
                "source": "ast_grep",
                "fallback_error": "Structural search timed out",
                "guidance": "Try a more specific query or reduce scope",
            }
        except Exception as e:
            logger.warning("ast-grep search failed: %s", e)

    # Fall back to python_glob with structural patterns
    # Build file patterns based on language
    lang_extensions: dict[str, List[str]] = {
        "python": ["**/*.py"],
        "javascript": ["**/*.js", "**/*.mjs", "**/*.cjs"],
        "typescript": ["**/*.ts", "**/*.tsx"],
        "jsx": ["**/*.jsx", "**/*.js"],
        "tsx": ["**/*.tsx", "**/*.ts"],
    }
    file_patterns = lang_extensions.get(language.lower(), ["**/*.py"])

    try:
        results = await python_glob_search(
            query=query,
            project_root=project_root,
            limit=limit,
            timeout=timeout,
            file_patterns=file_patterns,
        )
        metrics.increment("search.fallback.engine.python_glob")

        if results:
            metrics.increment("search.fallback.success")
        else:
            metrics.increment("search.fallback.empty")

        return {
            "results": results,
            "source": "python_glob",
            "source_note": "Results from pattern-based search (ast-grep not available)",
        }
    except asyncio.TimeoutError:
        metrics.increment("search.fallback.errors.TimeoutError")
        metrics.increment("search.fallback.empty")
        return {
            "results": [],
            "source": "python_glob",
            "fallback_error": "Search timed out",
            "guidance": "Try a more specific query",
        }
    except Exception as e:
        logger.error("python_glob structural search failed: %s", e)
        metrics.increment("search.fallback.empty")
        return {
            "results": [],
            "source": "python_glob",
            "fallback_error": f"Search failed: {e}",
        }


def get_fallback_success_rate() -> float:
    """Calculate fallback search success rate.

    Computes the ratio of successful fallback searches (those returning
    at least one result) to total fallback searches triggered.

    Returns:
        Success rate as a float between 0.0 and 1.0.
        Returns 0.0 if no fallback searches have been triggered.

    Example:
        >>> rate = get_fallback_success_rate()
        >>> print(f"Fallback search success rate: {rate:.1%}")
        Fallback search success rate: 75.0%
    """
    metrics = get_metrics_tracker()
    total = metrics.get("search.fallback.triggered", 0)
    success = metrics.get("search.fallback.success", 0)

    if total == 0:
        return 0.0
    return success / total


def get_fallback_metrics_summary() -> dict:
    """Get a summary of all fallback search metrics.

    Returns:
        Dictionary with fallback-specific metrics including:
        - triggered: Total fallback searches
        - success: Successful searches (> 0 results)
        - empty: Empty result searches
        - success_rate: Computed success rate
        - engines: Per-engine breakdown
        - errors: Error type breakdown
    """
    metrics = get_metrics_tracker()

    triggered = metrics.get("search.fallback.triggered", 0)
    success = metrics.get("search.fallback.success", 0)
    empty = metrics.get("search.fallback.empty", 0)

    return {
        "triggered": triggered,
        "success": success,
        "empty": empty,
        "success_rate": get_fallback_success_rate(),
        "engines": {
            "ripgrep": metrics.get("search.fallback.engine.ripgrep", 0),
            "python_glob": metrics.get("search.fallback.engine.python_glob", 0),
            "ast_grep": metrics.get("search.fallback.engine.ast_grep", 0),
        },
        "errors": {
            "FileNotFoundError": metrics.get(
                "search.fallback.errors.FileNotFoundError", 0
            ),
            "TimeoutError": metrics.get("search.fallback.errors.TimeoutError", 0),
        },
    }
