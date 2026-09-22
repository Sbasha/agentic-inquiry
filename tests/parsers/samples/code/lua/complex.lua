local complex = {}

function complex.distance(a, b)
    return math.abs(a - b)
end

function complex.root_mean_square(values)
    if #values == 0 then
        return 0
    end
    local total = 0
    for _, value in ipairs(values) do
        total = total + value * value
    end
    return math.sqrt(total / #values)
end

function complex.build_default()
    return { scale = 0.8 }
end

return complex
