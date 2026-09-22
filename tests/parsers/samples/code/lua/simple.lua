local complex = require("complex")

local simple = {}

function simple.run_simple()
    local settings = complex.build_default()
    local baseline = complex.distance(10, 3) * settings.scale
    local rms = complex.root_mean_square({ 1, 2, 3 })
    return { baseline = baseline, rms = rms }
end

function simple.summarize()
    local metrics = simple.run_simple()
    return string.format("baseline=%.2f, rms=%.2f", metrics.baseline, metrics.rms)
end

return simple
