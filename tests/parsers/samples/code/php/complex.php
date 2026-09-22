<?php

namespace Samples;

class ComplexMetrics
{
    public function __construct(private float $scale = 1.0)
    {
    }

    public function distance(int $a, int $b): float
    {
        return abs($a - $b) * $this->scale;
    }

    public function rootMeanSquare(array $values): float
    {
        if (count($values) === 0) {
            return 0.0;
        }
        $total = array_reduce($values, fn ($carry, $value) => $carry + $value * $value, 0.0);
        return sqrt($total / count($values));
    }

    public static function buildDefault(): self
    {
        return new self(0.88);
    }
}
