module SimpleMetrics

using ..ComplexMetrics

export run_simple, summarize

function run_simple()
    settings = ComplexMetrics.build_default()
    baseline = ComplexMetrics.distance(10, 3; scale = settings.scale)
    rms = ComplexMetrics.root_mean_square([1.0, 2.0, 3.0])
    (; baseline, rms)
end

function summarize()
    metrics = run_simple()
    "baseline=$(round(metrics.baseline, digits=2)), rms=$(round(metrics.rms, digits=2))"
end

end
