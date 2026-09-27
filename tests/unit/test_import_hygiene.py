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

import pytest

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


def test_watching_import_creates_no_files(tmp_path: Path) -> None:
    completed = _run(
        "import agentic_inquiry.watching.file_tracker\nimport agentic_inquiry.watching\n",
        tmp_path,
    )
    assert completed.returncode == 0, completed.stderr
    assert list((tmp_path / "cwd").iterdir()) == []
    assert list((tmp_path / "home").iterdir()) == []


def test_watching_built_in_default_is_a_file_watcher(tmp_path: Path) -> None:
    code = (
        "from agentic_inquiry.watching import FileWatcher, get_watcher\n"
        "assert isinstance(get_watcher(), FileWatcher)\n"
        "print('ok')\n"
    )
    completed = _run(code, tmp_path)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "ok"


@pytest.mark.parametrize(
    "first_call", ["get_watcher()", "get_watcher('default')", "available_watchers()"]
)
def test_watching_default_watcher_registers_on_first_lookup(
    tmp_path: Path, first_call: str
) -> None:
    code = (
        "import agentic_inquiry.watching as watching\n"
        "built = []\n"
        "def stub():\n"
        "    built.append(object())\n"
        "    return built[-1]\n"
        "watching.FileWatcher = stub\n"
        f"first = watching.{first_call}\n"
        "assert len(built) == 1, built\n"
        "assert first in (built[0], ['default']), first\n"
        "assert watching.get_watcher() is built[0]\n"
        "assert watching.get_watcher('default') is built[0]\n"
        "assert watching.available_watchers() == ['default']\n"
        "watching.unregister_watcher('default')\n"
        "assert watching.get_watcher() is built[1]\n"
        "print('ok')\n"
    )
    completed = _run(code, tmp_path)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "ok"


def test_watching_caller_watchers_skip_the_built_in_default(tmp_path: Path) -> None:
    code = (
        "import os\n"
        "from agentic_inquiry.watching import (\n"
        "    available_watchers, get_watcher, register_watcher, unregister_watcher,\n"
        ")\n"
        "first, chosen, theirs = object(), object(), object()\n"
        "register_watcher('first', first)\n"
        "assert get_watcher() is first\n"
        "register_watcher('chosen', chosen, set_default=True)\n"
        "assert get_watcher() is chosen\n"
        "assert get_watcher('first') is first\n"
        "import agentic_inquiry.watching as watching\n"
        "real_file_watcher, built_in = watching.FileWatcher, object()\n"
        "watching.FileWatcher = lambda: built_in\n"
        "assert available_watchers() == ['first', 'chosen', 'default']\n"
        "assert get_watcher('default') is built_in\n"
        "assert get_watcher() is chosen\n"
        "unregister_watcher('default')\n"
        "watching.FileWatcher = real_file_watcher\n"
        "unregister_watcher('first')\n"
        "unregister_watcher('chosen')\n"
        "register_watcher('default', theirs)\n"
        "assert get_watcher() is theirs\n"
        "assert get_watcher('default') is theirs\n"
        "unregister_watcher('default')\n"
        "register_watcher('other', first)\n"
        "register_watcher('default', theirs)\n"
        "unregister_watcher('other')\n"
        "assert get_watcher() is theirs\n"
        "assert os.listdir('.') == []\n"
        "print('ok')\n"
    )
    completed = _run(code, tmp_path)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "ok"
    assert list((tmp_path / "cwd").iterdir()) == []


def test_watching_default_watcher_errors_reach_the_caller(tmp_path: Path) -> None:
    code = (
        "import agentic_inquiry.watching as watching\n"
        "def broken():\n"
        "    raise ValueError('no project')\n"
        "watching.FileWatcher = broken\n"
        "try:\n"
        "    watching.get_watcher()\n"
        "except ValueError as exc:\n"
        "    print(exc)\n"
    )
    completed = _run(code, tmp_path)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "no project"


def test_watching_concurrent_first_lookups_build_one_default(tmp_path: Path) -> None:
    code = (
        "import threading, time\n"
        "from concurrent.futures import ThreadPoolExecutor\n"
        "import agentic_inquiry.watching as watching\n"
        "built = []\n"
        "barrier = threading.Barrier(8)\n"
        "def slow():\n"
        "    time.sleep(0.05)\n"
        "    built.append(object())\n"
        "    return built[-1]\n"
        "watching.FileWatcher = slow\n"
        "def lookup(_):\n"
        "    barrier.wait()\n"
        "    return watching.get_watcher()\n"
        "with ThreadPoolExecutor(8) as pool:\n"
        "    results = list(pool.map(lookup, range(8)))\n"
        "assert len(built) == 1, len(built)\n"
        "assert all(r is built[0] for r in results)\n"
        "print('ok')\n"
    )
    completed = _run(code, tmp_path)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "ok"
