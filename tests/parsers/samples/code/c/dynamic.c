#include <stdio.h>

struct Metrics {
    double baseline;
    double rms;
};

struct Metrics run_simple(void);
void summarize(void);

typedef void (*summary_fn)(void);

void run_dynamic(summary_fn fn) {
    fn();
}

int main(void) {
    run_dynamic(summarize);
    return 0;
}
