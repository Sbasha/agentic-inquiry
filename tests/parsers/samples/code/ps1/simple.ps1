. ./complex.ps1

function Invoke-SimpleMetrics {
    $metrics = Invoke-ComplexMetrics -A 10 -B 3 -Values @(1, 2, 3)
    return [pscustomobject]@{
        Baseline = $metrics.Distance
        RMS = $metrics.RMS
    }
}

function Get-Summary {
    $metrics = Invoke-SimpleMetrics
    return "baseline=$($metrics.Baseline), rms=$([math]::Round($metrics.RMS, 2))"
}
