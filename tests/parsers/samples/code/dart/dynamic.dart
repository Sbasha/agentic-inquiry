import 'simple.dart';

typedef SummaryAction = String Function();

final Map<String, SummaryAction> registry = <String, SummaryAction>{
  'summarize': summarize,
};

String runDynamic([String name = 'summarize']) {
  final action = registry[name];
  if (action == null) {
    return 'unknown action';
  }
  return 'dynamic:${action()}';
}
