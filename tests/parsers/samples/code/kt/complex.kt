package samples

import kotlin.math.abs
import kotlin.math.sqrt

data class ComplexMetrics(val scale: Double = 1.0) {
    fun distance(a: Int, b: Int): Double = abs(a - b) * scale

    fun rootMeanSquare(values: List<Double>): Double {
        if (values.isEmpty()) return 0.0
        val total = values.sumOf { it * it }
        return sqrt(total / values.size)
    }

    companion object {
        fun buildDefault() = ComplexMetrics(0.86)
    }
}
