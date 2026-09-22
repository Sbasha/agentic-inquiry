class SimpleMetrics {
    static Map<String, Double> runSimple() {
        def analyzer = ComplexMetrics.buildDefault()
        [
            baseline: analyzer.distance(10, 3),
            rms     : analyzer.rootMeanSquare([1d, 2d, 3d])
        ]
    }

    static String summarize() {
        def metrics = runSimple()
        "baseline=${metrics.baseline}, rms=${metrics.rms}"
    }
}
