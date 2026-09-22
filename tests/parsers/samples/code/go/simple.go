package samples

import "fmt"

type Metrics struct {
	Baseline float64
	RMS      float64
}

func RunSimple() Metrics {
	analyzer := NewComplexMetrics()
	return Metrics{
		Baseline: analyzer.Distance(10, 3),
		RMS:      analyzer.RootMeanSquare([]float64{1, 2, 3}),
	}
}

func Summarize() string {
	metrics := RunSimple()
	return fmt.Sprintf("baseline=%.2f, rms=%.2f", metrics.Baseline, metrics.RMS)
}
