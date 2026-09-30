"""Ranking metrics, budgeted rendering and paired statistics for evals/."""

from __future__ import annotations

import math

import pytest

from evals.metrics import (
    Hit,
    acc_at,
    dedupe,
    mrr_at,
    ndcg_at,
    paired,
    recall_at,
    render,
)


def words(text: str) -> int:
    return len(text.split())


class TestRanking:
    def test_ndcg_perfect_and_partial(self) -> None:
        assert ndcg_at(["a", "b", "c"], {"a"}, 10) == 1.0
        # single relevant at rank 2: 1/log2(3) over ideal 1
        assert ndcg_at(["x", "a"], {"a"}, 10) == pytest.approx(1 / math.log2(3))
        assert ndcg_at(["x", "y"], {"a"}, 10) == 0.0
        assert ndcg_at([], set(), 10) == 0.0

    def test_ndcg_graded(self) -> None:
        # Linear gain, as trec_eval's ndcg_cut (the BEIR reference) computes it.
        gains = {"a": 2, "b": 1}
        ideal = 2 + 1 / math.log2(3)
        got = ndcg_at(["b", "a"], gains, 10)
        assert got == pytest.approx((1 + 2 / math.log2(3)) / ideal)

    def test_mrr_recall_acc(self) -> None:
        ranked = ["x", "a", "y", "b"]
        assert mrr_at(ranked, {"a", "b"}, 10) == 0.5
        assert mrr_at(ranked, {"a"}, 1) == 0.0
        assert recall_at(ranked, {"a", "b", "c"}, 2) == pytest.approx(1 / 3)
        assert recall_at(ranked, set(), 2) == 0.0
        assert acc_at(ranked, {"a", "b"}, 4) == 1.0
        assert acc_at(ranked, {"a", "b"}, 3) == 0.0

    def test_dedupe_keeps_first_order(self) -> None:
        assert dedupe(["b", "a", "b", "", "c", "a"]) == ["b", "a", "c"]


class TestRender:
    def test_budget_cuts_line_by_line_and_maps_source_lines(self) -> None:
        hits = [
            Hit(
                path="f.py",
                start=10,
                end=12,
                text="== f.py:10-12 ==\none two\nthree\nfour",
                body_offset=1,
            ),
            Hit(
                path="g.py", start=1, end=1, text="== g.py:1-1 ==\nfive", body_offset=1
            ),
        ]
        # header(3 words) + "one two"(2) + "three"(1) = 6; "four" would make 7.
        out = render(hits, budget=6, count=words)
        assert out.tokens == 6
        assert out.lines == {"f.py": {10, 11}}
        assert out.paths == ["f.py"]

    def test_whole_budget_covers_everything_and_orders_paths(self) -> None:
        hits = [
            Hit(
                path="f.py",
                start=10,
                end=12,
                text="== f.py:10-12 ==\na\nb\nc",
                body_offset=1,
            ),
            Hit(path="g.py", start=1, end=1, text="== g.py:1-1 ==\nd", body_offset=1),
            Hit(
                path="f.py", start=30, end=30, text="== f.py:30-30 ==\ne", body_offset=1
            ),
        ]
        out = render(hits, budget=10_000, count=words)
        assert out.lines == {"f.py": {10, 11, 12, 30}, "g.py": {1}}
        assert out.paths == ["f.py", "g.py"]

    def test_pointer_hit_points_without_rendering_evidence(self) -> None:
        hits = [
            Hit(
                path="s.py",
                start=395,
                end=395,
                text="NODE Session [src=s.py loc=L395]",
                pointer=True,
            ),
            Hit(path="", start=0, end=0, text="EDGE a --calls--> b"),
        ]
        out = render(hits, budget=100, count=words)
        assert out.lines == {}
        assert out.pointed == {"s.py": [(395, 395)]}
        assert out.paths == ["s.py"]
        assert out.touches("s.py", 390, 400)
        assert not out.touches("s.py", 396, 400)

    def test_touches_counts_rendered_lines(self) -> None:
        hits = [
            Hit(
                path="f.py",
                start=10,
                end=11,
                text="== f.py:10-11 ==\na\nb",
                body_offset=1,
            )
        ]
        out = render(hits, budget=100, count=words)
        assert out.touches("f.py", 11, 20)
        assert not out.touches("f.py", 12, 20)

    def test_unit_markers_extracted_from_rendered_lines_only(self) -> None:
        hits = [
            Hit(
                path="s1",
                start=0,
                end=0,
                text="[D1:1] hi there\n[D1:2] bye now",
                body_offset=0,
            )
        ]
        out = render(hits, budget=3, count=words, unit_pattern=r"\[(D\d+:\d+)\]")
        assert out.units == ["D1:1"]

    def test_whole_unit_hit_without_lines_counts_path(self) -> None:
        hits = [Hit(path="doc-7", start=0, end=0, text="abstract text", body_offset=0)]
        out = render(hits, budget=100, count=words)
        assert out.paths == ["doc-7"]
        assert out.lines == {}


