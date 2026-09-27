#!/usr/bin/env python3
"""Comprehensive test for all language parsers using UnifiedCodeParser."""

from collections import defaultdict
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

from agentic_inquiry.parsers.implementations.unified_code import UnifiedCodeParser


# Map directory names to language names
LANG_MAP = {
    "py": "python",
    "js": "javascript",
    "ts": "typescript",
    "jsx": "jsx",
    "tsx": "tsx",
    "java": "java",
    "go": "go",
    "rs": "rust",
    "rb": "ruby",
    "c": "c",
    "cpp": "cpp",
    "cs": "c_sharp",
    "php": "php",
    "swift": "swift",
    "kt": "kotlin",
    "scala": "scala",
    "r": "r",
    "jl": "julia",
    "ex": "elixir",
    "elm": "elm",
    "ml": "ocaml",
    "lua": "lua",
    "dart": "dart",
    "groovy": "groovy",
    "apex": "apex",
    "pl": "perl",
    "f90": "fortran",
    "m": "matlab",
    "sh": "bash",
    "ps1": "powershell",
    "tf": "hcl",
    "dockerfile": "dockerfile",
    "sql": "sql",
    # Note: markdown (.md) is handled by DocumentParser, not UnifiedCodeParser
    # to preserve proper document structure and entity types (heading, section)
    "yaml": "yaml",
    "hs": "haskell",
    "zig": "zig",
}

# Minimum expected entity counts per language (conservative lower bounds)
# Languages with rich samples should extract at least this many entities
# These are intentionally conservative to avoid test brittleness
EXPECTED_MIN_ENTITIES = {
    "python": 2,  # Functions, classes, imports
    "javascript": 2,  # Functions, classes, exports
    "typescript": 2,  # Functions, classes, interfaces
    "java": 2,  # Classes, methods, imports
    "go": 1,  # Functions, types
    "rust": 1,  # Functions, structs, impls
    "ruby": 1,  # Classes, methods
    "c": 1,  # Functions
    "cpp": 1,  # Classes, functions
    "c_sharp": 1,  # Classes, methods
    "php": 1,  # Classes, functions
    "swift": 1,  # Classes, functions
    "kotlin": 1,  # Classes, functions
    "scala": 1,  # Classes, objects
    # Languages with simpler samples or limited tree-sitter support
    "jsx": 0,  # May have limited entity extraction
    "tsx": 0,  # May have limited entity extraction
    "r": 0,  # May have limited entity extraction
    "julia": 0,
    "elixir": 0,
    "elm": 0,
    "ocaml": 0,
    "lua": 0,
    "dart": 0,
    "groovy": 0,
    "apex": 2,
    "perl": 0,
    "fortran": 0,
    "matlab": 0,
    "bash": 0,
    "powershell": 0,
    "hcl": 0,
    "dockerfile": 0,
    "sql": 0,
    "yaml": 0,
    "haskell": 0,
    "zig": 0,
}

# Create a list of tuples for pytest parameterization
language_params = list(LANG_MAP.items())


@pytest.fixture(scope="module")
def parser():
    """Provides a single UnifiedCodeParser instance for the test module."""
    return UnifiedCodeParser()


@pytest.fixture(scope="module")
def samples_dir():
    """Provides the path to the code samples directory."""
    return Path("tests/parsers/samples/code")


async def _run_language_parse(
    lang_dir: Path, language: str, parser: UnifiedCodeParser
) -> dict:
    """Helper function to parse content for a single language."""
    files = [
        f for f in lang_dir.iterdir() if f.is_file() and not f.name.startswith(".")
    ]
    if not files:
        return {"status": "NO_FILES", "language": language}

    file_path = files[0]
    try:
        file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return {"status": "READ_ERROR", "language": language, "file": file_path.name}

    try:
        # Use the new parser interface - await the async parse call
        result = await parser.parse(str(file_path))

        # Extract symbols from chunks (symbols field contains extracted entities)
        all_symbols = []
        for chunk in result.chunks:
            if chunk.symbols:
                all_symbols.extend(chunk.symbols)

        # Also check metadata for elements (legacy format)
        all_elements = []
        for chunk in result.chunks:
            if chunk.metadata and "elements" in chunk.metadata:
                all_elements.extend(chunk.metadata["elements"])

        by_type = defaultdict(list)
        for elem in all_elements:
            by_type[elem.get("element_type", "unknown")].append(elem.get("name", ""))

        # Total entities = symbols + elements
        total_entities = len(all_symbols) + len(all_elements)

        has_imports = (
            "import" in by_type
            or "from_import" in by_type
            or any("import" in k for k in by_type)
        )

        return {
            "status": "SUCCESS",
            "language": language,
            "file": file_path.name,
            "total_elements": total_entities,
            "symbols": all_symbols,
            "symbol_count": len(all_symbols),
            "element_count": len(all_elements),
            "types": dict(by_type),
            "has_imports": has_imports,
            "type_counts": {k: len(v) for k, v in by_type.items()},
            "chunk_count": len(result.chunks),
        }
    except Exception as e:
        return {
            "status": "ERROR",
            "language": language,
            "file": file_path.name,
            "error": str(e),
            "error_type": type(e).__name__,
        }


@pytest.mark.asyncio
@pytest.mark.parametrize("lang_dir_name, language", language_params)
async def test_language_parser(
    lang_dir_name: str, language: str, parser: UnifiedCodeParser, samples_dir: Path
):
    """Tests that the parser can successfully process a sample file for each language."""
    lang_dir = samples_dir / lang_dir_name
    if not lang_dir.is_dir():
        pytest.skip(f"Sample directory not found for {language} ('{lang_dir_name}')")

    result = await _run_language_parse(lang_dir, language, parser)

    # Assert parsing succeeded
    assert result["status"] == "SUCCESS", (
        f"Language '{language}' failed parsing. "
        f"File: {result.get('file', 'N/A')}, "
        f"Status: {result['status']}, "
        f"Error: {result.get('error', 'N/A')}"
    )

    # Assert entity extraction meets minimum expectations
    min_expected = EXPECTED_MIN_ENTITIES.get(language, 0)
    actual_count = result.get("total_elements", 0)
    symbol_count = result.get("symbol_count", 0)
    chunk_count = result.get("chunk_count", 0)

    if min_expected > 0:
        assert actual_count >= min_expected, (
            f"Language '{language}' extracted {actual_count} entities "
            f"(symbols: {symbol_count}), expected at least {min_expected}. "
            f"Symbols: {result.get('symbols', [])}, Chunks: {chunk_count}"
        )

    # Log entity extraction info for debugging (visible with pytest -v -s)
    if actual_count > 0:
        symbols = result.get("symbols", [])
        print(
            f"\n  {language}: {actual_count} entities, {chunk_count} chunks, symbols={symbols}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
