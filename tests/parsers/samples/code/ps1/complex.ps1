function Invoke-ComplexMetrics {
    param (
        [int]$A,
        [int]$B,
        [double[]]$Values
    )

    $distance = [math]::Abs($A - $B)

    if (-not $Values -or $Values.Length -eq 0) {
        $rms = 0
    }
    else {
        $total = ($Values | ForEach-Object { $_ * $_ }) -as [double[]]
        $rms = [math]::Sqrt(($total | Measure-Object -Sum).Sum / $Values.Length)
    }

    return [pscustomobject]@{
        Distance = $distance
        RMS = $rms
    }
}
