const std = @import("std");

pub const ComplexMetrics = struct {
    scale: f64 = 1.0,

    pub fn distance(self: ComplexMetrics, a: i32, b: i32) f64 {
        return @floatFromInt(std.math.absInt(a - b)) * self.scale;
    }

    pub fn rootMeanSquare(self: ComplexMetrics, values: []const f64) f64 {
        if (values.len == 0) return 0;
        var total: f64 = 0;
        for (values) |value| {
            total += value * value;
        }
        return std.math.sqrt(total / @floatFromInt(values.len)) * self.scale;
    }
};

pub fn buildDefault() ComplexMetrics {
    return .{ .scale = 0.81 };
}
