defmodule SimpleMetrics do
  alias ComplexMetrics, as: Complex

  def run_simple do
    analyzer = Complex.build_default()
    baseline = Complex.distance(10, 3, analyzer.scale)
    rms = Complex.root_mean_square([1.0, 2.0, 3.0])
    %{baseline: baseline, rms: rms}
  end

  def summarize do
    metrics = run_simple()
    "baseline=#{Float.round(metrics.baseline, 2)}, rms=#{Float.round(metrics.rms, 2)}"
  end
end
