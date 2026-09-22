package DynamicMetrics;
use strict;
use warnings;

use SimpleMetrics;

sub run {
    my ($name) = @_;
    $name //= 'summarize';
    if (SimpleMetrics->can($name)) {
        return 'dynamic:' . SimpleMetrics->$name();
    }
    return 'unknown';
}

1;
