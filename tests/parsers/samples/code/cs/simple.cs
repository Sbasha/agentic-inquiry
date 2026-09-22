using System.Collections.Generic;

namespace Samples {
    public static class SimpleMetrics {
        public static IDictionary<string, double> RunSimple() {
            var analyzer = ComplexMetrics.BuildDefault();
            return new Dictionary<string, double> {
                ["baseline"] = analyzer.Distance(10, 3),
                ["rms"] = analyzer.RootMeanSquare(new [] { 1.0, 2.0, 3.0 })
            };
        }

        public static string Summarize() {
            var metrics = RunSimple();
            return $"Summary: baseline={metrics[\"baseline\"]:0.00}, rms={metrics[\"rms\"]:0.00}";
        }
    }
}
