"""Importing the package must be free of side effects (spec AC3).

The AFP lifecycle contract runs ``ai`` as a short-lived process on every
native event, so the package import graph is part of the hook's latency and
its filesystem footprint. These tests run in a subprocess with a scratch
``HOME`` and ``INQUIRY_HOME`` so the assertions see a fresh interpreter.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HEAVY = ["lancedb", "pyarrow", "pandas", "torch", "sentence_transformers", "fastmcp", "fastapi", "fsspec"]


def _run(code: str, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    cwd = tmp_path / "cwd"
    cwd.mkdir(exist_ok=True)
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    inherited = {k: v for k, v in os.environ.items() if not k.startswith("INQUIRY_")}
    env = {
        **inherited,
        "HOME": str(home),
        "INQUIRY_HOME": str(home / ".agentic-inquiry"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_package_import_loads_no_heavy_modules(tmp_path: Path) -> None:
    code = (
        "import json, sys\n"
        "import agentic_inquiry\n"
        f"heavy = set({HEAVY!r}) & {{m.split('.')[0] for m in sys.modules}}\n"
        "print(json.dumps(sorted(heavy)))\n"
    )
    completed = _run(code, tmp_path)
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == []


def test_package_import_creates_no_files(tmp_path: Path) -> None:
    completed = _run("import agentic_inquiry\n", tmp_path)
    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    assert list((tmp_path / "cwd").iterdir()) == []
    assert list((tmp_path / "home").iterdir()) == []


def test_lazy_subpackage_attributes_still_resolve(tmp_path: Path) -> None:
    code = (
        "import agentic_inquiry\n"
        "assert agentic_inquiry.search.__name__ == 'agentic_inquiry.search'\n"
        "assert agentic_inquiry.storage.__name__ == 'agentic_inquiry.storage'\n"
        "assert agentic_inquiry.memory.__name__ == 'agentic_inquiry.memory'\n"
        "assert sorted(agentic_inquiry.__all__) == sorted(['database', 'embeddings', "
        "'exceptions', 'indexing', 'models', 'parsers', 'search'])\n"
        "try:\n"
        "    agentic_inquiry.nope\n"
        "except AttributeError:\n"
        "    print('ok')\n"
    )
    completed = _run(code, tmp_path)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "ok"


def test_package_import_is_fast(tmp_path: Path) -> None:
    code = (
        "import time\n"
        "started = time.perf_counter()\n"
        "import agentic_inquiry\n"
        "print(time.perf_counter() - started)\n"
    )
    _run(code, tmp_path)  # warm the cache
    completed = _run(code, tmp_path)
    assert completed.returncode == 0, completed.stderr
    elapsed = float(completed.stdout.strip())
    assert elapsed < 0.1, elapsed
