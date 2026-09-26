"""Gold-label derivation and split assignment for evals/."""
from __future__ import annotations

import textwrap

from evals.data import enclosing_defs, evidence_ids, parse_patch, split_of, stratified_sample

PATCH = textwrap.dedent(
    """\
    diff --git a/pkg/mod.py b/pkg/mod.py
    --- a/pkg/mod.py
    +++ b/pkg/mod.py
    @@ -10,4 +10,5 @@ def f():
         a = 1
    -    b = 2
    +    b = 3
    +    c = 4
         return a
    @@ -40,2 +41,3 @@ class K:
         x = 1
    +    y = 2
         z = 3
    diff --git a/pkg/new.py b/pkg/new.py
    new file mode 100644
    --- /dev/null
    +++ b/pkg/new.py
    @@ -0,0 +1,2 @@
    +def g():
    +    pass
    diff --git a/pkg/gone.py b/pkg/gone.py
    deleted file mode 100644
    --- a/pkg/gone.py
    +++ /dev/null
    @@ -1,2 +0,0 @@
    -def h():
    -    pass
    """
)


def test_parse_patch_pre_image_lines() -> None:
    gold = parse_patch(PATCH)
    # Line 11 deleted; pure insertion after line 40 anchors on line 40.
    assert gold["pkg/mod.py"] == {11, 40}
    # New files have no pre-image and cannot be retrieved.
    assert "pkg/new.py" not in gold
    # Deleted files keep every deleted line.
    assert gold["pkg/gone.py"] == {1, 2}


def test_insertion_at_top_of_file_anchors_on_line_one() -> None:
    patch = "--- a/x.py\n+++ b/x.py\n@@ -0,0 +1 @@\n+import os\n"
    assert parse_patch(patch) == {"x.py": {1}}


SOURCE = textwrap.dedent(
    """\
    import os

    class K:
        def m(self):
            return 1

        @staticmethod
        def n():
            return 2

    def top():
        pass
    """
)


def test_enclosing_defs_innermost_with_decorators() -> None:
    spans = enclosing_defs(SOURCE, {5, 9, 12, 1})
    # line 5 -> K.m (4-5); line 9 -> K.n incl. decorator (7-9); line 12 -> top (11-12); line 1 -> none
    assert spans == {(4, 5), (7, 9), (11, 12)}


def test_enclosing_defs_tolerates_syntax_errors() -> None:
    assert enclosing_defs("def broken(:\n  pass\n", {1}) == set()


def test_split_is_stable_and_roughly_one_third_dev() -> None:
    ids = [f"case-{i}" for i in range(3000)]
    splits = [split_of(i) for i in ids]
    assert splits == [split_of(i) for i in ids]
    dev = splits.count("dev") / len(ids)
    assert 0.30 < dev < 0.37


def test_evidence_ids_normalizes_malformed_entries() -> None:
    assert evidence_ids(["D1:3", "D8:6; D9:17", "D:1", "d2:4"]) == ["D1:3", "D8:6", "D9:17", "D2:4"]


def test_stratified_sample_respects_caps_and_is_seeded() -> None:
    rows = [{"repo": "a", "id": f"a{i}"} for i in range(10)] + [{"repo": "b", "id": f"b{i}"} for i in range(3)]
    pick = stratified_sample(rows, key="repo", id_field="id", caps={"a": 4, "b": 5}, seed=1)
    assert sum(r["repo"] == "a" for r in pick) == 4
    assert sum(r["repo"] == "b" for r in pick) == 3
    assert pick == stratified_sample(rows, key="repo", id_field="id", caps={"a": 4, "b": 5}, seed=1)


def test_insertion_pairs_name_both_neighbours() -> None:
    from evals.data import insertion_pairs

    pairs = insertion_pairs(PATCH)
    # "+ b = 3 / + c = 4" follow a deletion of old line 11: neighbours 11 and 12.
    # "+ y = 2" sits between old lines 40 and 41.
    assert pairs["pkg/mod.py"] == [(11, 12), (40, 41)]
    assert "pkg/new.py" not in pairs


def test_method_inserted_between_methods_is_credited_to_the_class() -> None:
    # Insertion between K.m (4-5) and K.n (7-9): neighbours 5 and 7.
    assert enclosing_defs(SOURCE, set(), [(5, 7)]) == {(3, 9)}


def test_locomo_cases_split_by_conversation() -> None:
    from evals.data import Case

    a = Case(id="conv-1-q1", suite="locomo", corpus="conv-1", query="", gold_units={}, split_unit="conv-1")
    b = Case(id="conv-1-q2", suite="locomo", corpus="conv-1", query="", gold_units={}, split_unit="conv-1")
    assert a.split == b.split == split_of("conv-1")
