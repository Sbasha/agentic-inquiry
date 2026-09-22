using System;
using System.Reflection;

namespace Samples {
    public static class DynamicMetrics {
        public static object Run(string methodName = "Summarize") {
            MethodInfo? method = typeof(SimpleMetrics).GetMethod(methodName, BindingFlags.Public | BindingFlags.Static);
            if (method == null) {
                throw new InvalidOperationException($"Method {methodName} not found");
            }
            return method.Invoke(null, null) ?? string.Empty;
        }
    }
}
