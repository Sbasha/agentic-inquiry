package samples

object DynamicMetrics {
  private val registry: Map[String, () => String] = Map(
    "summarize" -> (() => SimpleMetrics.summarize())
  )

  def runDynamic(name: String = "summarize"): String =
    registry.get(name).map(fn => s"dynamic:${fn()}").getOrElse("unknown")
}
