"""Simple workflow that imports symbols from complex.py."""

from complex import build_default_analyzer, describe_metrics


def simple_flow() -> dict[str, float]:
    analyzer = build_default_analyzer()
    baseline = analyzer.distance(10, 3)
    metrics = describe_metrics([1.0, 2.0, 3.0])
    metrics["baseline"] = baseline
    return metrics


def summarize() -> str:
    result = simple_flow()
    return f"Summary: baseline={result['baseline']}, rms={result['rms']:.2f}"
