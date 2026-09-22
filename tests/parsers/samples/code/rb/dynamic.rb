require_relative 'simple'

module DynamicMetrics
  module_function

  def run(name = :summarize)
    if SimpleMetrics.respond_to?(name)
      "dynamic:#{SimpleMetrics.send(name)}"
    else
      'unknown'
    end
  end
end
