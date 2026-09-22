using System;
using System.Collections.Generic;
using System.Linq;

namespace Samples {
    public class ComplexMetrics {
        public double Scale { get; }

        public ComplexMetrics(double scale = 1.0) {
            Scale = scale;
        }

        public double Distance(double a, double b) {
            return Math.Abs(a - b) * Scale;
        }

        public double RootMeanSquare(IEnumerable<double> values) {
            var list = values.ToList();
            if (list.Count == 0) {
                return 0;
            }
            var total = list.Sum(v => v * v);
            return Math.Sqrt(total / list.Count);
        }

        public static ComplexMetrics BuildDefault() {
            return new ComplexMetrics(0.85);
        }
    }
}
