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


def _run_pytest(tmp_path: Path, test_body: str) -> tuple[subprocess.CompletedProcess[str], float]:
    (tmp_path / "test_generated.py").write_text(test_body, encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(ROOT_DIR)}
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
            "test_generated.py",
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=env,
        timeout=thread_watchdog.GRACE_SECONDS + 60,
    )
    return completed, time.monotonic() - started


@pytest.mark.slow
def test_leaked_thread_is_reported_after_the_summary(tmp_path: Path) -> None:
    completed, _ = _run_pytest(
        tmp_path,
        "import threading\n"
        "def test_leaks():\n"
        "    threading.Thread(target=threading.Event().wait, name='leaky-probe').start()\n",
    )

    assert "1 passed" in completed.stdout
    report = completed.stderr.split("--- leaky-probe (threading.Thread)", 1)
    assert len(report) == 2, completed.stderr
    assert 'File "' in report[1]
    assert completed.returncode == 1


def test_clean_run_exits_without_waiting(tmp_path: Path) -> None:
    completed, elapsed = _run_pytest(tmp_path, "def test_nothing():\n    pass\n")

    assert "1 passed" in completed.stdout
    assert "non-daemon" not in completed.stderr
    assert completed.returncode == 0
    assert elapsed < thread_watchdog.GRACE_SECONDS
