import Foundation

struct ComplexMetrics {
    let scale: Double

    init(scale: Double = 1.0) {
        self.scale = scale
    }

    func distance(_ a: Int, _ b: Int) -> Double {
        return abs(Double(a - b)) * scale
    }

    func rootMeanSquare(_ values: [Double]) -> Double {
        guard !values.isEmpty else { return 0 }
        let total = values.reduce(0) { $0 + $1 * $1 }
        return sqrt(total / Double(values.count))
    }

    static func buildDefault() -> ComplexMetrics {
        ComplexMetrics(scale: 0.87)
    }
}
