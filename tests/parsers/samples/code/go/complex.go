package samples

import "math"

type ComplexMetrics struct {
	Scale float64
}

func NewComplexMetrics() ComplexMetrics {
	return ComplexMetrics{Scale: 0.85}
}

func (c ComplexMetrics) Distance(a, b int) float64 {
	return math.Abs(float64(a-b)) * c.Scale
}

func (c ComplexMetrics) RootMeanSquare(values []float64) float64 {
	if len(values) == 0 {
		return 0
	}
	total := 0.0
	for _, v := range values {
		total += v * v
	}
	return math.Sqrt(total / float64(len(values)))
}
