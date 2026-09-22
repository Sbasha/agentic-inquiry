enum DynamicMetrics {
    static func run(name: String = "summarize") -> String {
        switch name {
        case "summarize":
            return "dynamic:\(SimpleMetrics.summarize())"
        default:
            return "unknown"
        }
    }
}
