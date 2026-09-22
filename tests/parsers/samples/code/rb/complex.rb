module ComplexMetrics
  module_function

  def distance(a, b, scale = 1.0)
    (a - b).abs * scale
  end

  def root_mean_square(values)
    return 0.0 if values.empty?
    total = values.reduce(0.0) { |acc, value| acc + value * value }
    Math.sqrt(total / values.length)
  end
end
