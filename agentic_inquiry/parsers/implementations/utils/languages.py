"""Consolidated language registry for code parsers.

Single source of truth for language mappings, supporting both extension-based
and content-based detection with tree-sitter language mappings.

Copied from akb_iq and adapted for the new parser registry system.
"""

import os
from pathlib import Path
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


class LanguageRegistry:
    """Unified language registry consolidating all language mappings."""

    # Complete language mapping - merged from all sources
    LANGUAGE_MAP: Dict[str, str] = {
        # Python
        ".py": "python",
        # JavaScript/TypeScript
        ".js": "javascript",
        ".mjs": "javascript",
        ".cjs": "javascript",
        ".ts": "typescript",
        ".tsx": "tsx",
        ".jsx": "jsx",
        # Compiled languages
        ".java": "java",
        ".c": "c",
        ".h": "c",
        ".cpp": "cpp",
        ".cc": "cpp",
        ".cxx": "cpp",
        ".hpp": "cpp",
        ".hh": "cpp",
        ".hxx": "cpp",
        ".cs": "c_sharp",
        ".go": "go",
        ".rs": "rust",
        # Web languages
        ".php": "php",
        ".rb": "ruby",
        ".swift": "swift",
        # JVM languages
        ".kt": "kotlin",
        ".kts": "kotlin",
        ".scala": "scala",
        ".sc": "scala",
        ".groovy": "groovy",
        # Scientific/Math
        ".r": "r",
        ".R": "r",
        ".m": "matlab",
        ".jl": "julia",
        # Scripting
        ".lua": "lua",
        ".dart": "dart",
        ".elm": "elm",
        # Functional languages
        ".ex": "elixir",
        ".exs": "elixir",
        ".erl": "erlang",
        ".hrl": "erlang",
        ".fs": "fsharp",
        ".fsi": "fsharp",
        ".fsx": "fsharp",
        ".hs": "haskell",
        ".lhs": "haskell",
        ".ml": "ocaml",
        ".clj": "clojure",
        ".cljs": "clojure",
        ".cljc": "clojure",
        ".lisp": "commonlisp",
        ".lsp": "commonlisp",
        # Systems languages
        ".nim": "nim",
        ".nix": "nix",
        ".d": "d",
        ".zig": "zig",
        # Scripting/Shell
        ".pl": "perl",
        ".pm": "perl",
        ".sh": "bash",
        ".bash": "bash",
        ".zsh": "bash",
        ".fish": "fish",
        ".ps1": "powershell",
        ".psm1": "powershell",
        # Data/Config
        ".sql": "sql",
        ".rq": "sparql",
        ".json": "json",
        ".jsonc": "json",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".toml": "toml",
        ".ini": "ini",
        ".cfg": "ini",
        ".conf": "ini",
        # Web/Markup
        ".html": "html",
        ".htm": "html",
        ".xml": "xml",
        ".xsl": "xml",
        ".xslt": "xml",
        ".css": "css",
        ".scss": "scss",
        ".sass": "sass",
        ".less": "less",
        # Documentation
        # Note: .md and .markdown are handled by DocumentParser which provides
        # proper entity types (heading, section) and document structure relationships.
        # UnifiedCodeParser treats them as code which loses semantic document structure.
        ".rst": "rst",
        ".tex": "latex",
        ".vim": "vim",
        ".vimrc": "vim",
        # Containers/Infrastructure
        ".dockerfile": "dockerfile",
        ".Dockerfile": "dockerfile",
        ".tf": "hcl",
        ".hcl": "hcl",
        # Hardware/Embedded
        ".sol": "solidity",
        ".apex": "apex",
        ".cls": "apex",
        ".trigger": "apex",
        ".v": "verilog",
        ".vh": "verilog",
        ".sv": "systemverilog",
        ".svh": "systemverilog",
        ".vhd": "vhdl",
        ".vhdl": "vhdl",
        ".adb": "ada",
        ".ads": "ada",
        ".f90": "fortran",
        ".f95": "fortran",
        ".f03": "fortran",
        ".s": "asm",
        ".asm": "asm",
        # Arduino
        ".ino": "arduino",
        ".pde": "arduino",
        # Chatito (NLU training data)
        ".chatito": "chatito",
        # Emacs Lisp
        ".el": "elisp",
        # Gleam
        ".gleam": "gleam",
        # OCaml interface files
        ".mli": "ocaml_interface",
        # Pony
        ".pony": "pony",
        # Properties files
        ".properties": "properties",
        # Racket/Scheme
        ".rkt": "racket",
        # Note: .scm excluded - tree-sitter query files, not Racket code
        ".ss": "racket",
        # udev rules
        ".rules": "udev",
        # Assembly (tree-sitter uses 'asm')
        ".S": "asm",
        # CMake
        "CMakeLists.txt": "cmake",
        ".cmake": "cmake",
        # GraphQL
        ".graphql": "graphql",
        ".gql": "graphql",
        # Protocol Buffers
        ".proto": "proto",
        # Thrift
        ".thrift": "thrift",
        # CUDA
        ".cu": "cuda",
        ".cuh": "cuda",
        # Vue
        ".vue": "vue",
        # Svelte
        ".svelte": "svelte",
        # Makefile
        "Makefile": "make",
        "makefile": "make",
        "GNUmakefile": "make",
        ".mk": "make",
        # Objective-C
        ".mm": "objc",
        # Rego (Open Policy Agent)
        ".rego": "rego",
        # Starlark (Bazel)
        "BUILD": "starlark",
        "BUILD.bazel": "starlark",
        "WORKSPACE": "starlark",
        "WORKSPACE.bazel": "starlark",
        ".bzl": "starlark",
        ".star": "starlark",
    }

    @classmethod
    def get_language(cls, file_path: Path) -> Optional[str]:
        """Get language for a file path.

        Checks both the file extension and the full filename for special cases
        like Makefile, CMakeLists.txt, BUILD, etc.
        """
        # First check full filename for special cases (Makefile, CMakeLists.txt, etc.)
        filename = file_path.name
        if filename in cls.LANGUAGE_MAP:
            return cls.LANGUAGE_MAP[filename]

        # Then check extension
        suffix = file_path.suffix.lower()
        return cls.LANGUAGE_MAP.get(suffix)

    @classmethod
    def get_extensions(cls, language: str) -> List[str]:
        """Get all extensions for a language."""
        return [ext for ext, lang in cls.LANGUAGE_MAP.items() if lang == language]

    @classmethod
    def get_tree_sitter_languages(
        cls, queries_path: Optional[Path] = None
    ) -> Dict[str, str]:
        """Build language map from available tree-sitter query files.

        Note: Only counts actual .scm query files, not -tags.scm files.
        The -tags.scm files use different capture conventions and are not
        compatible with the QueryLoader's extraction logic.
        """
        if queries_path is None:
            queries_path = Path(__file__).parent.parent / "queries"

        if not queries_path.exists():
            return {}

        supported_languages = set()
        for filename in os.listdir(queries_path):
            # Only count actual .scm files, NOT -tags.scm files
            # -tags.scm files use different capture conventions (@name, @definition.class)
            # that aren't compatible with our parser's extraction logic (@class.name, @class.def)
            if filename.endswith(".scm") and not filename.endswith("-tags.scm"):
                lang = filename.replace(".scm", "")
                supported_languages.add(lang)

        return {
            ext: lang
            for ext, lang in cls.LANGUAGE_MAP.items()
            if lang in supported_languages
        }

    @classmethod
    def all_languages(cls) -> set[str]:
        """Get all supported language names."""
        return set(cls.LANGUAGE_MAP.values())


# Global language registry instance
_language_registry = LanguageRegistry()


def get_language_registry() -> LanguageRegistry:
    """Get the global language registry instance.

    Returns:
        Global LanguageRegistry instance
    """
    return _language_registry


def detect_language(file_path: Path) -> Optional[str]:
    """Convenience function to detect language from a file path.

    Args:
        file_path: Path to the file

    Returns:
        Language name or None if not detected
    """
    return _language_registry.get_language(file_path)
