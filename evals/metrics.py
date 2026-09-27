"""Ranking metrics, token-budgeted rendering and paired statistics.

Every arm's output is scored through `render`: hits are emitted in rank order
until the token budget is spent, line by line, so an arm that returns large
chunks and an arm that returns one-line graph nodes pay for exactly what an
agent would read.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np

# z(0.975) + z(0.80): two-sided alpha 0.05 at 80% power.
_MDE_Z = 2.8016


@dataclass(frozen=True)
class Hit:
    """One retrieved item as the agent would read it.

    ``text`` is the full display text. Display line ``body_offset + i`` shows
    source line ``start + i``; ``start == 0`` means the hit has no line
    mapping (a whole document, or an EDGE line with no ``path``). A
    ``pointer`` hit names ``path:start-end`` without showing that code, like a
    graph NODE line: it points the agent somewhere but renders no evidence.
    """

    path: str
    start: int
    end: int
    text: str
    body_offset: int = 0
    pointer: bool = False


@dataclass
class Rendered:
    tokens: int = 0
    paths: list[str] = field(default_factory=list)
    lines: dict[str, set[int]] = field(default_factory=dict)
    pointed: dict[str, list[tuple[int, int]]] = field(default_factory=dict)
    units: list[str] = field(default_factory=list)
    text_lines: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        """Exactly what the agent would read within the budget."""
        return "\n".join(self.text_lines)

    def touches(self, path: str, start: int, end: int) -> bool:
        """True when a rendered line or a pointer falls inside ``path:start-end``."""
        if any(start <= line <= end for line in self.lines.get(path, ())):
            return True
        return any(lo <= end and start <= hi for lo, hi in self.pointed.get(path, ()))


@lru_cache(maxsize=1)
def _encoding():  # type: ignore[no-untyped-def]
    import tiktoken

    return tiktoken.get_encoding("cl100k_base")


@lru_cache(maxsize=500_000)
def count_tokens(text: str) -> int:
    """Tokens under the pinned tokenizer (tiktoken ``cl100k_base``)."""
    return len(_encoding().encode(text, disallowed_special=()))


def render(
    hits: Iterable[Hit],
    budget: int,
    count: Callable[[str], int] = count_tokens,
    unit_pattern: str | None = None,
) -> Rendered:
    """Emit hits in order until ``budget`` tokens; return what was covered."""
    out = Rendered()
    marker = re.compile(unit_pattern) if unit_pattern else None
    seen_units: set[str] = set()
    for hit in hits:
        for index, line in enumerate(hit.text.split("\n")):
            cost = count(line) if line else 0
            if out.tokens + cost > budget:
                return out
            out.tokens += cost
            out.text_lines.append(line)
            if hit.path and hit.path not in out.paths:
                out.paths.append(hit.path)
            if hit.pointer:
                if hit.path and hit.start > 0 and index == 0:
                    out.pointed.setdefault(hit.path, []).append(
                        (hit.start, max(hit.end, hit.start))
                    )
            else:
                source = hit.start + index - hit.body_offset
                if (
                    hit.path
                    and hit.start > 0
                    and hit.start <= source <= max(hit.end, hit.start)
                ):
                    out.lines.setdefault(hit.path, set()).add(source)
            if marker:
                for unit in marker.findall(line):
                    if unit not in seen_units:
                        seen_units.add(unit)
                        out.units.append(unit)
    return out


def dedupe(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def _gains(
    relevant: Mapping[str, float] | set[str] | frozenset[str],
) -> dict[str, float]:
    if isinstance(relevant, Mapping):
        return {k: float(v) for k, v in relevant.items() if v > 0}
    return {k: 1.0 for k in relevant}


def ndcg_at(
    ranked: Sequence[str],
    relevant: Mapping[str, float] | set[str] | frozenset[str],
    k: int,
) -> float:
    """nDCG@k with linear gain, matching trec_eval's ``ndcg_cut``."""
    gains = _gains(relevant)
    if not gains:
        return 0.0
    dcg = sum(
        gains.get(item, 0.0) / math.log2(rank + 2)
        for rank, item in enumerate(ranked[:k])
    )
    ideal = sorted(gains.values(), reverse=True)[:k]
    idcg = sum(g / math.log2(rank + 2) for rank, g in enumerate(ideal))
    return dcg / idcg


def mrr_at(ranked: Sequence[str], relevant: set[str] | frozenset[str], k: int) -> float:
    for rank, item in enumerate(ranked[:k]):
        if item in relevant:
            return 1.0 / (rank + 1)
    return 0.0


def recall_at(
    ranked: Sequence[str], relevant: set[str] | frozenset[str], k: int
) -> float:
    if not relevant:
        return 0.0
    return len(set(ranked[:k]) & set(relevant)) / len(relevant)


def acc_at(ranked: Sequence[str], relevant: set[str] | frozenset[str], k: int) -> float:
    """1.0 when every relevant item is in the top k (localization accuracy)."""
    return 1.0 if relevant and set(relevant) <= set(ranked[:k]) else 0.0


def paired(
    a: Sequence[float],
    b: Sequence[float],
    seed: int,
    resamples: int = 10_000,
    clusters: Sequence[str] | None = None,
) -> dict[str, float]:
    """Paired comparison of per-case scores ``a`` versus ``b``.

    Returns the mean difference, a percentile bootstrap 95% CI, a two-sided
    sign-flip permutation p-value and the minimum detectable effect at 80%
    power given the observed spread of differences. With ``clusters`` the
    bootstrap resamples whole clusters (repositories, conversations), because
    cases that share a corpus are not independent.
    """
    if len(a) != len(b) or (clusters is not None and len(clusters) != len(a)):
        raise ValueError(f"paired samples differ in length: {len(a)} != {len(b)}")
    diffs = np.asarray(a, dtype=float) - np.asarray(b, dtype=float)
    n = len(diffs)
    if n == 0:
        return {
            "n": 0,
            "mean_diff": 0.0,
            "ci_low": 0.0,
            "ci_high": 0.0,
            "p_perm": 1.0,
            "mde": 0.0,
        }
    rng = np.random.default_rng(seed)
    mean = float(diffs.mean())
    if clusters is None:
        boot = diffs[rng.integers(0, n, size=(resamples, n))].mean(axis=1)
    else:
        names = sorted(set(clusters))
        index = {name: i for i, name in enumerate(names)}
        members = np.array([index[c] for c in clusters])
        sums = np.bincount(members, weights=diffs, minlength=len(names))
        counts = np.bincount(members, minlength=len(names)).astype(float)
        draws = rng.integers(0, len(names), size=(resamples, len(names)))
        boot = sums[draws].sum(axis=1) / counts[draws].sum(axis=1)
    signs = rng.choice(np.array([-1.0, 1.0]), size=(resamples, n))
    null = np.abs((signs * diffs).mean(axis=1))
    extreme = int(np.sum(null >= abs(mean) - 1e-12))
    sd = float(diffs.std(ddof=1)) if n > 1 else 0.0
    return {
        "n": n,
        "mean_diff": round(mean, 6),
        "ci_low": round(float(np.percentile(boot, 2.5)), 6),
        "ci_high": round(float(np.percentile(boot, 97.5)), 6),
        "p_perm": round((extreme + 1) / (resamples + 1), 6) if mean != 0.0 else 1.0,
        "mde": round(_MDE_Z * sd / math.sqrt(n), 6),
    }
