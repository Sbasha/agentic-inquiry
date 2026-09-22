module ComplexMetrics

export distance, root_mean_square, build_default

distance(a::Number, b::Number; scale::Float64 = 1.0) = abs(a - b) * scale

function root_mean_square(values::AbstractVector{<:Number})
    isempty(values) && return 0.0
    total = sum(value -> value ^ 2, values)
    sqrt(total / length(values))
end

build_default() = (scale = 0.82,)

end
