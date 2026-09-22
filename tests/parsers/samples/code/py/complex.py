"""Complex analytics utilities for symbol extraction tests."""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Iterable


@dataclass
class ComplexAnalyzer:
    """Provides multiple methods that the parser should discover."""

    scale: float = 1.0

    def distance(self, a: float, b: float) -> float:
        """Return a scaled distance between values."""
        return abs(a - b) * self.scale

    def root_mean_square(self, values: Iterable[float]) -> float:
        """Compute RMS to give the parser a nested symbol."""
        values = list(values)
        if not values:
            return 0.0
        total = sum(v * v for v in values)
        return sqrt(total / len(values))


def build_default_analyzer() -> ComplexAnalyzer:
    """Factory that is referenced from simple.py."""
    return ComplexAnalyzer(scale=0.75)


def describe_metrics(values: Iterable[float]) -> dict[str, float]:
    analyzer = build_default_analyzer()
    return {
        "distance": analyzer.distance(values[0], values[-1]),
        "rms": analyzer.root_mean_square(values),
    }
