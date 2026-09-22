class ComplexMetrics {
    double scale = 1.0

    double distance(Number a, Number b) {
        Math.abs(a.doubleValue() - b.doubleValue()) * scale
    }

    double rootMeanSquare(List<Double> values) {
        if (!values) {
            return 0
        }
        double total = values.collect { it * it }.sum()
        Math.sqrt(total / values.size())
    }

    static ComplexMetrics buildDefault() {
        new ComplexMetrics(scale: 0.8)
    }
}
