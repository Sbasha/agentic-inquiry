export interface Metrics {
    distance: number;
    rms: number;
}

export class ComplexAnalyzer {
    constructor(private readonly scale = 1.0) {}

    distance(a: number, b: number): number {
        return Math.abs(a - b) * this.scale;
    }

    rootMeanSquare(values: number[]): number {
        if (values.length === 0) {
            return 0;
        }
        const total = values.reduce((acc, value) => acc + value * value, 0);
        return Math.sqrt(total / values.length);
    }
}

export const buildDefaultAnalyzer = (): ComplexAnalyzer => new ComplexAnalyzer(0.82);

export function describeMetrics(values: number[]): Metrics {
    const analyzer = buildDefaultAnalyzer();
    return {
        distance: analyzer.distance(values[0], values[values.length - 1]),
        rms: analyzer.rootMeanSquare(values),
    };
}
