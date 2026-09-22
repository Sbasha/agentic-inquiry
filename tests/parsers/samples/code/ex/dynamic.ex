defmodule DynamicMetrics do
  def run(name \\ :summarize) do
    apply(SimpleMetrics, name, [])
  end
end
