module DynamicMetrics

using ..SimpleMetrics

run(name::String = "summarize") = name == "summarize" ? "dynamic:" * SimpleMetrics.summarize() : "unknown"

end
