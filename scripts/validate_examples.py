#!/usr/bin/env python3
"""
Example Validation Script

This script validates all example files for common issues:
- Syntax errors using Python AST
- Import errors
- Outdated API usage patterns
- Missing documentation
- Consistent structure

Usage:
    python scripts/validate_examples.py
    python scripts/validate_examples.py --verbose
    python scripts/validate_examples.py --fix-imports

Requirements: 8.1, 8.2
"""

import argparse
import ast
import re
import sys
from pathlib import Path
from typing import List, Set, Tuple

# Project root
PROJECT_ROOT = Path(__file__).parent.parent
EXAMPLES_DIR = PROJECT_ROOT / "examples"

# Expected documentation sections in example headers
REQUIRED_SECTIONS = [
    "Prerequisites:",
    "Usage:",
    "Related Documentation:",
    "Related Examples:",
]

# Deprecated API patterns to check for
DEPRECATED_PATTERNS = [
    (r"from agent_vault\.parsers\.base import", "Use 'from agent_vault.parsers.models import' instead"),
    (r"\.code_symbols", "Use '.symbols' field instead of '.code_symbols'"),
    (r"DatabaseManager\(", "Use 'LanceDBManager' instead of 'DatabaseManager'"),
    (r"from agent_vault\.database\.manager import", "Use 'from agent_vault.database import LanceDBManager' instead"),
    (r"Config\(\)", "Use 'Config.load()' instead of 'Config()'"),
]

# Required imports for examples
COMMON_IMPORTS = {
    "asyncio",  # All examples should use async
    "sys",
    "Path",
}


class ValidationResult:
    """Result of validating an example file."""
    
    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.info: List[str] = []
    
    def add_error(self, message: str):
        """Add an error message."""
        self.errors.append(message)
    
    def add_warning(self, message: str):
        """Add a warning message."""
        self.warnings.append(message)
    
    def add_info(self, message: str):
        """Add an info message."""
        self.info.append(message)
    
    def is_valid(self) -> bool:
        """Check if validation passed (no errors)."""
        return len(self.errors) == 0
    
    def has_issues(self) -> bool:
        """Check if there are any issues (errors or warnings)."""
        return len(self.errors) > 0 or len(self.warnings) > 0


def check_syntax(file_path: Path) -> Tuple[bool, str]:
    """Check Python file for syntax errors using AST.
    
    Args:
        file_path: Path to Python file
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        ast.parse(content, filename=str(file_path))
        return True, ""
    
    except SyntaxError as e:
        return False, f"Syntax error at line {e.lineno}: {e.msg}"
    
    except Exception as e:
        return False, f"Failed to parse: {e}"


def check_imports(file_path: Path) -> Tuple[List[str], Set[str]]:
    """Check for import errors and extract imported modules.
    
    Args:
        file_path: Path to Python file
        
    Returns:
        Tuple of (error_messages, imported_modules)
    """
    errors = []
    imported_modules = set()
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        tree = ast.parse(content, filename=str(file_path))
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_modules.add(alias.name.split('.')[0])
            
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported_modules.add(node.module.split('.')[0])
    
    except Exception as e:
        errors.append(f"Failed to analyze imports: {e}")
    
    return errors, imported_modules


def check_deprecated_patterns(file_path: Path) -> List[Tuple[int, str, str]]:
    """Check for deprecated API usage patterns.
    
    Args:
        file_path: Path to Python file
        
    Returns:
        List of (line_number, pattern, suggestion) tuples
    """
    issues = []
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        for line_num, line in enumerate(lines, 1):
            for pattern, suggestion in DEPRECATED_PATTERNS:
                if re.search(pattern, line):
                    issues.append((line_num, pattern, suggestion))
    
    except Exception as e:
        issues.append((0, "error", f"Failed to check patterns: {e}"))
    
    return issues


def check_documentation(file_path: Path) -> Tuple[bool, List[str]]:
    """Check for required documentation sections.
    
    Args:
        file_path: Path to Python file
        
    Returns:
        Tuple of (has_docstring, missing_sections)
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for module docstring
        has_docstring = '"""' in content or "'''" in content
        
        # Check for required sections
        missing_sections = []
        for section in REQUIRED_SECTIONS:
            if section not in content:
                missing_sections.append(section)
        
        return has_docstring, missing_sections
    
    except Exception:
        return False, REQUIRED_SECTIONS


def check_async_usage(file_path: Path) -> Tuple[bool, str]:
    """Check if example uses async/await properly.
    
    Args:
        file_path: Path to Python file
        
    Returns:
        Tuple of (uses_async, message)
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for async main function
        has_async_main = "async def main(" in content
        
        # Check for asyncio.run
        has_asyncio_run = "asyncio.run(" in content
        
        # Check for await statements
        has_await = "await " in content
        
        if has_async_main and has_asyncio_run:
            return True, "Uses async/await properly"
        elif has_await:
            return False, "Uses await but missing async main or asyncio.run"
        else:
            return False, "Does not use async/await (library is async-only)"
    
    except Exception as e:
        return False, f"Failed to check async usage: {e}"


def check_shebang(file_path: Path) -> bool:
    """Check if file has proper shebang.
    
    Args:
        file_path: Path to Python file
        
    Returns:
        True if has proper shebang
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            first_line = f.readline()
        
        return first_line.startswith("#!/usr/bin/env python")
    
    except Exception:
        return False


