package samples

data class Metrics(val baseline: Double, val rms: Double)

fun runSimple(): Metrics {
    val analyzer = ComplexMetrics.buildDefault()
    val rms = analyzer.rootMeanSquare(listOf(1.0, 2.0, 3.0))
    val baseline = analyzer.distance(10, 3)
    return Metrics(baseline, rms)
}

fun summarize(): String {
    val metrics = runSimple()
    return "baseline=${metrics.baseline}, rms=${String.format("%.2f", metrics.rms)}"
}
