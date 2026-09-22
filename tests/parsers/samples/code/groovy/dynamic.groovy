class DynamicMetrics {
    static String run(String name = 'summarize') {
        def method = SimpleMetrics.metaClass.getMetaMethod(name)
        if (!method) {
            return 'unknown'
        }
        "dynamic:${method.invoke(SimpleMetrics, null)}"
    }
}
