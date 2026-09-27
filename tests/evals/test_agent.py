"""Level C citation parsing, scoring and tool-manifest checks."""

from __future__ import annotations

from evals.agent import manifest_ok, parse_citations, score
from evals.data import Case


def test_parse_citations_reads_after_locations_and_caps_files() -> None:
    text = (
        "I looked at a.py:1.\nLOCATIONS:\n./src/a.py:10\nsrc/b.py:20\nsrc/a.py:30\n"
        + "".join(f"src/f{i}.py:{i}\n" for i in range(10))
    )
    cited = parse_citations(text, limit=3)
    assert cited == [
        ("src/a.py", 10),
        ("src/b.py", 20),
        ("src/a.py", 30),
        ("src/f0.py", 0),
    ]


def test_score_counts_files_and_functions() -> None:
    case = Case(
        id="t",
        suite="swebench",
        corpus="c",
        query="",
        gold_units={"src/a.py": 1.0, "src/c.py": 1.0},
        gold_functions=[("src/a.py", 5, 15), ("src/c.py", 1, 3)],
    )
    metrics = score(case, [("src/a.py", 10), ("src/b.py", 2)])
    assert metrics == {"file_recall": 0.5, "file_precision": 0.5, "fn_hit": 0.5}


def test_manifest_requires_only_the_arm_server() -> None:
    ok = {
        "tools": ["Read", "mcp__inquiry__search"],
        "mcp_servers": [{"name": "inquiry", "status": "connected"}],
    }
    assert manifest_ok("inquiry", ok)
    assert not manifest_ok(
        "inquiry",
        {"tools": ["Read"], "mcp_servers": [{"name": "inquiry", "status": "failed"}]},
    )
    assert not manifest_ok("floor", ok)
    assert manifest_ok("floor", {"tools": ["Read", "Grep", "Glob"], "mcp_servers": []})
