param(
    [Parameter(Mandatory = $true)]
    [string]$OpenCellIdCsvPath,
    [string]$ProviderMappingPath = "config/provider_mapping.sample.json",
    [string]$OutputRoot = "data"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python is not installed or not available on PATH. Install Python 3.11+ first."
}

python .\scripts\build_real_bangalore_dataset.py `
    --opencellid-csv $OpenCellIdCsvPath `
    --provider-mapping $ProviderMappingPath `
    --output-root $OutputRoot
