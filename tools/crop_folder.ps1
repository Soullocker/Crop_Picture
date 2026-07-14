param(
    [string]$InputDir,
    [string]$OutputDir,
    [int]$Padding = 8
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

$pythonExe = Resolve-Path (Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe")
$scriptPath = Resolve-Path (Join-Path $PSScriptRoot "..\scripts\crop_picture.py")

Write-Host "Crop blank margins from all images in a folder"
Write-Host ""

if (-not $PSBoundParameters.ContainsKey("InputDir") -or [string]::IsNullOrWhiteSpace($InputDir)) {
    $InputDir = Read-Host "Input image folder path"
}

if (-not $PSBoundParameters.ContainsKey("OutputDir") -or [string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = Read-Host "Output folder path"
}

if (-not $PSBoundParameters.ContainsKey("Padding")) {
    $paddingText = Read-Host "Padding pixels, press Enter for 8"
    if (-not [string]::IsNullOrWhiteSpace($paddingText)) {
        $Padding = [int]$paddingText
    }
}

& $pythonExe $scriptPath --input $InputDir --output $OutputDir --padding $Padding
exit $LASTEXITCODE
