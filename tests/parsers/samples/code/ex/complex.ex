defmodule ComplexMetrics do
  @moduledoc """
  Complex analytics helpers used across modules.
  """

  def distance(a, b, scale \\ 1.0) do
    abs(a - b) * scale
  end

  def root_mean_square(values) when is_list(values) do
    case values do
      [] ->
        0.0

      _ ->
        total = Enum.reduce(values, 0.0, fn value, acc -> acc + value * value end)
        :math.sqrt(total / length(values))
    end
  end

  def build_default do
    %{scale: 0.9}
  end
end
