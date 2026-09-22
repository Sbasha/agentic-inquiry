public with sharing class SimpleService {
    public class Metrics {
        public Decimal baseline;
        public Decimal rms;
    }

    public static Metrics summarize() {
        Metrics metrics = new Metrics();
        metrics.baseline = ComplexController.distance(10, 3);
        metrics.rms = ComplexController.normalizeScore(new List<Integer>{1, 2, 3});
        return metrics;
    }
}
