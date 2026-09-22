export async function runDynamic(name = "summarize"): Promise<string> {
    const module = await import("./simple");
    const action = (module as Record<string, () => unknown>)[name];
    if (typeof action !== "function") {
        return "dynamic:unknown";
    }
    const result = action();
    if (typeof result === "object" && result !== null && "baseline" in (result as Record<string, unknown>)) {
        const data = result as { baseline: number; rms: number };
        return `dynamic:${data.baseline.toFixed(1)}:${data.rms.toFixed(1)}`;
    }
    return `dynamic:${String(result)}`;
}

export function eagerPreview(): Promise<number> {
    return import("./complex").then(({ ComplexAnalyzer }) => {
        const analyzer = new ComplexAnalyzer(1.1);
        return analyzer.distance(12, 4);
    });
}
