"""Arm helpers that need no models or network: parsing, fusion, units."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from evals.arms import build_units, parse_graphify, rrf
from evals.competitor_worker import sessions, turns
from evals.run import applicable_arms

GRAPHIFY_OUTPUT = """Graph: graph.json (10 nodes) | Traversal: BFS depth=2 | Start: ['Session']

NODE Session [src=src/requests/sessions.py loc=L395 community=]
NODE HeadersType [src= loc= community=]
NODE .resolve_redirects() [src=src/requests/sessions.py loc=L186 community=]
EDGE Session --contains--> .resolve_redirects() [EXTRACTED 1.0]
"""


def test_parse_graphify_keeps_order_and_points_nodes() -> None:
    hits = parse_graphify(GRAPHIFY_OUTPUT)
    nodes = [h for h in hits if h.pointer]
    assert [(h.path, h.start) for h in nodes] == [
        ("src/requests/sessions.py", 395),
        ("src/requests/sessions.py", 186),
    ]
    # Header, blank, sourceless node and edge lines still cost budget, in order.
    assert [h.text for h in hits][0].startswith("Graph:")
    assert len(hits) == 6


def test_rrf_rewards_agreement() -> None:
    assert rrf([[1, 2, 3], [3, 1, 4]])[:2] == [1, 3]
    assert rrf([[], [5]]) == [5]


def test_build_units_windows_and_skips(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("\n".join(f"line{i}" for i in range(1, 121)) + "\n")
    (tmp_path / "blank.txt").write_text("\n\n")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("x")
    (tmp_path / "bin.dat").write_bytes(b"\x00\x01")
    units = build_units(tmp_path, 50)
    assert [(u.path, u.start, u.end) for u in units] == [
        ("a.py", 1, 50),
        ("a.py", 51, 100),
        ("a.py", 101, 120),
    ]
    whole = build_units(tmp_path, 0)
    assert [(u.path, u.start, u.end) for u in whole] == [("a.py", 1, 120)]


def test_competitors_are_refused_outside_level_b() -> None:
    # The refusal happens before the suite is read.
    with pytest.raises(SystemExit, match="mem0: Level B only"):
        applicable_arms(cast(Any, None), ["inquiry", "mem0"])


def test_worker_orders_sessions_and_keeps_dates(tmp_path: Path) -> None:
    (tmp_path / "session_10.txt").write_text(
        "[D10:1] (1 pm on 9 May, 2023) Ann: late\n"
    )
    (tmp_path / "session_2.txt").write_text("[D2:1] (1 pm on 8 May, 2023) Ann: early\n")
    assert [p.name for p in sessions(tmp_path)] == ["session_2.txt", "session_10.txt"]
    lme = tmp_path / "lme"
    lme.mkdir()
    (lme / "b.txt").write_text(
        "[b#t0] (2023/05/24 (Wed) 06:42) user: hi\n[b#t1] (2023/05/24 (Wed) 06:42) assistant: yo\n"
    )
    (lme / "a.txt").write_text("[a#t0] (2023/06/01 (Thu) 10:00) user: later\n")
    assert [p.name for p in sessions(lme)] == ["b.txt", "a.txt"]
    assert turns(lme / "b.txt") == [
        {"role": "user", "content": "(2023/05/24 (Wed) 06:42) user: hi"},
        {"role": "assistant", "content": "(2023/05/24 (Wed) 06:42) assistant: yo"},
    ]
