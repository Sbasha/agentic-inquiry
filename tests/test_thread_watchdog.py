"""The thread watchdog plugin reports a leaked thread instead of hanging."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests.helpers import thread_watchdog

ROOT_DIR = Path(__file__).resolve().parents[1]

_LEAK = (
    "import threading\n"
    "threading.Thread(target=threading.Event().wait, name='leaky-probe').start()\n"
)


def _run_pytest(
    tmp_path: Path, files: dict[str, str]
) -> tuple[subprocess.CompletedProcess[str], float]:
    for name, body in files.items():
        (tmp_path / name).write_text(body, encoding="utf-8")
    # A developer's PYTEST_ADDOPTS must not change the child run.
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTEST_")}
    env["PYTHONPATH"] = str(ROOT_DIR)
    started = time.monotonic()
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "tests.helpers.thread_watchdog",
            "-p",
            "no:cacheprovider",
            f"--rootdir={tmp_path}",
            ".",
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=env,
        timeout=thread_watchdog.GRACE_SECONDS + 60,
    )
    return completed, time.monotonic() - started


def _assert_reports_leak(completed: subprocess.CompletedProcess[str]) -> None:
    report = completed.stderr.split("--- leaky-probe (threading.Thread)", 1)
    assert len(report) == 2, completed.stderr
    assert 'File "' in report[1]


@pytest.mark.slow
def test_leaked_thread_after_passing_run_is_reported_and_fails(tmp_path: Path) -> None:
    completed, _ = _run_pytest(
        tmp_path, {"test_leak.py": "def test_leaks():\n" + _indent(_LEAK)}
    )

    assert "1 passed" in completed.stdout
    _assert_reports_leak(completed)
    assert completed.returncode == 1


@pytest.mark.slow
def test_leaked_thread_keeps_pytest_status(tmp_path: Path) -> None:
    # A conftest-level leak with nothing collected: pytest's status is 5.
    completed, _ = _run_pytest(tmp_path, {"conftest.py": _LEAK})

    assert "no tests ran" in completed.stdout
    _assert_reports_leak(completed)
    assert completed.returncode == pytest.ExitCode.NO_TESTS_COLLECTED


def test_thread_ending_within_grace_is_not_reported(tmp_path: Path) -> None:
    completed, elapsed = _run_pytest(
        tmp_path,
        {
            "test_slow.py": (
                "import threading, time\n"
                "def test_starts_slow_thread():\n"
                "    threading.Thread(target=time.sleep, args=(2,)).start()\n"
            )
        },
    )

    assert "1 passed" in completed.stdout
    assert "non-daemon" not in completed.stderr
    assert completed.returncode == 0
    assert elapsed < thread_watchdog.GRACE_SECONDS


def test_clean_run_finalizes_normally(tmp_path: Path) -> None:
    marker = tmp_path / "atexit-ran"
    completed, elapsed = _run_pytest(
        tmp_path,
        {
            "test_clean.py": (
                "import atexit, pathlib\n"
                "def test_registers_atexit():\n"
                f"    atexit.register(pathlib.Path({str(marker)!r}).touch)\n"
            )
        },
    )

    assert "1 passed" in completed.stdout
    assert "non-daemon" not in completed.stderr
    assert completed.returncode == 0
    assert marker.exists()
    assert elapsed < thread_watchdog.GRACE_SECONDS


def _indent(code: str) -> str:
    return "".join(f"    {line}\n" for line in code.splitlines())
