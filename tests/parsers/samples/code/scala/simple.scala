package samples

case class Metrics(baseline: Double, rms: Double)

object SimpleMetrics {
  def runSimple(): Metrics = {
    val baseline = ComplexMetrics.distance(10, 3, 0.84)
    val rms = ComplexMetrics.rootMeanSquare(List(1.0, 2.0, 3.0))
    Metrics(baseline, rms)
  }

  def summarize(): String = {
    val metrics = runSimple()
    f"baseline=${metrics.baseline}%.2f, rms=${metrics.rms}%.2f"
  }
}
