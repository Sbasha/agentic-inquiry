. ./simple.ps1

function Invoke-Dynamic {
    param([string]$Name = 'Get-Summary')
    if (Get-Command $Name -ErrorAction SilentlyContinue) {
        return "dynamic:$(Invoke-Expression $Name)"
    }
    return 'unknown'
}
