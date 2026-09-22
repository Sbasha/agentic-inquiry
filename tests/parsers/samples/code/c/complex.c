#include <math.h>

double complex_distance(int a, int b) {
    return fabs((double)a - (double)b);
}

double complex_rms(const double *values, int count) {
    if (count == 0) {
        return 0.0;
    }
    double total = 0.0;
    for (int i = 0; i < count; ++i) {
        total += values[i] * values[i];
    }
    return sqrt(total / count);
}
