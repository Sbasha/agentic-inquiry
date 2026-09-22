#include <string>
#include <vector>

#include "complex.cpp"

struct Metrics {
    double baseline;
    double rms;
};

Metrics run_simple() {
    auto analyzer = build_default_analyzer();
    Metrics metrics{analyzer.distance(10, 3), analyzer.root_mean_square({1.0, 2.0, 3.0})};
    return metrics;
}

std::string summarize() {
    Metrics metrics = run_simple();
    return "baseline=" + std::to_string(metrics.baseline) + ", rms=" + std::to_string(metrics.rms);
}
