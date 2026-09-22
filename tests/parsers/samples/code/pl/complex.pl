package ComplexMetrics;
use strict;
use warnings;

sub distance {
    my ($a, $b, $scale) = @_;
    $scale //= 1;
    return abs($a - $b) * $scale;
}

sub root_mean_square {
    my (@values) = @_;
    return 0 unless @values;
    my $total = 0;
    $total += $_ * $_ for @values;
    return sqrt($total / scalar @values);
}

1;
