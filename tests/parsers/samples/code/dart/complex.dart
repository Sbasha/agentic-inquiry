import 'dart:math';

class ComplexMetrics {
  const ComplexMetrics({this.scale = 1.0});

  final double scale;

  double distance(num a, num b) {
    return (a - b).abs() * scale;
  }

  double rootMeanSquare(List<double> values) {
    if (values.isEmpty) {
      return 0;
    }
    final total = values.map((v) => v * v).reduce((a, b) => a + b);
    return sqrt(total / values.length);
  }

  static ComplexMetrics buildDefault() => const ComplexMetrics(scale: 0.8);
}
