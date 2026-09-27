"""Pytest plugin: name the non-daemon threads that stall interpreter exit.

Interpreter shutdown joins every non-daemon thread, so one leaked thread (an
unclosed aiosqlite connection, say) keeps the process alive after pytest has
written its summary and reports. When shutdown begins, this plugin starts a
daemon timer. If a non-daemon thread is still alive when the timer fires, it
writes each such thread's name, type and stack to stderr and exits with
pytest's status, or 1 when that status was 0. Close the reported resource in
the test or fixture that opened it.
"""

from __future__ import annotations

import os
import sys
import threading
import traceback

import pytest

GRACE_SECONDS = 10.0

_session: pytest.Session | None = None
_armed = False


def pytest_sessionstart(session: pytest.Session) -> None:
    global _session
    _session = session


def pytest_unconfigure(config: pytest.Config) -> None:
    global _armed
    if _armed:
        return
    _armed = True
    # threading runs these callbacks in reverse registration order when
    # shutdown begins, so this one runs before concurrent.futures joins its
    # idle workers and before the non-daemon threads are joined.
    threading._register_atexit(_start_timer)  # type: ignore[attr-defined]


def _start_timer() -> None:
    timer = threading.Timer(GRACE_SECONDS, _report_and_exit)
    timer.daemon = True
    timer.start()


def _report_and_exit() -> None:
    current = threading.current_thread()
    blocking = [
        thread
        for thread in threading.enumerate()
        if thread is not threading.main_thread()
        and thread is not current
        and not thread.daemon
        and thread.is_alive()
    ]
    if not blocking:
        return

    frames = sys._current_frames()
    lines = [
        f"\n{len(blocking)} non-daemon thread(s) still running "
        f"{GRACE_SECONDS:g}s into interpreter shutdown:",
    ]
    for thread in blocking:
        kind = f"{type(thread).__module__}.{type(thread).__qualname__}"
        lines.append(f"\n--- {thread.name} ({kind})")
        frame = frames.get(thread.ident) if thread.ident is not None else None
        if frame is not None:
            lines.append("".join(traceback.format_stack(frame)).rstrip())

    # pytest's summary may still sit in a pipe's buffer; os._exit drops it.
    sys.stdout.flush()
    print("\n".join(lines), file=sys.stderr, flush=True)
    status = int(_session.exitstatus) if _session is not None else 0
    os._exit(status or 1)
