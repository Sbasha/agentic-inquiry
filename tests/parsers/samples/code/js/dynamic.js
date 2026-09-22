export async function runDynamic(name = "summarize") {
    const module = await import("./simple.js");
    const action = module[name];
    if (!action) {
        return "dynamic:unknown";
    }
    const result = action();
    if (typeof result === "object") {
        return `dynamic:${result.baseline.toFixed(1)}:${result.rms.toFixed(1)}`;
    }
    return `dynamic:${result}`;
}

export function eagerPreview() {
    return import("./complex.js").then(({ ComplexAnalyzer }) => {
        const analyzer = new ComplexAnalyzer(1.2);
        return analyzer.distance(12, 3);
    });
}