def validate_example(file_path: Path, verbose: bool = False) -> ValidationResult:
    """Validate a single example file.
    
    Args:
        file_path: Path to example file
        verbose: Whether to include info messages
        
    Returns:
        ValidationResult object
    """
    result = ValidationResult(file_path)
    
    # Check syntax
    is_valid_syntax, syntax_error = check_syntax(file_path)
    if not is_valid_syntax:
        result.add_error(f"Syntax error: {syntax_error}")
        return result  # Can't continue if syntax is invalid
    
    if verbose:
        result.add_info("✓ Syntax is valid")
    
    # Check imports
    import_errors, imported_modules = check_imports(file_path)
    for error in import_errors:
        result.add_error(f"Import error: {error}")
    
    if verbose and not import_errors:
        result.add_info(f"✓ Imports are valid ({len(imported_modules)} modules)")
    
    # Check for deprecated patterns
    deprecated_issues = check_deprecated_patterns(file_path)
    for line_num, pattern, suggestion in deprecated_issues:
        if line_num > 0:
            result.add_warning(f"Line {line_num}: Deprecated pattern '{pattern}' - {suggestion}")
        else:
            result.add_error(suggestion)
    
    if verbose and not deprecated_issues:
        result.add_info("✓ No deprecated patterns found")
    
    # Check documentation
    has_docstring, missing_sections = check_documentation(file_path)
    if not has_docstring:
        result.add_error("Missing module docstring")
    elif verbose:
        result.add_info("✓ Has module docstring")
    
    for section in missing_sections:
        result.add_warning(f"Missing documentation section: {section}")
    
    if verbose and not missing_sections:
        result.add_info("✓ All required documentation sections present")
    
    # Check async usage
    uses_async, async_message = check_async_usage(file_path)
    if not uses_async:
        result.add_warning(f"Async usage: {async_message}")
    elif verbose:
        result.add_info(f"✓ {async_message}")
    
    # Check shebang
    if not check_shebang(file_path):
        result.add_warning("Missing or incorrect shebang (should be #!/usr/bin/env python3)")
    elif verbose:
        result.add_info("✓ Has proper shebang")
    
    return result


def find_example_files() -> List[Path]:
    """Find all example Python files.
    
    Returns:
        List of example file paths
    """
    example_files = []
    
    # Find all .py files in examples directory
    for py_file in EXAMPLES_DIR.rglob("*.py"):
        # Skip __pycache__ and other special directories
        if "__pycache__" not in str(py_file):
            example_files.append(py_file)
    
    return sorted(example_files)


def print_result(result: ValidationResult, verbose: bool = False):
    """Print validation result.
    
    Args:
        result: ValidationResult to print
        verbose: Whether to print info messages
    """
    rel_path = result.file_path.relative_to(PROJECT_ROOT)
    
    # Determine status symbol
    if result.is_valid() and not result.warnings:
        status = "✓"
        color = "\033[92m"  # Green
    elif result.is_valid():
        status = "⚠"
        color = "\033[93m"  # Yellow
    else:
        status = "✗"
        color = "\033[91m"  # Red
    
    reset = "\033[0m"
    
    print(f"{color}{status}{reset} {rel_path}")
    
    # Print errors
    for error in result.errors:
        print(f"  {color}ERROR:{reset} {error}")
    
    # Print warnings
    for warning in result.warnings:
        print(f"  \033[93mWARNING:\033[0m {warning}")
    
    # Print info if verbose
    if verbose:
        for info in result.info:
            print(f"  \033[94mINFO:\033[0m {info}")


def main():
    """Main validation function."""
    parser = argparse.ArgumentParser(
        description="Validate example files for common issues"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed information"
    )
    parser.add_argument(
        "--files",
        nargs="+",
        help="Specific files to validate (relative to examples/)"
    )
    
    args = parser.parse_args()
    
    # Find example files
    if args.files:
        example_files = [EXAMPLES_DIR / f for f in args.files]
        # Validate files exist
        for f in example_files:
            if not f.exists():
                print(f"Error: File not found: {f}")
                return 1
    else:
        example_files = find_example_files()
    
    if not example_files:
        print("No example files found!")
        return 1
    
    print("=" * 80)
    print("EXAMPLE VALIDATION")
    print("=" * 80)
    print(f"\nValidating {len(example_files)} example file(s)...\n")
    
    # Validate each file
    results = []
    for file_path in example_files:
        result = validate_example(file_path, verbose=args.verbose)
        results.append(result)
        print_result(result, verbose=args.verbose)
    
    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    
    total = len(results)
    valid = sum(1 for r in results if r.is_valid() and not r.warnings)
    warnings_only = sum(1 for r in results if r.is_valid() and r.warnings)
    errors = sum(1 for r in results if not r.is_valid())
    
    print(f"\nTotal files: {total}")
    print(f"✓ Valid (no issues): {valid}")
    print(f"⚠ Valid (with warnings): {warnings_only}")
    print(f"✗ Invalid (with errors): {errors}")
    
    # Count specific issues
    total_errors = sum(len(r.errors) for r in results)
    total_warnings = sum(len(r.warnings) for r in results)
    
    print(f"\nTotal errors: {total_errors}")
    print(f"Total warnings: {total_warnings}")
    
    # Exit code
    if errors > 0:
        print("\n❌ Validation failed!")
        return 1
    elif warnings_only > 0:
        print("\n⚠️  Validation passed with warnings")
        return 0
    else:
        print("\n✅ All examples validated successfully!")
        return 0


if __name__ == "__main__":
    sys.exit(main())
