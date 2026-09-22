package samples

object ComplexMetrics {
  def distance(a: Int, b: Int, scale: Double = 1.0): Double = math.abs(a - b) * scale

  def rootMeanSquare(values: List[Double]): Double = {
    if (values.isEmpty) 0.0
    else math.sqrt(values.map(v => v * v).sum / values.length)
  }
}
