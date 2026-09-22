import { ComplexAnalyzer, buildDefaultAnalyzer, describeMetrics } from "./complex.js";

export function simpleFlow() {
    const analyzer = buildDefaultAnalyzer();
    const metrics = describeMetrics([1, 2, 3]);
    metrics.baseline = analyzer.distance(10, 3);
    return metrics;
}

export function summarize() {
    const result = simpleFlow();
    return `baseline=${result.baseline}, rms=${result.rms.toFixed(2)}`;
}
