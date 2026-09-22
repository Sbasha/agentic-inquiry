import 'complex.dart';

Map<String, double> runSimple() {
  final analyzer = ComplexMetrics.buildDefault();
  final rms = analyzer.rootMeanSquare([1.0, 2.0, 3.0]);
  final baseline = analyzer.distance(10, 3);
  return {
    'baseline': baseline,
    'rms': rms,
  };
}

String summarize() {
  final metrics = runSimple();
  return "baseline=${metrics['baseline']?.toStringAsFixed(2)}, rms=${metrics['rms']?.toStringAsFixed(2)}";
}
