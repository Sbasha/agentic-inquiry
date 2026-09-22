<?php

namespace Samples;

function run_dynamic(string $name = 'summarize'): string
{
    if (!function_exists(__NAMESPACE__ . "\\$name")) {
        return 'unknown';
    }
    $callable = __NAMESPACE__ . "\\$name";
    return 'dynamic:' . $callable();
}
