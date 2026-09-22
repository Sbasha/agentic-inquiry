export class ComplexAnalyzer {
    constructor(scale = 1.0) {
        this.scale = scale;
    }

    distance(a, b) {
        return Math.abs(a - b) * this.scale;
    }

    rootMeanSquare(values) {
        if (!values.length) {
            return 0;
        }
        const total = values.reduce((acc, value) => acc + value * value, 0);
        return Math.sqrt(total / values.length);
    }
}

export const buildDefaultAnalyzer = () => new ComplexAnalyzer(0.8);

export function describeMetrics(values) {
    const analyzer = buildDefaultAnalyzer();
    return {
        distance: analyzer.distance(values[0], values[values.length - 1]),
        rms: analyzer.rootMeanSquare(values),
    };
}
