"""Arm helpers that need no models or network: parsing, fusion, units."""

from __future__ import annotations

from pathlib import Path

from evals.arms import build_units, parse_graphify, rrf

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
