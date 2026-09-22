const std = @import("std");
const simple = @import("simple.zig");

pub fn runDynamic(allocator: std.mem.Allocator, name: []const u8) ![]u8 {
    if (std.mem.eql(u8, name, "summarize")) {
        const metrics = simple.summarize();
        return std.fmt.allocPrint(allocator, "dynamic:{d:.2}:{d:.2}", .{ metrics.baseline, metrics.rms });
    }
    return std.fmt.allocPrint(allocator, "unknown", .{});
}
