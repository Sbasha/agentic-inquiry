import { ComplexAnalyzer, buildDefaultAnalyzer, describeMetrics, Metrics } from "./complex";

export function runSimple(): Metrics & { baseline: number } {
    const analyzer: ComplexAnalyzer = buildDefaultAnalyzer();
    const metrics = describeMetrics([1, 2, 3]);
    return {
        ...metrics,
        baseline: analyzer.distance(10, 3),
    };
}

export function summarize(): string {
    const metrics = runSimple();
    return `baseline=${metrics.baseline.toFixed(2)}, rms=${metrics.rms.toFixed(2)}`;
}
