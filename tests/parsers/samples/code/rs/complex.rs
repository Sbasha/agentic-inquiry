pub struct ComplexMetrics {
    scale: f64,
}

impl ComplexMetrics {
    pub fn new(scale: f64) -> Self {
        Self { scale }
    }

    pub fn distance(&self, a: i32, b: i32) -> f64 {
        ((a - b).abs()) as f64 * self.scale
    }

    pub fn root_mean_square(&self, values: &[f64]) -> f64 {
        if values.is_empty() {
            return 0.0;
        }
        let total: f64 = values.iter().map(|v| v * v).sum();
        (total / values.len() as f64).sqrt()
    }
}

pub fn build_default() -> ComplexMetrics {
    ComplexMetrics::new(0.83)
}
