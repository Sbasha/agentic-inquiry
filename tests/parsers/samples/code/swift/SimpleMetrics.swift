struct Metrics {
    let baseline: Double
    let rms: Double
}

struct SimpleMetrics {
    static func runSimple() -> Metrics {
        let analyzer = ComplexMetrics.buildDefault()
        let baseline = analyzer.distance(10, 3)
        let rms = analyzer.rootMeanSquare([1, 2, 3])
        return Metrics(baseline: baseline, rms: rms)
    }

    static func summarize() -> String {
        let metrics = runSimple()
        return String(format: "baseline=%.2f, rms=%.2f", metrics.baseline, metrics.rms)
    }
}
