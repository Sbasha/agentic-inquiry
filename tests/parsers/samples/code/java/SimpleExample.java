public class SimpleExample {
    public static class Metrics {
        public final double baseline;
        public final double rms;

        public Metrics(double baseline, double rms) {
            this.baseline = baseline;
            this.rms = rms;
        }
    }

    public Metrics runSimple() {
        ComplexExample analyzer = ComplexExample.buildDefault();
        double baseline = analyzer.distance(10, 3);
        double rms = analyzer.rootMeanSquare(java.util.Arrays.asList(1, 2, 3));
        return new Metrics(baseline, rms);
    }

    public String summarize() {
        Metrics metrics = runSimple();
        return String.format("baseline=%.2f, rms=%.2f", metrics.baseline, metrics.rms);
    }
}
