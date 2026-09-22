use crate::complex::{build_default, ComplexMetrics};

pub struct Metrics {
    pub baseline: f64,
    pub rms: f64,
}

pub fn run_simple() -> Metrics {
    let analyzer = build_default();
    Metrics {
        baseline: analyzer.distance(10, 3),
        rms: analyzer.root_mean_square(&[1.0, 2.0, 3.0]),
    }
}

pub fn summarize() -> String {
    let metrics = run_simple();
    format!("baseline={:.2}, rms={:.2}", metrics.baseline, metrics.rms)
}
