package SimpleMetrics;
use strict;
use warnings;

use ComplexMetrics;

sub run_simple {
    my %metrics = (
        baseline => ComplexMetrics::distance(10, 3, 0.8),
        rms      => ComplexMetrics::root_mean_square(1, 2, 3)
    );
    return \%metrics;
}

sub summarize {
    my $metrics = run_simple();
    return sprintf 'baseline=%.2f, rms=%.2f', $metrics->{baseline}, $metrics->{rms};
}

1;
