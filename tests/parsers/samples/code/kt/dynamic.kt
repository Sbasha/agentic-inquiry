package samples

val registry: Map<String, () -> String> = mapOf(
    "summarize" to ::summarize
)

fun runDynamic(name: String = "summarize"): String {
    val action = registry[name] ?: return "unknown"
    return "dynamic:${action()}"
}
