const std = @import("std");
const complex = @import("complex.zig");

pub const Metrics = struct {
    baseline: f64,
    rms: f64,
};

pub fn runSimple() Metrics {
    const analyzer = complex.buildDefault();
    const values = [_]f64{ 1, 2, 3 };
    return .{
        .baseline = analyzer.distance(10, 3),
        .rms = analyzer.rootMeanSquare(&values),
    };
}

pub fn summarize() Metrics {
    return runSimple();
}