class TestPaired:
    def test_identical_arms_have_zero_difference(self) -> None:
        r = paired([0.5, 0.2, 0.9], [0.5, 0.2, 0.9], seed=1)
        assert r["mean_diff"] == 0.0
        assert r["ci_low"] == 0.0 and r["ci_high"] == 0.0
        assert r["p_perm"] == 1.0

    def test_clear_improvement_excludes_zero_and_is_deterministic(self) -> None:
        a = [0.9, 0.8, 0.95, 0.7, 0.85, 0.9, 0.8, 0.75, 0.9, 0.88] * 3
        b = [0.2, 0.3, 0.25, 0.1, 0.3, 0.2, 0.35, 0.3, 0.2, 0.25] * 3
        r1 = paired(a, b, seed=7)
        r2 = paired(a, b, seed=7)
        assert r1 == r2
        assert r1["n"] == 30
        assert r1["ci_low"] > 0
        assert r1["p_perm"] < 0.01
        diffs = [x - y for x, y in zip(a, b)]
        mean = sum(diffs) / len(diffs)
        sd = math.sqrt(sum((d - mean) ** 2 for d in diffs) / (len(diffs) - 1))
        assert r1["mde"] == pytest.approx(2.8016 * sd / math.sqrt(30), rel=1e-3)

    def test_cluster_bootstrap_is_wider_when_clusters_disagree(self) -> None:
        # Two clusters: one large gain, one small loss. Per-case CI excludes 0;
        # resampling whole clusters must not.
        a = [1.0] * 20 + [0.0] * 20
        b = [0.0] * 20 + [0.1] * 20
        clusters = ["repo-a"] * 20 + ["repo-b"] * 20
        per_case = paired(a, b, seed=3)
        clustered = paired(a, b, seed=3, clusters=clusters)
        assert per_case["ci_low"] > 0
        assert clustered["ci_low"] < 0 < clustered["ci_high"]
        assert clustered["mean_diff"] == per_case["mean_diff"]

    def test_length_mismatch_is_an_error(self) -> None:
        with pytest.raises(ValueError):
            paired([1.0], [1.0, 0.0], seed=1)


def test_mcnemar_exact_matches_binomial_tail() -> None:
    from evals.metrics import mcnemar

    # 6 discordant pairs, all favouring a: p = 2 * (1/2)**6
    a = [True] * 6 + [True, False] * 3
    b = [False] * 6 + [True, False] * 3
    result = mcnemar(a, b)
    assert (result["a_only"], result["b_only"]) == (6, 0)
    assert result["p"] == round(2 / 64, 6)
    assert mcnemar([True, False], [True, False])["p"] == 1.0


def test_holm_is_step_down_and_monotone() -> None:
    from evals.metrics import holm

    assert holm({"x": 0.01, "y": 0.04, "z": 0.03}) == {"x": 0.03, "z": 0.06, "y": 0.06}


def test_ratio_interval_is_seeded() -> None:
    from evals.metrics import ratio_interval

    first = ratio_interval([1.0, 2.0, 3.0], [2.0, 4.0, 6.0], seed=1)
    assert first["ratio"] == 0.5 and first == ratio_interval(
        [1.0, 2.0, 3.0], [2.0, 4.0, 6.0], seed=1
    )


def test_mcnemar_two_sided_with_discordance_both_ways() -> None:
    from evals.metrics import mcnemar

    a = [True] * 7 + [False] * 2 + [True] * 5
    b = [False] * 7 + [True] * 2 + [True] * 5
    result = mcnemar(a, b)
    assert (result["a_only"], result["b_only"]) == (7, 2)
    assert result["p"] == round(
        2 * sum(__import__("math").comb(9, k) for k in range(3)) / 2**9, 6
    )
    assert abs(result["p"] - 0.1797) < 1e-4
