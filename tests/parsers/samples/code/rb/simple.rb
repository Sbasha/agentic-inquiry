require_relative 'complex'

module SimpleMetrics
  module_function

  def run_simple
    {
      baseline: ComplexMetrics.distance(10, 3, 0.8),
      rms: ComplexMetrics.root_mean_square([1.0, 2.0, 3.0])
    }
  end

  def summarize
    metrics = run_simple
    format('baseline=%.2f, rms=%.2f', metrics[:baseline], metrics[:rms])
  end
end
