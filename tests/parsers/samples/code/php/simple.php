<?php

namespace Samples;

use Samples\ComplexMetrics;

function run_simple(): array
{
    $analyzer = ComplexMetrics::buildDefault();
    return [
        'baseline' => $analyzer->distance(10, 3),
        'rms' => $analyzer->rootMeanSquare([1.0, 2.0, 3.0]),
    ];
}

function summarize(): string
{
    $metrics = run_simple();
    return sprintf('baseline=%.2f, rms=%.2f', $metrics['baseline'], $metrics['rms']);
}
