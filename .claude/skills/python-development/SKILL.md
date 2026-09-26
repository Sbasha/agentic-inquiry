---
name: python-development
description: Apply repository-compatible Python engineering practices when implementing, reviewing, or testing Python code. Use for Python projects, packages, command-line tools, services, and standalone scripts where interpreter support, dependency management, typing, tests, and packaging choices must follow the project's declared versions and existing toolchain.
---

# Python

- Read `pyproject.toml`, lockfiles, CI, and contributor docs before choosing a Python version or tool. Preserve the project's supported interpreter range and package manager.
- Use type hints at maintained interfaces, dataclasses when they simplify value objects, `pathlib` for new path handling, and f-strings for interpolation.
- Run the repository's formatter, linter, type checker, and tests. Do not introduce a new tool merely because it is preferred elsewhere.
- For standalone scripts with a few real dependencies, consider PEP 723 inline metadata when the execution environment supports it.
