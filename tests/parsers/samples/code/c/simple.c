#include <stdio.h>

double complex_distance(int a, int b);
double complex_rms(const double *values, int count);

struct Metrics {
    double baseline;
    double rms;
};

struct Metrics run_simple(void) {
    struct Metrics metrics;
    double values[3] = {1.0, 2.0, 3.0};
    metrics.baseline = complex_distance(10, 3);
    metrics.rms = complex_rms(values, 3);
    return metrics;
}

void summarize(void) {
    struct Metrics metrics = run_simple();
    printf("baseline=%.2f, rms=%.2f\n", metrics.baseline, metrics.rms);
}
